"""
Workpage service layer - the ONE place that knows how a customer work moves
through its life, and the only thing other modules call.

    CRM lead converted -> Assigned -> Allocated (an employee has it)
        stock is in inventory : take it from inventory -> Delivered at once
        stock is short        : Stock short / PO not raised -> PO raised -> In transit -> PO received -> Delivered
                                (a defective receipt shows Waiting for new PO)
    Delivered -> fully paid -> Closed ("Work done"), automatically.

CRM calls on_lead_converted(); Sales calls on_quotation_accepted(); Procurement calls the
on_po_* hooks. All go through `safe()`, so a problem here can NEVER break a purchase order,
a quotation or a conversion - it only means the work's history misses a line.

Money rules (all derived, none stored):
    discount_amount = quotation_amount * discount_percent / 100
    net_payable     = quotation_amount - discount_amount
    profit          = net_payable - vendor_amount
A work can be closed only when delivered AND received >= net_payable.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.crm import Account
from app.models.hr import Department, Employee
from app.models.organization import Organization
from app.models.procurement import PurchaseOrder, ProcurementEmailLog
from app.models.sales import Customer, Quotation
from app.models.user import User
from app.models.sales import Product
from app.models.workpage import WorkOrder, WorkEvent, WorkPayment, WorkItem, WorkStockIssue
from app.services import pricing, stock as stock_svc
from app.services.accounting import post_work_receipt_journal_entry
from app.services.inventory import issue_stock

log = logging.getLogger("workpages")

STATUSES = {
    "assigned":       {"label": "Assigned",                  "color": "slate"},
    "allocated":      {"label": "Allocated",                 "color": "blue"},
    "po_not_raised":  {"label": "Stock short - PO not raised", "color": "orange"},
    "po_raised":      {"label": "PO raised",                 "color": "amber"},
    "in_transit":     {"label": "In transit",                "color": "violet"},
    "waiting_new_po": {"label": "Waiting for new PO",        "color": "red"},
    "po_received":    {"label": "PO received",               "color": "indigo"},
    "delivered":      {"label": "Delivered - payment pending", "color": "teal"},
    "closed":         {"label": "Work done",                 "color": "green"},
}
# Everything between "an employee has it" and "work done" that is still waiting on something.
PENDING_KEYS = ("po_not_raised", "po_raised", "in_transit", "waiting_new_po", "po_received", "delivered")
# While a work is in one of these, its status follows its purchase orders.
PO_PHASE = ("assigned", "allocated", "po_not_raised", "po_raised", "in_transit", "waiting_new_po", "po_received")
PAYMENT_METHODS = ("cash", "card", "gpay", "bank_transfer", "cheque")
METHODS_NEEDING_REFERENCE = ("card", "gpay", "bank_transfer", "cheque")
TWO = Decimal("0.01")


class WorkError(Exception):
    """A rule was broken; the route turns this into a 400."""


def q2(v) -> Decimal:
    return Decimal(v or 0).quantize(TWO, rounding=ROUND_HALF_UP)


# ------------------------------------------------------------------ money
def discount_amount(w: WorkOrder) -> Decimal:
    return q2(Decimal(w.quotation_amount or 0) * Decimal(w.discount_percent or 0) / 100)


def net_payable(w: WorkOrder) -> Decimal:
    return q2(Decimal(w.quotation_amount or 0) - discount_amount(w))


def profit(w: WorkOrder) -> Decimal:
    return q2(net_payable(w) - Decimal(w.vendor_amount or 0))


def received_amount(w: WorkOrder) -> Decimal:
    return q2(sum((Decimal(p.amount) for p in w.payments), Decimal(0)))


def pending_amount(w: WorkOrder) -> Decimal:
    return max(q2(net_payable(w) - received_amount(w)), Decimal("0.00"))


# --------------------------------------------------------------- plumbing
def safe(db: Session, fn, *args, **kwargs):
    """Run a sync hook inside a savepoint; swallow and log any failure."""
    try:
        with db.begin_nested():
            return fn(db, *args, **kwargs)
    except Exception:  # noqa: BLE001 - by design: never break the calling module
        log.exception("workpage hook %s failed", getattr(fn, "__name__", fn))
        return None


def next_work_number(db: Session, org_id) -> str:
    db.flush()
    db.query(Organization).filter(Organization.id == org_id).with_for_update().first()
    n = db.query(func.count(WorkOrder.id)).filter(WorkOrder.org_id == org_id).scalar() or 0
    while True:
        n += 1
        number = f"WK-{n:04d}"
        if not db.query(WorkOrder.id).filter(WorkOrder.org_id == org_id, WorkOrder.work_number == number).first():
            return number


def log_event(db: Session, work: WorkOrder, kind: str, title: str, detail: str | None = None,
              user: User | None = None, meta: dict | None = None) -> WorkEvent:
    ev = WorkEvent(org_id=work.org_id, work_id=work.id, kind=kind, title=title, detail=detail,
                   actor_user_id=user.id if user else None, actor_name=user.name if user else "System",
                   meta=meta or None, created_at=datetime.utcnow())
    db.add(ev)
    work.updated_at = datetime.utcnow()
    return ev


def _set_status(db: Session, work: WorkOrder, new: str):
    work.status = new
    work.updated_at = datetime.utcnow()


def _user_department(db: Session, user: User | None):
    if not user:
        return None
    emp = db.query(Employee).filter(Employee.org_id == user.org_id, Employee.user_id == user.id).first()
    return emp.department_id if emp else None


def _get_work(db: Session, org_id, work_id) -> WorkOrder | None:
    if not work_id:
        return None
    return db.query(WorkOrder).filter(WorkOrder.id == work_id, WorkOrder.org_id == org_id).first()


def check_linkable(db: Session, org_id, work_id):
    """Procurement asks: may a PO be raised for this work? Returns the id (or None)."""
    if not work_id:
        return None
    work = _get_work(db, org_id, work_id)
    if not work:
        raise WorkError("Work not found.")
    if work.status in ("delivered", "closed"):
        raise WorkError(f"{work.work_number} is already {STATUSES[work.status]['label'].lower()}; a purchase order cannot be raised for it.")
    if _issues(db, work):
        raise WorkError(f"{work.work_number} was served from inventory; no purchase order is needed.")
    return work.id


# ------------------------------------------------------------------ items & stock helpers
def _items(db: Session, work: WorkOrder) -> list[WorkItem]:
    return db.query(WorkItem).filter(WorkItem.work_id == work.id).order_by(WorkItem.created_at, WorkItem.id).all()


def _issues(db: Session, work: WorkOrder) -> list[WorkStockIssue]:
    return db.query(WorkStockIssue).filter(WorkStockIssue.work_id == work.id).order_by(WorkStockIssue.created_at, WorkStockIssue.id).all()


def issued_lines(db: Session, work: WorkOrder):
    return [(i.qty, i.mrp, i.max_discount_percent) for i in _issues(db, work)]


def pricing_violations(db: Session, work: WorkOrder, quotation_amount=None, discount_percent=None) -> list[str]:
    """The MRP / max-discount rule for stock this work took from inventory (see app/services/pricing.py)."""
    return pricing.violations(work.quotation_amount if quotation_amount is None else quotation_amount,
                              work.discount_percent if discount_percent is None else discount_percent,
                              issued_lines(db, work))


def set_items(db: Session, work: WorkOrder, user: User, items: list[tuple]) -> list[WorkItem]:
    """Replace the list of what the customer needs (product, qty). Allowed until stock has been taken."""
    if work.status in ("delivered", "closed"):
        raise WorkError(f"This work is already {STATUSES[work.status]['label'].lower()}.")
    if _issues(db, work):
        raise WorkError("Stock has already been taken for this work; its items can no longer change.")
    merged: dict = {}
    for product_id, qty in items:
        if int(qty) <= 0:
            raise WorkError("Each quantity must be at least 1.")
        prod = db.query(Product).filter(Product.id == product_id, Product.org_id == work.org_id).first()
        if not prod:
            raise WorkError("Product not found.")
        merged[prod.id] = merged.get(prod.id, 0) + int(qty)
    db.query(WorkItem).filter(WorkItem.work_id == work.id).delete()
    rows = []
    for pid, qty in merged.items():
        r = WorkItem(org_id=work.org_id, work_id=work.id, product_id=pid, qty=qty)
        db.add(r)
        rows.append(r)
    db.flush()
    names = {p.id: p.name for p in db.query(Product).filter(Product.id.in_(list(merged)))} if merged else {}
    log_event(db, work, "items_set", "Required items listed",
              "; ".join(f"{names.get(pid, 'Product')} x {q}" for pid, q in merged.items()) or "No items.", user)
    return rows


def stock_check(db: Session, work: WorkOrder, show_cost: bool = False) -> dict:
    """What the work needs against what inventory can serve right now (first-expiry-first-out, expired lots ignored)."""
    out_items, all_ok, picks_all = [], True, []
    for it in _items(db, work):
        prod = db.get(Product, it.product_id)
        picks, short = stock_svc.plan_issue(db, work.org_id, it.product_id, it.qty)
        avail = stock_svc.available_qty(db, work.org_id, it.product_id)
        total = stock_svc.stock_total(db, work.org_id, it.product_id)
        ok = short == 0
        all_ok = all_ok and ok
        picks_all += [(b, t) for b, t in picks]
        row = {"product_id": it.product_id, "product_name": prod.name if prod else "Product", "sku": prod.sku if prod else None,
               "required": it.qty, "available": avail, "on_hand": total, "short_by": short, "ok": ok,
               "unpriced": stock_svc.unpriced(db, work.org_id, it.product_id),
               "batches": [{"batch_id": b.id, "take": t, "mrp": q2(b.mrp), "max_discount_percent": q2(b.max_discount_percent),
                            "expiry_date": b.expiry_date, "inward_date": b.inward_date,
                            **({"vendor_name": b.vendor_name, "vendor_amount": q2(b.vendor_amount)} if show_cost else {})}
                           for b, t in picks]}
        out_items.append(row)
    has_items = bool(out_items)
    lines = [(t, b.mrp, b.max_discount_percent) for b, t in picks_all]
    viol = pricing.violations(work.quotation_amount, work.discount_percent, lines) if (has_items and all_ok) else []
    lim = pricing.limits(lines) if lines else None
    return {"items": out_items, "has_items": has_items, "all_available": has_items and all_ok,
            "pricing": {"limits": lim, "violations": viol, "ok": not viol},
            "can_issue": has_items and all_ok and not viol and work.status in ("allocated", "po_not_raised") and not _issues(db, work),
            "already_issued": bool(_issues(db, work))}


def mark_stock_short(db: Session, work: WorkOrder, user: User, note: str | None = None) -> WorkOrder:
    """The employee checked inventory and it cannot serve the work: it waits for a purchase, with the reason on record."""
    if work.status not in ("allocated", "po_not_raised"):
        raise WorkError("Only an allocated work can be marked as waiting for stock.")
    chk = stock_check(db, work)
    if not chk["has_items"]:
        raise WorkError("List the items the customer needs first, then check inventory.")
    short = [i for i in chk["items"] if not i["ok"]]
    if not short:
        raise WorkError("Everything needed is in stock. Use 'Take from inventory' instead of raising a purchase order.")
    reason = "; ".join(f"{i['product_name']}: need {i['required']}, only {i['available']} in stock" for i in short)
    if (note or "").strip():
        reason += f". {note.strip()}"
    work.pending_note = reason
    _set_status(db, work, "po_not_raised")
    log_event(db, work, "stock_short", "Stock short - purchase needed", f"{reason}. The purchase order has not been raised yet.", user)
    return work


def issue_stock_for_work(db: Session, work: WorkOrder, user: User) -> WorkOrder:
    """Take the needed stock out of inventory: rates come from the batch, never typed. The work is delivered at once."""
    if work.status not in ("allocated", "po_not_raised"):
        raise WorkError("Allocate the work to an employee before taking stock from inventory." if work.status == "assigned"
                        else f"A work in status '{STATUSES[work.status]['label']}' cannot take stock from inventory.")
    if _issues(db, work):
        raise WorkError("Stock has already been taken for this work.")
    items = _items(db, work)
    if not items:
        raise WorkError("List the items the customer needs first.")
    plan, lines = [], []
    for it in items:
        prod = db.get(Product, it.product_id)
        picks, short = stock_svc.plan_issue(db, work.org_id, it.product_id, it.qty)
        if short:
            have = it.qty - short
            raise WorkError(f"Not enough stock for {prod.name if prod else 'a product'}: {have} available, {it.qty} needed.")
        plan.append((it, prod, picks))
        lines += [(t, b.mrp, b.max_discount_percent) for b, t in picks]
    viol = pricing.violations(work.quotation_amount, work.discount_percent, lines)
    if viol:
        raise WorkError(" ".join(viol) + " Ask a manager to correct the quotation amount or the discount first.")
    cost_total, detail = Decimal(0), []
    for it, prod, picks in plan:
        for b, t in picks:
            b.quantity_remaining -= t
            b.updated_at = datetime.utcnow()
            db.add(WorkStockIssue(org_id=work.org_id, work_id=work.id, batch_id=b.id, product_id=it.product_id, qty=t,
                                  cost_rate=q2(b.vendor_amount), mrp=q2(b.mrp), max_discount_percent=q2(b.max_discount_percent),
                                  issued_by=user.id))
            cost_total += Decimal(b.vendor_amount) * t
            detail.append(f"{prod.name} x {t} (bought at {q2(b.vendor_amount)}, MRP {q2(b.mrp)}, from {b.vendor_name})")
        try:
            issue_stock(db, work.org_id, str(it.product_id), prod.name, it.qty, ref_type="work_order", ref_id=str(work.id))
        except ValueError as e:
            raise WorkError(str(e))
    work.vendor_amount = q2(cost_total)
    work.pending_note = None
    work.delivered_on = date.today()
    work.delivery_note = "Served from existing inventory"
    _set_status(db, work, "delivered")
    log_event(db, work, "stock_issued", "Stock taken from inventory", "; ".join(detail) + f". Cost to us {q2(cost_total)}.", user,
              {"cost": str(q2(cost_total))})
    log_event(db, work, "delivered", "Delivered from inventory (no purchase needed)",
              f"Delivered on {work.delivered_on}. Waiting for the customer's payment ({pending_amount(work)}).", user)
    maybe_auto_close(db, work, user)
    return work


def maybe_auto_close(db: Session, work: WorkOrder, user: User | None):
    """Delivered and fully paid = work done. Nobody has to remember to close it."""
    if work.status == "delivered" and net_payable(work) > 0 and pending_amount(work) == 0:
        work.closed_at = datetime.utcnow()
        _set_status(db, work, "closed")
        log_event(db, work, "closed", "Work done", f"Delivered and fully paid ({received_amount(work)}); closed automatically.", user)
        return True
    return False


# ----------------------------------------------------------- manual actions
def create_work(db: Session, org_id, user: User | None, *, client_name: str, domain=None, client_details=None,
                description=None, quotation_amount=0, vendor_amount=0, discount_percent=0,
                customer_id=None, quotation_id=None, sales_order_id=None, department_id=None,
                opened_title="Work received", lead_id=None, opportunity_id=None, client_mobile=None,
                assign_department=True) -> WorkOrder:
    if department_id is None and assign_department:
        department_id = _user_department(db, user)
    work = WorkOrder(org_id=org_id, work_number=next_work_number(db, org_id), client_name=client_name.strip(),
                     domain=(domain or "").strip() or None, client_details=client_details, description=description,
                     quotation_amount=q2(quotation_amount), vendor_amount=q2(vendor_amount),
                     discount_percent=q2(discount_percent), customer_id=customer_id, quotation_id=quotation_id,
                     sales_order_id=sales_order_id, handling_department_id=department_id,
                     lead_id=lead_id, opportunity_id=opportunity_id, client_mobile=(client_mobile or "").strip() or None,
                     created_by=user.id if user else None, status="assigned")
    db.add(work)
    db.flush()
    dept = db.get(Department, department_id) if department_id else None
    log_event(db, work, "created", opened_title,
              f"Estimated quotation amount {q2(quotation_amount)}." + (f" Assigned to {dept.name}." if dept else " Waiting for a manager to allocate it to a department and an employee."),
              user)
    return work


def allocate(db: Session, work: WorkOrder, user: User, department_id, employee_id=None) -> WorkOrder:
    if work.status in ("delivered", "closed"):
        raise WorkError(f"This work is already {STATUSES[work.status]['label'].lower()}.")
    dept = db.query(Department).filter(Department.id == department_id, Department.org_id == work.org_id).first()
    if not dept:
        raise WorkError("Department not found.")
    emp = None
    if employee_id:
        emp = db.query(Employee).filter(Employee.id == employee_id, Employee.org_id == work.org_id,
                                        Employee.status == "active").first()
        if not emp:
            raise WorkError("Employee not found.")
        if emp.department_id != dept.id:
            raise WorkError(f"{emp.name} does not belong to the {dept.name} department.")
    work.handling_department_id = dept.id
    work.allocated_employee_id = emp.id if emp else None
    if emp and work.status == "assigned":
        _set_status(db, work, "allocated")
    log_event(db, work, "allocated", f"Allocated to {dept.name}",
              (f"Employee {emp.name} ({emp.employee_code or 'no code'}) is working on it." if emp
               else "No individual employee picked yet."), user,
              {"department": dept.name, "employee": emp.name if emp else None, "employee_code": emp.employee_code if emp else None})
    return work


def deliver(db: Session, work: WorkOrder, user: User, delivered_on: date | None, note: str | None, from_stock: bool = False):
    """Delivery of goods that arrived through a purchase order. Stock already in inventory is served by issue_stock_for_work."""
    if work.status == "closed":
        raise WorkError("This work is closed.")
    if work.status == "delivered":
        raise WorkError("This work is already delivered.")
    if from_stock:
        raise WorkError("To serve a work from existing stock, list its items and use 'Take from inventory'; that moves the stock and the status by itself.")
    if work.status != "po_received":
        if work.status in ("assigned", "allocated"):
            raise WorkError("Nothing to deliver yet: check inventory and take the stock, or raise a purchase order and receive the goods.")
        raise WorkError(f"A work in status '{STATUSES[work.status]['label']}' cannot be delivered yet.")
    work.delivered_on = delivered_on or date.today()
    work.delivery_note = (note or "").strip() or None
    work.pending_note = None
    _set_status(db, work, "delivered")
    log_event(db, work, "delivered", "Delivered to customer",
              f"Delivered on {work.delivered_on}." + (f" {work.delivery_note}" if work.delivery_note else ""), user)
    maybe_auto_close(db, work, user)
    return work


def record_payment(db: Session, work: WorkOrder, user: User, amount, method: str, transaction_id=None,
                   note=None, paid_on: date | None = None) -> WorkPayment:
    if work.status == "closed":
        raise WorkError("This work is closed; no more payments can be recorded.")
    amount = q2(amount)
    if amount <= 0:
        raise WorkError("The amount must be more than zero.")
    if method not in PAYMENT_METHODS:
        raise WorkError("Pick a payment method: cash, card, GPay, bank transfer or cheque.")
    viol = pricing_violations(db, work)
    if viol:
        raise WorkError("Finance check: this bill breaks the MRP / maximum-discount rule, so no payment can be booked against it. " + " ".join(viol))
    pending = pending_amount(work)
    if amount > pending:
        raise WorkError(f"This payment ({amount}) is more than the amount still pending ({pending}).")
    txn = (transaction_id or "").strip() or None
    if method in METHODS_NEEDING_REFERENCE:
        if not txn:
            raise WorkError("Enter the transaction / reference number for this payment.")
        dup = db.query(WorkPayment.id).filter(WorkPayment.org_id == work.org_id, WorkPayment.transaction_id == txn).first()
        if dup:
            raise WorkError(f"Reference {txn} is already recorded against another payment.")
    else:
        txn = None
    pay = WorkPayment(org_id=work.org_id, work_id=work.id, amount=amount, method=method, transaction_id=txn,
                      note=(note or "").strip() or None, paid_on=paid_on or date.today(), recorded_by=user.id)
    db.add(pay)
    db.flush()
    db.expire(work, ["payments"])
    label = {"cash": "Cash", "card": "Card", "gpay": "GPay", "bank_transfer": "Bank transfer", "cheque": "Cheque"}[method]
    post_work_receipt_journal_entry(db, work.org_id, str(pay.id), amount, note=f"{work.work_number}, {label}" + (f", {txn}" if txn else ""))
    left = pending_amount(work)
    log_event(db, work, "payment", f"Payment received: {amount}",
              f"By {label}" + (f" (ref {txn})" if txn else "") + f". Received so far {received_amount(work)}; "
              + ("fully paid." if left == 0 else f"{left} still pending."), user,
              {"amount": str(amount), "method": method, "transaction_id": txn, "pending": str(left)})
    maybe_auto_close(db, work, user)
    return pay


def close(db: Session, work: WorkOrder, user: User) -> WorkOrder:
    if work.status == "closed":
        raise WorkError("This work is already closed.")
    if work.status != "delivered":
        raise WorkError("Only a delivered work can be closed.")
    left = pending_amount(work)
    if left > 0:
        raise WorkError(f"The full payment has not been received. {left} is still pending.")
    work.closed_at = datetime.utcnow()
    _set_status(db, work, "closed")
    log_event(db, work, "closed", "Work done", f"Fully paid ({received_amount(work)}). Closed by {user.name}.", user)
    return work


# ------------------------------------------------------- cross-module hooks
def on_lead_converted(db: Session, lead, opportunity, user: User | None = None):
    """CRM: a quotation that came in was converted. Opens the work as Assigned (once per lead)."""
    if db.query(WorkOrder.id).filter(WorkOrder.org_id == lead.org_id, WorkOrder.lead_id == lead.id).first():
        return None
    parts = [f"Contact: {lead.name}"]
    if lead.phone:
        parts.append(f"Mobile: {lead.phone}")
    if lead.email:
        parts.append(f"Email: {lead.email}")
    amount = (opportunity.value if opportunity and opportunity.value else None) or lead.estimated_amount or 0
    return create_work(db, lead.org_id, user, client_name=lead.company_name or lead.name, domain=lead.industry,
                       client_details="\n".join(parts), description=opportunity.name if opportunity else None,
                       quotation_amount=amount, lead_id=lead.id, opportunity_id=opportunity.id if opportunity else None,
                       client_mobile=lead.phone, assign_department=False,
                       opened_title="Quotation converted - waiting to be allocated")


def on_quotation_accepted(db: Session, quotation: Quotation, order, user: User | None = None):
    """Sales: the customer said yes. Opens a work (once per quotation) - or, if the quotation grew out of a
    CRM opportunity that already has its work, attaches the quotation and order to that work instead."""
    if db.query(WorkOrder.id).filter(WorkOrder.org_id == quotation.org_id, WorkOrder.quotation_id == quotation.id).first():
        return None
    if quotation.opportunity_id:
        existing = (db.query(WorkOrder).filter(WorkOrder.org_id == quotation.org_id, WorkOrder.opportunity_id == quotation.opportunity_id,
                                               WorkOrder.quotation_id.is_(None)).first())
        if existing:
            existing.quotation_id = quotation.id
            existing.sales_order_id = order.id if order else None
            existing.customer_id = existing.customer_id or quotation.customer_id
            log_event(db, existing, "quotation_linked", "Sales quotation accepted and linked",
                      f"Quotation total {q2(quotation.total)}; the work's amount was left as agreed.", user)
            return existing
    customer = db.get(Customer, quotation.customer_id)
    industry = None
    if customer and customer.account_id:
        acc = db.get(Account, customer.account_id)
        industry = acc.industry if acc else None
    work = create_work(db, quotation.org_id, user, client_name=customer.name if customer else "Customer",
                       domain=industry, client_details=(customer.billing_address if customer else None),
                       quotation_amount=quotation.total or 0, customer_id=quotation.customer_id,
                       quotation_id=quotation.id, sales_order_id=order.id if order else None,
                       opened_title="Deal accepted - waiting to be allocated")
    return work


def _active_pos(db: Session, work: WorkOrder) -> list[PurchaseOrder]:
    pos = (db.query(PurchaseOrder).filter(PurchaseOrder.org_id == work.org_id, PurchaseOrder.work_order_id == work.id)
           .order_by(PurchaseOrder.created_at).all())
    live = [p for p in pos if p.approval_status != "rejected" and p.status != "cancelled"]
    out = []
    for i, p in enumerate(live):
        superseded = p.status == "defective" and any(o.created_at and p.created_at and o.created_at > p.created_at for o in live[i + 1:])
        if not superseded:
            out.append(p)
    return out


def recompute_from_pos(db: Session, work: WorkOrder):
    """While a work is in its purchase phase, its status is a pure function of its live purchase orders.
    Deriving it (instead of nudging it step by step) is what keeps Workpage and Home exactly in step."""
    if work.status not in PO_PHASE:
        return
    active = _active_pos(db, work)
    if not active:
        if work.status in ("po_raised", "in_transit", "waiting_new_po", "po_received"):
            new = "po_not_raised" if work.pending_note else ("allocated" if work.allocated_employee_id else "assigned")
        else:
            return
    elif any(p.status == "defective" for p in active):
        new = "waiting_new_po"
    elif all(p.status == "received" for p in active):
        new = "po_received"
    elif any(p.approval_status == "pending" for p in active):
        new = "po_raised"
    else:
        new = "in_transit"
    if new != work.status:
        _set_status(db, work, new)


def on_po_created(db: Session, po: PurchaseOrder, user: User | None):
    work = _get_work(db, po.org_id, po.work_order_id)
    if not work:
        return
    first = db.query(PurchaseOrder.id).filter(PurchaseOrder.work_order_id == work.id, PurchaseOrder.id != po.id).first() is None
    if first and not Decimal(work.vendor_amount or 0):
        work.vendor_amount = q2(po.total)
    log_event(db, work, "po_raised", f"{po.po_number} raised",
              f"Raised by {user.name if user else 'a buyer'} for {q2(po.total)}; waiting for approval.", user,
              {"po_id": str(po.id), "po_number": po.po_number})
    recompute_from_pos(db, work)


def on_po_decision(db: Session, po: PurchaseOrder, user: User | None, approved: bool):
    work = _get_work(db, po.org_id, po.work_order_id)
    if not work:
        return
    if approved:
        log_event(db, work, "po_approved", f"{po.po_number} approved", f"Approved by {user.name if user else 'an approver'}; the order is with the vendor.", user)
    else:
        log_event(db, work, "po_rejected", f"{po.po_number} rejected", f"Rejected by {user.name if user else 'an approver'}.", user)
    recompute_from_pos(db, work)


def on_po_received(db: Session, po: PurchaseOrder, user: User | None):
    work = _get_work(db, po.org_id, po.work_order_id)
    if not work:
        return
    log_event(db, work, "po_received", f"{po.po_number} received in good condition",
              f"Goods checked and added to stock by {user.name if user else 'the warehouse'}.", user, {"po_number": po.po_number})
    recompute_from_pos(db, work)


def on_po_defective(db: Session, po: PurchaseOrder, user: User | None, notes: str | None = None):
    work = _get_work(db, po.org_id, po.work_order_id)
    if not work:
        return
    log_event(db, work, "po_defective", f"{po.po_number} arrived defective",
              (notes or "Goods were damaged on arrival and were not added to stock.") + " Waiting for a replacement purchase order.",
              user, {"po_number": po.po_number})
    recompute_from_pos(db, work)


def on_procurement_notice(db: Session, po: PurchaseOrder, kind: str, channel: str, status: str,
                          to_email: str | None, user: User | None):
    """PO sent to the vendor, or a defect notice sent / printed (the send-back log)."""
    work = _get_work(db, po.org_id, po.work_order_id)
    if not work:
        return
    what = "Purchase order" if kind == "po" else "Defect notice (send-back)"
    how = {"email": f"emailed to {to_email}" if to_email else "emailed", "print": "printed for hand delivery"}.get(channel, channel)
    log_event(db, work, "po_sent" if kind == "po" else "send_back", f"{what} {how}",
              f"{po.po_number}. Delivery status: {status}.", user, {"po_number": po.po_number, "channel": channel})


def reconciliation_report(db: Session, org_id) -> list[dict]:
    """Finance view: for every work, what was quoted (net payable) against what was received on the work
    and what Finance has actually booked (journal entries WPMT-<payment id>, credited to Sales Revenue).
    A work is only 'matched' when quoted = received = booked and it is closed as Work done."""
    from app.models.finance import JournalEntry, JournalLine, ChartOfAccounts as Account
    works = db.query(WorkOrder).filter(WorkOrder.org_id == org_id).order_by(WorkOrder.created_at.desc()).all()
    refs = {}
    for w in works:
        for p in w.payments:
            refs[f"WPMT-{p.id}"] = w.id
    booked: dict = {}
    if refs:
        rows = (db.query(JournalEntry.reference, func.coalesce(func.sum(JournalLine.credit), 0))
                .join(JournalLine, JournalLine.journal_entry_id == JournalEntry.id)
                .join(Account, Account.id == JournalLine.account_id)
                .filter(JournalEntry.org_id == org_id, JournalEntry.reference.in_(list(refs)), Account.code == "4000")
                .group_by(JournalEntry.reference).all())
        for ref, amt in rows:
            booked[refs[ref]] = booked.get(refs[ref], Decimal(0)) + Decimal(amt)
    out = []
    for w in works:
        quoted, got, books = net_payable(w), received_amount(w), q2(booked.get(w.id, Decimal(0)))
        if w.status == "closed" and quoted == got == books:
            state, note = "matched", "Quoted = received = booked in Finance. Work done."
        elif got != books:
            state, note = "mismatch", f"Received {got} on the work but Finance has booked {books}."
        elif w.status == "closed":
            state, note = "mismatch", f"Closed, but quoted {quoted} differs from received {got}."
        elif got == 0:
            state, note = "awaiting_payment" if w.status == "delivered" else "not_started", ("Delivered; no payment yet." if w.status == "delivered" else "Not yet delivered; no payment yet.")
        elif got < quoted:
            state, note = "part_paid", f"{q2(quoted - got)} still to receive before the work can close."
        elif got == quoted:
            state, note = "paid_awaiting_delivery", "Paid in full in advance; it becomes Work done when delivered."
        else:
            state, note = "mismatch", f"Received {got} is above the quoted {quoted}."
        out.append({"work_id": w.id, "work_number": w.work_number, "client_name": w.client_name, "status_label": STATUSES[w.status]["label"],
                    "quoted_net": quoted, "received": got, "booked_in_finance": books, "difference": q2(quoted - got), "state": state, "note": note})
    return out


def pricing_report(db: Session, org_id) -> list[dict]:
    """Finance view: every work that took stock from inventory, with the billed price against the MRP rules."""
    ids = [r[0] for r in db.query(WorkStockIssue.work_id).filter(WorkStockIssue.org_id == org_id).distinct()]
    rows = []
    for w in db.query(WorkOrder).filter(WorkOrder.org_id == org_id, WorkOrder.id.in_(ids)).order_by(WorkOrder.created_at.desc()).all() if ids else []:
        lim = pricing.limits(issued_lines(db, w))
        viol = pricing_violations(db, w)
        mrp_total = lim["ceiling"] if lim else Decimal(0)
        eff = q2(Decimal(100) * (mrp_total - net_payable(w)) / mrp_total) if mrp_total else Decimal(0)
        rows.append({"work_id": w.id, "work_number": w.work_number, "client_name": w.client_name, "status_label": STATUSES[w.status]["label"],
                     "quotation_amount": q2(w.quotation_amount), "discount_percent": q2(w.discount_percent), "net_payable": net_payable(w),
                     "mrp_total": mrp_total, "lowest_allowed": lim["floor"] if lim else Decimal(0),
                     "effective_discount_percent": eff, "max_discount_percent": lim["max_discount_percent"] if lim else Decimal(0),
                     "ok": not viol, "violations": viol})
    return rows


# ------------------------------------------------------------ presentation
def _name(u) -> str | None:
    return u.name if u else None


def pending_reason(db: Session, w: WorkOrder) -> str:
    """Why the work is where it is and what it is waiting for. Derived live, never stored (except the stock-short note)."""
    st = w.status
    if st == "closed":
        return "Work done: delivered and fully paid."
    if st == "assigned":
        return "Waiting for a manager to allocate it to a department and an employee."
    if st == "allocated":
        emp = w.allocated_employee.name if w.allocated_employee else "the team"
        if _issues(db, w):
            return f"{emp} has taken stock from inventory."
        return f"With {emp}: needs the stock check against inventory." if not _items(db, w) else f"With {emp}: items listed, inventory check pending."
    if st == "po_not_raised":
        return (w.pending_note or "Stock is not available in inventory.") + " Purchase order not raised yet."
    pos = _active_pos(db, w)
    nums = ", ".join(p.po_number or "PO" for p in pos) or "the purchase order"
    if st == "po_raised":
        return f"{nums} raised; waiting for approval."
    if st == "in_transit":
        vendors = ", ".join(sorted({p.vendor.name for p in pos if p.vendor}))
        return f"{nums} approved and placed with {vendors or 'the vendor'}; goods are on the way."
    if st == "waiting_new_po":
        return f"{nums} arrived defective; a replacement purchase order is needed."
    if st == "po_received":
        return "Goods received in good condition; waiting for delivery to the customer."
    if st == "delivered":
        left = pending_amount(w)
        return f"Delivered. Waiting for the customer's payment: {left} pending." if left > 0 else "Delivered and fully paid."
    return STATUSES[st]["label"]


def summary_row(db: Session, w: WorkOrder) -> dict:
    dept = db.get(Department, w.handling_department_id) if w.handling_department_id else None
    return {
        "id": w.id, "work_number": w.work_number, "client_name": w.client_name, "domain": w.domain,
        "client_mobile": w.client_mobile, "lead_id": w.lead_id,
        "status": w.status, "status_label": STATUSES[w.status]["label"], "status_color": STATUSES[w.status]["color"],
        "is_pending": w.status in PENDING_KEYS, "pending_reason": pending_reason(db, w),
        "quotation_amount": q2(w.quotation_amount), "vendor_amount": q2(w.vendor_amount),
        "discount_percent": q2(w.discount_percent), "discount_amount": discount_amount(w),
        "net_payable": net_payable(w), "profit": profit(w),
        "received_amount": received_amount(w), "pending_amount": pending_amount(w),
        "handling_department": dept.name if dept else None, "handling_department_id": w.handling_department_id,
        "allocated_employee_name": w.allocated_employee.name if w.allocated_employee else None,
        "created_at": w.created_at, "delivered_on": w.delivered_on, "closed_at": w.closed_at,
    }


def detail(db: Session, w: WorkOrder) -> dict:
    d = summary_row(db, w)
    emp = w.allocated_employee
    pos = (db.query(PurchaseOrder).filter(PurchaseOrder.org_id == w.org_id, PurchaseOrder.work_order_id == w.id)
           .order_by(PurchaseOrder.created_at).all())
    logs = {}
    if pos:
        for lg in db.query(ProcurementEmailLog).filter(ProcurementEmailLog.po_id.in_([p.id for p in pos])).order_by(ProcurementEmailLog.created_at):
            logs.setdefault(lg.po_id, []).append(lg)
    quotation = db.get(Quotation, w.quotation_id) if w.quotation_id else None
    d.update({
        "client_details": w.client_details, "description": w.description,
        "delivered_on": w.delivered_on, "delivery_note": w.delivery_note, "closed_at": w.closed_at,
        "quotation": ({"id": quotation.id, "total": quotation.total, "status": quotation.status,
                       "created_at": quotation.created_at} if quotation else None),
        "allocated_employee": ({"id": emp.id, "name": emp.name, "employee_code": emp.employee_code} if emp else None),
        "can_close": w.status == "delivered" and pending_amount(w) == 0,
        "items": [{"id": i.id, "product_id": i.product_id, "qty": i.qty,
                   "product_name": (db.get(Product, i.product_id).name if db.get(Product, i.product_id) else None)} for i in _items(db, w)],
        "stock_issues": [{"id": i.id, "product_id": i.product_id, "qty": i.qty, "cost_rate": i.cost_rate, "mrp": i.mrp,
                          "max_discount_percent": i.max_discount_percent,
                          "product_name": (db.get(Product, i.product_id).name if db.get(Product, i.product_id) else None),
                          "batch_vendor": (db.get(stock_svc.StockBatch, i.batch_id).vendor_name if db.get(stock_svc.StockBatch, i.batch_id) else None)}
                         for i in _issues(db, w)],
        "pricing": {"limits": pricing.limits(issued_lines(db, w)), "violations": pricing_violations(db, w)},
        "pending_note": w.pending_note,
        "purchase_orders": [{
            "id": p.id, "po_number": p.po_number, "vendor_name": p.vendor.name if p.vendor else None,
            "total": p.total, "approval_status": p.approval_status, "status": p.status,
            "ordered_on": p.order_date, "created_at": p.created_at,
            "assigned_to": _name(p.creator), "approved_by": _name(p.approver), "approved_at": p.approved_at,
            "receipts": [{"condition": r.condition, "received_date": r.received_date, "notes": r.notes,
                          "received_by": _name(r.receiver)} for r in p.receipts],
            "notices": [{"kind": lg.kind, "channel": lg.channel, "to_email": lg.to_email, "status": lg.status,
                         "created_at": lg.created_at} for lg in logs.get(p.id, [])],
        } for p in pos],
        "payments": [{"id": p.id, "amount": p.amount, "method": p.method, "transaction_id": p.transaction_id,
                      "note": p.note, "paid_on": p.paid_on, "recorded_by": db.get(User, p.recorded_by).name if p.recorded_by and db.get(User, p.recorded_by) else None}
                     for p in w.payments],
        "events": [{"id": e.id, "kind": e.kind, "title": e.title, "detail": e.detail, "actor_name": e.actor_name,
                    "created_at": e.created_at} for e in w.events],
    })
    return d
