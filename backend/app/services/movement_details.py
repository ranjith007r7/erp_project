"""
Stock movement details for the Inventory > Stock Movements page.

A movement row only says "-10 work_order". Here each page of movements is enriched with what a manager asks next: for stock
that left for a work - the client and company, who handles it and (if the viewer may see money) the profit of the deal; for
stock that came in on a purchase order - who ordered it, from which vendor and against which job; for a direct sale - the
customer and invoice. Loaded in bulk per page (no per-row queries). Lives in services/ so Inventory does not import other
modules' routes.
"""
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.crm import Account
from app.models.hr import Department, Employee
from app.models.procurement import PurchaseOrder, Vendor
from app.models.sales import Customer, Invoice, SalesOrder
from app.models.stock import StockBatch
from app.models.user import User
from app.models.workpage import WorkOrder
from app.services import workpages as wp

TITLES = {"work_order": "Issued to a work", "work_cancelled": "Returned: work cancelled", "purchase_order": "Received on a purchase order",
          "sales_order": "Sold (direct sale)", "stock_intake": "Stock intake", "stock_intake_removed": "Stock intake undone"}


def _uuid(v):
    try:
        return v if isinstance(v, UUID) else UUID(str(v))
    except (ValueError, TypeError):
        return None


def describe(db: Session, org_id, movements, show_profit: bool) -> dict:
    """movement id -> {"title", "details": [{label, value}], "link"}"""
    ids = {}
    for m in movements:
        i = _uuid(m.ref_id)
        if i:
            ids.setdefault(m.ref_type, set()).add(i)
    work_ids = set(ids.get("work_order", ())) | set(ids.get("work_cancelled", ()))
    pos = {p.id: p for p in db.query(PurchaseOrder).filter(PurchaseOrder.org_id == org_id, PurchaseOrder.id.in_(ids.get("purchase_order", {None}))).all()} if ids.get("purchase_order") else {}
    work_ids |= {p.work_order_id for p in pos.values() if p.work_order_id}
    works = {w.id: w for w in db.query(WorkOrder).filter(WorkOrder.org_id == org_id, WorkOrder.id.in_(work_ids)).all()} if work_ids else {}
    users = {}
    user_ids = {p.created_by for p in pos.values() if p.created_by}
    batches = {b.id: b for b in db.query(StockBatch).filter(StockBatch.org_id == org_id, StockBatch.id.in_(set(ids.get("stock_intake", ())) | set(ids.get("stock_intake_removed", ())))).all()} \
        if (ids.get("stock_intake") or ids.get("stock_intake_removed")) else {}
    user_ids |= {b.created_by for b in batches.values() if b.created_by}
    if user_ids:
        users = {u.id: u.name for u in db.query(User).filter(User.id.in_(user_ids))}
    vendors = {v.id: v.name for v in db.query(Vendor).filter(Vendor.org_id == org_id, Vendor.id.in_({p.vendor_id for p in pos.values()}))} if pos else {}
    orders = {o.id: o for o in db.query(SalesOrder).filter(SalesOrder.org_id == org_id, SalesOrder.id.in_(ids.get("sales_order", {None}))).all()} if ids.get("sales_order") else {}
    custs = {c.id: c for c in db.query(Customer).filter(Customer.id.in_({o.customer_id for o in orders.values()}))} if orders else {}
    inv = {i.order_id: i for i in db.query(Invoice).filter(Invoice.org_id == org_id, Invoice.order_id.in_(list(orders)))} if orders else {}
    accounts = {a.id: a.name for a in db.query(Account).filter(Account.id.in_({c.account_id for c in custs.values() if c.account_id}))} if custs else {}
    for w in works.values():
        if w.customer_id and w.customer_id not in custs:
            c = db.get(Customer, w.customer_id)
            if c:
                custs[c.id] = c
                if c.account_id and c.account_id not in accounts:
                    a = db.get(Account, c.account_id)
                    accounts[c.account_id] = a.name if a else None
    emp_names = {e.id: e.name for e in db.query(Employee).filter(Employee.id.in_({w.allocated_employee_id for w in works.values() if w.allocated_employee_id}))} if works else {}
    depts = {d.id: d.name for d in db.query(Department).filter(Department.id.in_({w.handling_department_id for w in works.values() if w.handling_department_id}))} if works else {}

    def work_lines(w):
        cust = custs.get(w.customer_id) if w.customer_id else None
        company = (accounts.get(cust.account_id) if cust and cust.account_id else None) or w.domain
        lines = [("Work", w.work_number), ("Client", w.client_name)]
        if company and company != w.client_name:
            lines.append(("Company / domain", company))
        lines.append(("Handled by", " · ".join(x for x in (emp_names.get(w.allocated_employee_id), depts.get(w.handling_department_id)) if x) or "Not allocated yet"))
        lines.append(("Work status", wp.STATUSES[w.status]["label"]))
        if show_profit:
            lines.append(("Profit on this deal", f"₹{wp.profit(w):,.2f}"))
        return lines

    out = {}
    for m in movements:
        rid, rt = _uuid(m.ref_id), m.ref_type
        lines, link = [], None
        if rt in ("work_order", "work_cancelled") and rid in works:
            w = works[rid]
            lines, link = work_lines(w), f"/workpage/{w.id}"
        elif rt == "purchase_order" and rid in pos:
            p = pos[rid]
            lines = [("PO", p.po_number or "-"), ("Vendor", vendors.get(p.vendor_id, "-")), ("Ordered by", users.get(p.created_by, "-"))]
            w = works.get(p.work_order_id) if p.work_order_id else None
            lines.append(("Against job", f"{w.work_number} · {w.client_name}" if w else "Stock for future (no job)"))
            link = f"/workpage/{w.id}" if w else "/procurement"
        elif rt == "sales_order" and rid in orders:
            o = orders[rid]
            c = custs.get(o.customer_id)
            i = inv.get(o.id)
            lines = [("Customer", c.name if c else "-")]
            if c and c.account_id and accounts.get(c.account_id):
                lines.append(("Company", accounts[c.account_id]))
            lines += [("Invoice", i.invoice_number if i and i.invoice_number else "-"), ("Order total", f"₹{o.total:,.2f}")]
            link = "/sales"
        elif rt in ("stock_intake", "stock_intake_removed") and rid in batches:
            b = batches[rid]
            lines = [("Vendor", b.vendor_name), ("Entered by", users.get(b.created_by, "-")), ("Lot", f"{b.quantity_in} units, {b.source.replace('_', ' ')}")]
            link = "/stock-intake"
        out[m.id] = {"title": TITLES.get(rt or "", (rt or "Movement").replace("_", " ").capitalize()),
                     "details": [{"label": a, "value": str(b)} for a, b in lines], "link": link}
    return out
