"""
Reports & Analytics is the one module that legitimately needs to read
every other module's data, so its cross-module logic lives here rather
than in the route file, following the same app/services/ pattern used by
accounting.py and inventory.py. Unlike those two, nothing here WRITES
anything - every function is read-only, computing numbers live from
whatever the other 9 modules have already produced. Nothing in this file
is ever cached or stored (the SavedReport model only stores which
filters were chosen, never the results) - the same "never store what you
can calculate" principle used for stock levels and dashboard counts.
"""
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.crm import Lead, Opportunity
from app.models.sales import Invoice, SalesOrder, SalesOrderItem, Product, Quotation
from app.models.finance import ChartOfAccounts, JournalEntry, JournalLine
from app.models.inventory import StockLevel
from app.models.procurement import PurchaseOrder, Vendor
from app.models.hr import Employee, Department, Payslip, PayrollRun, LeaveRequest
from app.models.projects import Project, Task


def _num(value) -> float:
    """Decimal -> float, so every response is plain JSON-friendly numbers."""
    return float(value) if value is not None else 0.0


def sales_summary(db: Session, org_id: str, months: int = 6) -> dict:
    cutoff = date.today().replace(day=1) - timedelta(days=31 * (months - 1))

    monthly_rows = (
        db.query(
            func.to_char(Invoice.created_at, "YYYY-MM").label("month"),
            func.sum(Invoice.amount).label("total"),
        )
        .filter(Invoice.org_id == org_id, Invoice.created_at >= cutoff)
        .group_by("month")
        .order_by("month")
        .all()
    )

    top_product_rows = (
        db.query(
            Product.name,
            func.sum(SalesOrderItem.qty * SalesOrderItem.unit_price).label("revenue"),
        )
        .join(SalesOrderItem, SalesOrderItem.product_id == Product.id)
        .join(SalesOrder, SalesOrder.id == SalesOrderItem.order_id)
        .filter(Product.org_id == org_id)
        .group_by(Product.name)
        .order_by(func.sum(SalesOrderItem.qty * SalesOrderItem.unit_price).desc())
        .limit(5)
        .all()
    )

    won = db.query(Opportunity).filter(Opportunity.org_id == org_id, Opportunity.stage == "won").count()
    lost = db.query(Opportunity).filter(Opportunity.org_id == org_id, Opportunity.stage == "lost").count()
    decided = won + lost

    return {
        "monthly_revenue": [{"month": r.month, "total": _num(r.total)} for r in monthly_rows],
        "top_products": [{"name": r.name, "revenue": _num(r.revenue)} for r in top_product_rows],
        "funnel": {
            "leads": db.query(Lead).filter(Lead.org_id == org_id).count(),
            "opportunities": db.query(Opportunity).filter(Opportunity.org_id == org_id).count(),
            "quotations": db.query(Quotation).filter(Quotation.org_id == org_id).count(),
            "sales_orders": db.query(SalesOrder).filter(SalesOrder.org_id == org_id).count(),
            "invoices": db.query(Invoice).filter(Invoice.org_id == org_id).count(),
        },
        "win_rate_pct": round((won / decided) * 100, 1) if decided else None,
    }


def finance_summary(db: Session, org_id: str, months: int = 6) -> dict:
    cutoff = date.today().replace(day=1) - timedelta(days=31 * (months - 1))

    def _total(account_type: str, side: str) -> float:
        column = JournalLine.credit if side == "credit" else JournalLine.debit
        total = (
            db.query(func.sum(column))
            .join(ChartOfAccounts, ChartOfAccounts.id == JournalLine.account_id)
            .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
            .filter(ChartOfAccounts.org_id == org_id, ChartOfAccounts.account_type == account_type)
            .scalar()
        )
        return _num(total)

    total_revenue = _total("revenue", "credit")
    total_expense = _total("expense", "debit")

    monthly_rows = (
        db.query(
            func.to_char(JournalEntry.date, "YYYY-MM").label("month"),
            ChartOfAccounts.account_type.label("account_type"),
            func.sum(JournalLine.credit - JournalLine.debit).label("net"),
        )
        .join(JournalLine, JournalLine.journal_entry_id == JournalEntry.id)
        .join(ChartOfAccounts, ChartOfAccounts.id == JournalLine.account_id)
        .filter(
            JournalEntry.org_id == org_id,
            JournalEntry.date >= cutoff,
            ChartOfAccounts.account_type.in_(["revenue", "expense"]),
        )
        .group_by("month", ChartOfAccounts.account_type)
        .order_by("month")
        .all()
    )
    monthly: dict[str, dict[str, float]] = {}
    for r in monthly_rows:
        bucket = monthly.setdefault(r.month, {"revenue": 0.0, "expense": 0.0})
        if r.account_type == "revenue":
            bucket["revenue"] += _num(r.net)
        else:
            bucket["expense"] += -_num(r.net)  # expense lines are debits, net comes out negative

    today = date.today()
    unpaid = db.query(Invoice).filter(Invoice.org_id == org_id, Invoice.status == "unpaid").all()
    aging = {"0_30": 0.0, "31_60": 0.0, "61_90": 0.0, "90_plus": 0.0}
    for inv in unpaid:
        age_days = (today - inv.due_date).days if inv.due_date else 0
        amount = _num(inv.amount)
        if age_days <= 30:
            aging["0_30"] += amount
        elif age_days <= 60:
            aging["31_60"] += amount
        elif age_days <= 90:
            aging["61_90"] += amount
        else:
            aging["90_plus"] += amount

    return {
        "total_revenue": total_revenue,
        "total_expense": total_expense,
        "net_profit": round(total_revenue - total_expense, 2),
        "monthly_revenue_expense": [
            {"month": m, "revenue": round(v["revenue"], 2), "expense": round(v["expense"], 2)}
            for m, v in sorted(monthly.items())
        ],
        "accounts_receivable_aging": {k: round(v, 2) for k, v in aging.items()},
        "unpaid_invoice_count": len(unpaid),
    }


def inventory_summary(db: Session, org_id: str) -> dict:
    rows = (
        db.query(Product, StockLevel.quantity)
        .outerjoin(StockLevel, StockLevel.product_id == Product.id)
        .filter(Product.org_id == org_id)
        .all()
    )

    total_valuation = 0.0
    low_stock = []
    for product, qty in rows:
        qty = qty or 0
        total_valuation += qty * _num(product.unit_price)
        if product.reorder_level > 0 and qty <= product.reorder_level:
            low_stock.append({"name": product.name, "sku": product.sku, "quantity": qty, "reorder_level": product.reorder_level})

    return {
        "total_products": len(rows),
        "stock_valuation": round(total_valuation, 2),
        "low_stock_items": low_stock,
        "low_stock_count": len(low_stock),
    }


def procurement_summary(db: Session, org_id: str) -> dict:
    vendor_rows = (
        db.query(Vendor.name, func.sum(PurchaseOrder.total).label("spend"), func.count(PurchaseOrder.id).label("orders"))
        .join(PurchaseOrder, PurchaseOrder.vendor_id == Vendor.id)
        .filter(Vendor.org_id == org_id)
        .group_by(Vendor.name)
        .order_by(func.sum(PurchaseOrder.total).desc())
        .all()
    )

    status_rows = (
        db.query(PurchaseOrder.status, func.count(PurchaseOrder.id))
        .filter(PurchaseOrder.org_id == org_id)
        .group_by(PurchaseOrder.status)
        .all()
    )

    return {
        "spend_by_vendor": [{"vendor": r.name, "spend": _num(r.spend), "orders": r.orders} for r in vendor_rows],
        "status_breakdown": {status: count for status, count in status_rows},
        "total_spend": round(sum(_num(r.spend) for r in vendor_rows), 2),
    }


def hr_summary(db: Session, org_id: str, months: int = 6) -> dict:
    cutoff = date.today().replace(day=1) - timedelta(days=31 * (months - 1))

    headcount_rows = (
        db.query(Department.name, func.count(Employee.id))
        .join(Employee, Employee.department_id == Department.id)
        .filter(Department.org_id == org_id, Employee.status == "active")
        .group_by(Department.name)
        .all()
    )

    payroll_rows = (
        db.query(PayrollRun.year, PayrollRun.month, func.sum(Payslip.net_pay).label("total"))
        .join(Payslip, Payslip.payroll_run_id == PayrollRun.id)
        .filter(PayrollRun.org_id == org_id, PayrollRun.status == "processed")
        .group_by(PayrollRun.year, PayrollRun.month)
        .order_by(PayrollRun.year, PayrollRun.month)
        .all()
    )

    return {
        "headcount_by_department": [{"department": name, "count": count} for name, count in headcount_rows],
        "active_employees": db.query(Employee).filter(Employee.org_id == org_id, Employee.status == "active").count(),
        "payroll_cost_by_month": [
            {"month": f"{r.year:04d}-{r.month:02d}", "total": _num(r.total)} for r in payroll_rows
        ],
        "pending_leave_requests": db.query(LeaveRequest).join(
            Employee, Employee.id == LeaveRequest.employee_id
        ).filter(Employee.org_id == org_id, LeaveRequest.status == "pending").count(),
    }


def crm_funnel(db: Session, org_id: str) -> dict:
    lead_rows = db.query(Lead.status, func.count(Lead.id)).filter(Lead.org_id == org_id).group_by(Lead.status).all()
    stage_rows = (
        db.query(Opportunity.stage, func.count(Opportunity.id))
        .filter(Opportunity.org_id == org_id)
        .group_by(Opportunity.stage)
        .all()
    )
    stage_value_rows = (
        db.query(Opportunity.stage, func.sum(Opportunity.value))
        .filter(Opportunity.org_id == org_id)
        .group_by(Opportunity.stage)
        .all()
    )

    total_leads = db.query(Lead).filter(Lead.org_id == org_id).count()
    converted_leads = db.query(Lead).filter(Lead.org_id == org_id, Lead.status == "converted").count()

    return {
        "leads_by_status": {status: count for status, count in lead_rows},
        "opportunities_by_stage": {stage: count for stage, count in stage_rows},
        "pipeline_value_by_stage": {stage: _num(value) for stage, value in stage_value_rows},
        "lead_conversion_pct": round((converted_leads / total_leads) * 100, 1) if total_leads else None,
    }


def projects_summary(db: Session, org_id: str) -> dict:
    status_rows = (
        db.query(Project.status, func.count(Project.id)).filter(Project.org_id == org_id).group_by(Project.status).all()
    )
    open_tasks = (
        db.query(Task)
        .join(Project, Project.id == Task.project_id)
        .filter(Project.org_id == org_id, Task.status != "done")
        .count()
    )
    return {
        "projects_by_status": {status: count for status, count in status_rows},
        "open_tasks": open_tasks,
    }


REPORT_FUNCTIONS = {
    "sales": sales_summary,
    "finance": finance_summary,
    "inventory": inventory_summary,
    "procurement": procurement_summary,
    "hr": hr_summary,
    "crm": crm_funnel,
    "projects": projects_summary,
}
