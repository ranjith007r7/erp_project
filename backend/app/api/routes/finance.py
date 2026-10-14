"""
Finance module routes. Two read-only views (accounts, journal entries) plus
one real action: recording a Payment against an Invoice, which posts its
own Journal Entry through the same shared accounting service Sales uses.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.api.deps import get_current_user, get_org_id, require_permission
import re
from decimal import Decimal

from app.models.finance import ChartOfAccounts, JournalEntry, Payment, Refund
from app.models.user import User
from app.models.workpage import WorkOrder
from app.models.sales import Invoice
from app.schemas.finance import (
    AccountOut, JournalEntryOut, RefundOut, RefundComplete, PaymentCreate, PaymentOut, METHODS_NEEDING_REFERENCE,
    DeductionProfileIn, DeductionRow, LopIn, LeaveTypeOut, RunSummary,
)
from app.models.hr import Employee, EmployeePayrollProfile, PayrollRun, PayrollInput
from app.services.payroll import get_leave_types, lop_days_from_approved_leave
from app.services.accounting import post_payment_journal_entry
from app.services.notifications import notify_role
from app.services.audit import log_audit_event
from app.services import workpages

router = APIRouter(prefix="/api/finance", tags=["finance"], dependencies=[Depends(get_current_user)])

TXN_RE = re.compile(r"^[A-Za-z0-9._\-/]{4,64}$")


@router.get("/accounts", response_model=list[AccountOut], dependencies=[Depends(require_permission("finance", "view"))])
def list_accounts(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return db.query(ChartOfAccounts).filter(ChartOfAccounts.org_id == org_id).order_by(ChartOfAccounts.code).all()


@router.get("/journal-entries", response_model=list[JournalEntryOut], dependencies=[Depends(require_permission("finance", "view"))])
def list_journal_entries(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return (
        db.query(JournalEntry)
        .options(joinedload(JournalEntry.lines))
        .filter(JournalEntry.org_id == org_id)
        .order_by(JournalEntry.date.desc(), JournalEntry.entry_number.desc())
        .all()
    )


@router.post("/payments", response_model=PaymentOut, status_code=201, dependencies=[Depends(require_permission("finance", "create"))])
def record_payment(payload: PaymentCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    """
    Records money received against an Invoice, marks the Invoice paid (or
    partially - see note below), and posts the matching Journal Entry -
    same commit-together guarantee as Sales' invoice generation.
    """
    invoice = db.query(Invoice).filter(Invoice.id == payload.invoice_id, Invoice.org_id == org_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status == "paid":
        raise HTTPException(status_code=400, detail="This invoice is already fully paid.")
    if invoice.status == "cancelled":
        raise HTTPException(status_code=400, detail="This invoice was cancelled with a credit note; no payment can be recorded against it.")

    paid_so_far = Decimal(db.query(func.coalesce(func.sum(Payment.amount), 0)).filter(Payment.invoice_id == invoice.id).scalar() or 0)
    due = Decimal(invoice.amount) - paid_so_far
    if Decimal(payload.amount) > due:
        raise HTTPException(status_code=400, detail=f"This payment ({payload.amount}) is more than the amount still due on the invoice ({due}).")

    txn = (payload.transaction_id or "").strip() or None
    if payload.method in METHODS_NEEDING_REFERENCE:
        label = {"card": "card", "gpay": "GPay", "bank_transfer": "bank transfer"}[payload.method]
        if not txn:
            raise HTTPException(status_code=400, detail=f"Enter the transaction ID for the {label} payment. A {label} payment is only recorded with its transaction ID.")
        if not TXN_RE.match(txn):
            raise HTTPException(status_code=400, detail="The transaction ID must be 4-64 characters: letters, numbers, dash, underscore, dot or slash.")
        if db.query(Payment.id).filter(Payment.org_id == org_id, Payment.transaction_id == txn).first():
            raise HTTPException(status_code=400, detail=f"Transaction ID {txn} is already recorded against another payment.")
    else:
        txn = None  # cash has no reference

    payment = Payment(
        org_id=org_id,
        invoice_id=invoice.id,
        amount=payload.amount,
        method=payload.method,
        transaction_id=txn,
        recorded_by=current_user.id,
    )
    db.add(payment)
    db.flush()  # generates payment.id for the journal entry reference

    try:
        note = {"cash": "Cash", "card": "Card", "gpay": "GPay", "bank_transfer": "Bank transfer"}[payload.method]
        if txn:
            note += f", txn {txn}"
        post_payment_journal_entry(db, org_id, str(payment.id), payment.amount, note=note)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Simple model for now: any payment recorded marks the invoice fully
    # paid. Partial-payment tracking (amount_paid vs amount_due) is a
    # reasonable Phase-4-or-later refinement, not needed for the demo story.
    if paid_so_far + Decimal(payment.amount) >= Decimal(invoice.amount):
        invoice.status = "paid"
    workpages.safe(db, workpages.on_invoice_payment, invoice, payment, current_user)

    # Real trigger #1 of 2 for "notifications only cover a few things" -
    # invoice payment recorded is exactly the kind of event a real org
    # would want to know about without someone manually checking Finance.
    notify_role(db, org_id, "Admin", f"Payment of {payment.amount} recorded against an invoice — now marked paid.")

    log_audit_event(db, org_id, current_user.id, "record_payment", "Invoice", invoice.id)
    db.commit()
    db.refresh(payment)
    return payment


@router.get("/payments", response_model=list[PaymentOut], dependencies=[Depends(require_permission("finance", "view"))])
def list_payments(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return db.query(Payment).filter(Payment.org_id == org_id).order_by(Payment.created_at.desc()).all()


# ---------------------------------------------------------------------------
# Payroll deductions. The Finance employee decides, per employee, the PF /
# insurance / TDS percentages, and per payroll run the unpaid-leave (LOP)
# days. Payroll processing (HR module) reads these; it never invents them.
# ---------------------------------------------------------------------------
def _pct(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(Decimal("0.01"))


@router.get("/pricing-check", dependencies=[Depends(require_permission("finance", "view"))])
def pricing_check(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    """MRP / max-discount compliance of works served from inventory: billed price vs the batch's MRP and allowed discount."""
    from app.services import workpages
    rows = workpages.pricing_report(db, org_id)
    return {"checked": len(rows), "violations": sum(1 for r in rows if not r["ok"]), "works": rows}


@router.get("/work-reconciliation", dependencies=[Depends(require_permission("finance", "view"))])
def work_reconciliation(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    """Quoted vs received vs booked, per work. Only quoted = received = booked lets a work be Work done."""
    from app.services import workpages
    rows = workpages.reconciliation_report(db, org_id)
    count = lambda st: sum(1 for r in rows if r["state"] == st)
    return {"works": rows, "matched": count("matched"), "mismatch": count("mismatch"),
            "open": sum(1 for r in rows if r["state"] in ("awaiting_payment", "part_paid", "not_started", "paid_awaiting_delivery", "cancelled_refund_due"))}


@router.get("/leave-types", response_model=list[LeaveTypeOut], dependencies=[Depends(require_permission("finance", "view"))])
def finance_leave_types(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    """The leave legend (shown next to the LOP field so Finance knows which leave is unpaid)."""
    types = get_leave_types(db, org_id)
    db.commit()
    return types


@router.get("/payroll-runs", response_model=list[RunSummary], dependencies=[Depends(require_permission("finance", "view"))])
def finance_payroll_runs(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    """Which payroll runs exist, so Finance can pick the one it is preparing deductions for."""
    return db.query(PayrollRun).filter(PayrollRun.org_id == org_id).order_by(PayrollRun.year.desc(), PayrollRun.month.desc()).all()


@router.get("/payroll-deductions", response_model=list[DeductionRow], dependencies=[Depends(require_permission("finance", "view"))])
def list_payroll_deductions(run_id: str | None = None, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    run = None
    if run_id:
        run = db.query(PayrollRun).filter(PayrollRun.id == run_id, PayrollRun.org_id == org_id).first()
        if not run:
            raise HTTPException(404, "Payroll run not found")
    employees = db.query(Employee).filter(Employee.org_id == org_id, Employee.status == "active").order_by(Employee.employee_code, Employee.name).all()
    profiles = {p.employee_id: p for p in db.query(EmployeePayrollProfile).filter(EmployeePayrollProfile.org_id == org_id).all()}
    inputs = {}
    if run:
        inputs = {i.employee_id: i for i in db.query(PayrollInput).filter(PayrollInput.payroll_run_id == run.id).all()}
    rows = []
    for e in employees:
        p = profiles.get(e.id)
        lop = None
        if run:
            lop = inputs[e.id].lop_days if e.id in inputs else lop_days_from_approved_leave(db, e, run.month, run.year)
        rows.append(DeductionRow(
            employee_id=e.id, employee_code=e.employee_code, name=e.name, designation=e.designation, salary=e.salary,
            configured=p is not None, pf_percent=_pct(p.pf_percent if p else 0),
            insurance_percent=_pct(p.insurance_percent if p else 0), tds_percent=_pct(p.tds_percent if p else 0),
            lop_days=lop,
        ))
    return rows


@router.put("/payroll-deductions/{employee_id}", response_model=DeductionRow, dependencies=[Depends(require_permission("finance", "edit"))])
def set_payroll_deductions(employee_id: str, payload: DeductionProfileIn, db: Session = Depends(get_db),
                           org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    employee = db.query(Employee).filter(Employee.id == employee_id, Employee.org_id == org_id).first()
    if not employee:
        raise HTTPException(404, "Employee not found")
    if payload.pf_percent + payload.insurance_percent + payload.tds_percent > 100:
        raise HTTPException(400, "PF + insurance + TDS cannot add up to more than 100% of salary.")
    profile = db.query(EmployeePayrollProfile).filter(EmployeePayrollProfile.employee_id == employee.id).first()
    if not profile:
        profile = EmployeePayrollProfile(org_id=org_id, employee_id=employee.id)
        db.add(profile)
    profile.pf_percent = payload.pf_percent
    profile.insurance_percent = payload.insurance_percent
    profile.tds_percent = payload.tds_percent
    profile.updated_by = current_user.id
    log_audit_event(db, org_id, current_user.id, "set_payroll_deductions", "Employee", employee.id)
    db.commit()
    return DeductionRow(
        employee_id=employee.id, employee_code=employee.employee_code, name=employee.name, designation=employee.designation,
        salary=employee.salary, configured=True, pf_percent=_pct(payload.pf_percent),
        insurance_percent=_pct(payload.insurance_percent), tds_percent=_pct(payload.tds_percent),
    )


@router.put("/payroll-runs/{run_id}/lop/{employee_id}", response_model=LopIn, dependencies=[Depends(require_permission("finance", "edit"))])
def set_lop_days(run_id: str, employee_id: str, payload: LopIn, db: Session = Depends(get_db),
                 org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    run = db.query(PayrollRun).filter(PayrollRun.id == run_id, PayrollRun.org_id == org_id).first()
    employee = db.query(Employee).filter(Employee.id == employee_id, Employee.org_id == org_id).first()
    if not run or not employee:
        raise HTTPException(404, "Payroll run or employee not found")
    if run.status == "processed":
        raise HTTPException(400, "This payroll run has already been processed, so its leave days can no longer change.")
    import calendar
    if payload.lop_days > calendar.monthrange(run.year, run.month)[1]:
        raise HTTPException(400, "Unpaid leave days cannot be more than the days in that month.")
    row = db.query(PayrollInput).filter(PayrollInput.payroll_run_id == run.id, PayrollInput.employee_id == employee.id).first()
    if not row:
        row = PayrollInput(payroll_run_id=run.id, employee_id=employee.id)
        db.add(row)
    row.lop_days = payload.lop_days
    log_audit_event(db, org_id, current_user.id, "set_payroll_lop_days", "PayrollRun", run.id)
    db.commit()
    return payload


# ---------------------------------------------------------------- refunds (after a cancellation)
def _refund_out(db: Session, r: Refund) -> dict:
    w = db.get(WorkOrder, r.work_id)
    inv = db.get(Invoice, r.invoice_id) if r.invoice_id else None
    by = db.get(User, r.completed_by) if r.completed_by else None
    return {"id": r.id, "refund_number": r.refund_number, "work_id": r.work_id, "work_number": w.work_number if w else None,
            "invoice_id": r.invoice_id, "invoice_number": inv.invoice_number if inv else None, "client_name": r.client_name,
            "reason": r.reason, "received_amount": r.received_amount, "charge_percent": r.charge_percent, "charge_amount": r.charge_amount,
            "refund_amount": r.refund_amount, "status": r.status, "method": r.method, "transaction_id": r.transaction_id, "note": r.note,
            "refund_date": r.refund_date, "created_at": r.created_at, "completed_by_name": by.name if by else None,
            "completed_at": r.completed_at, "kind": "sales_invoice" if r.invoice_id else "work"}


@router.get("/refunds", response_model=list[RefundOut], dependencies=[Depends(require_permission("finance", "view"))])
def list_refunds(status: str | None = None, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    """Refunds owed to customers after a cancellation (pending first), with the ones already paid back."""
    from app.services import refunds as refunds_svc
    if refunds_svc.heal_pending(db, org_id):
        db.commit()
    q = db.query(Refund).filter(Refund.org_id == org_id)
    if status in ("pending", "completed"):
        q = q.filter(Refund.status == status)
    rows = q.order_by(Refund.status.desc(), Refund.created_at.desc()).all()      # "pending" sorts after "completed" descending, so flip below
    rows.sort(key=lambda r: (r.status != "pending", -(r.created_at.timestamp() if r.created_at else 0)))
    return [_refund_out(db, r) for r in rows]


@router.post("/refunds/{refund_id}/complete", response_model=RefundOut, dependencies=[Depends(require_permission("finance", "refund"))])
def complete_refund(refund_id: str, payload: RefundComplete, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    """Finance records the cancellation charge (%), how the rest was paid back and its transaction id, and completes the refund."""
    from app.services import refunds as refunds_svc
    r = db.query(Refund).filter(Refund.id == refund_id, Refund.org_id == org_id).with_for_update().first()
    if not r:
        raise HTTPException(status_code=404, detail="Refund not found")
    try:
        refunds_svc.complete(db, r, current_user, charge_percent=payload.charge_percent, method=payload.method,
                             transaction_id=payload.transaction_id, note=payload.note, refund_date=payload.refund_date)
    except refunds_svc.RefundError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    log_audit_event(db, org_id, current_user.id, "complete_refund", "Refund", r.id)
    notify_role(db, org_id, "Admin", f"Refund {r.refund_number} completed: {r.refund_amount} paid back to {r.client_name}"
                + (f", {r.charge_amount} kept as cancellation charge" if r.charge_amount else "") + ".")
    db.commit()
    db.refresh(r)
    return _refund_out(db, r)
