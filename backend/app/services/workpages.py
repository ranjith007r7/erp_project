"""
Workpage service layer - the ONE place that knows how a customer work moves
through its life, and the only thing other modules call.

    Assigned -> Allocated -> PO raised -> PO received -> Delivered -> Closed
                                   \\-> Waiting for new PO (a received PO was defective)

Sales calls on_quotation_accepted(); Procurement calls the on_po_* hooks. Both
go through `safe()`, so a problem here can NEVER break a purchase order or a
quotation - it only means the work's history misses a line.

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
from app.models.workpage import WorkOrder, WorkEvent, WorkPayment
from app.services.accounting import post_work_receipt_journal_entry

log = logging.getLogger("workpages")

STATUSES = {
    "assigned":       {"label": "Assigned",            "color": "slate"},
    "allocated":      {"label": "Allocated",           "color": "blue"},
    "po_raised":      {"label": "PO raised",           "color": "amber"},
    "waiting_new_po": {"label": "Waiting for new PO",  "color": "red"},
    "po_received":    {"label": "PO received",         "color": "indigo"},
    "delivered":      {"label": "Delivered",           "color": "teal"},
    "closed":         {"label": "Closed",              "color": "green"},
}
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
    return work.id


# ----------------------------------------------------------- manual actions
def create_work(db: Session, org_id, user: User | None, *, client_name: str, domain=None, client_details=None,
                description=None, quotation_amount=0, vendor_amount=0, discount_percent=0,
                customer_id=None, quotation_id=None, sales_order_id=None, department_id=None,
                opened_title="Work received") -> WorkOrder:
    if department_id is None:
        department_id = _user_department(db, user)
    work = WorkOrder(org_id=org_id, work_number=next_work_number(db, org_id), client_name=client_name.strip(),
                     domain=(domain or "").strip() or None, client_details=client_details, description=description,
                     quotation_amount=q2(quotation_amount), vendor_amount=q2(vendor_amount),
                     discount_percent=q2(discount_percent), customer_id=customer_id, quotation_id=quotation_id,
                     sales_order_id=sales_order_id, handling_department_id=department_id,
                     created_by=user.id if user else None, status="assigned")
    db.add(work)
    db.flush()
    dept = db.get(Department, department_id) if department_id else None
    log_event(db, work, "created", opened_title,
              f"Quoted amount {q2(quotation_amount)}." + (f" Assigned to {dept.name}." if dept else " Not yet assigned to a department."),
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


def deliver(db: Session, work: WorkOrder, user: User, delivered_on: date | None, note: str | None, from_stock: bool):
    if work.status == "closed":
        raise WorkError("This work is closed.")
    if work.status == "delivered":
        raise WorkError("This work is already delivered.")
    if work.status != "po_received":
        if work.status == "allocated" and from_stock:
            pass   # served from existing stock: no purchase needed
        elif work.status == "allocated":
            raise WorkError("No purchase order is linked yet. Tick 'deliver from stock' if no purchase was needed.")
        else:
            raise WorkError(f"A work in status '{STATUSES[work.status]['label']}' cannot be delivered yet.")
    from_stock = from_stock and work.status == "allocated"
    work.delivered_on = delivered_on or date.today()
    work.delivery_note = (note or "").strip() or None
    _set_status(db, work, "delivered")
    log_event(db, work, "delivered", "Delivered to customer",
              f"Delivered on {work.delivered_on}." + (f" {work.delivery_note}" if work.delivery_note else "")
              + (" Served from existing stock." if from_stock else ""),
              user)
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
    log_event(db, work, "closed", "Work closed", f"Fully paid ({received_amount(work)}). Closed by {user.name}.", user)
    return work


# ------------------------------------------------------- cross-module hooks
def on_quotation_accepted(db: Session, quotation: Quotation, order, user: User | None = None):
    """Sales: the customer said yes. Opens a work (once per quotation)."""
    if db.query(WorkOrder.id).filter(WorkOrder.org_id == quotation.org_id, WorkOrder.quotation_id == quotation.id).first():
        return None
    customer = db.get(Customer, quotation.customer_id)
    industry = None
    if customer and customer.account_id:
        acc = db.get(Account, customer.account_id)
        industry = acc.industry if acc else None
    work = create_work(db, quotation.org_id, user, client_name=customer.name if customer else "Customer",
                       domain=industry, client_details=(customer.billing_address if customer else None),
                       quotation_amount=quotation.total or 0, customer_id=quotation.customer_id,
                       quotation_id=quotation.id, sales_order_id=order.id if order else None,
                       opened_title="Deal accepted - moved to the purchase team")
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


def on_po_created(db: Session, po: PurchaseOrder, user: User | None):
    work = _get_work(db, po.org_id, po.work_order_id)
    if not work:
        return
    first = db.query(PurchaseOrder.id).filter(PurchaseOrder.work_order_id == work.id, PurchaseOrder.id != po.id).first() is None
    if first and not Decimal(work.vendor_amount or 0):
        work.vendor_amount = q2(po.total)
    if work.status in ("assigned", "allocated", "waiting_new_po"):
        _set_status(db, work, "po_raised")
    log_event(db, work, "po_raised", f"{po.po_number} raised",
              f"Raised by {user.name if user else 'a buyer'} for {q2(po.total)}; waiting for approval.", user,
              {"po_id": str(po.id), "po_number": po.po_number})


def on_po_decision(db: Session, po: PurchaseOrder, user: User | None, approved: bool):
    work = _get_work(db, po.org_id, po.work_order_id)
    if not work:
        return
    if approved:
        log_event(db, work, "po_approved", f"{po.po_number} approved", f"Approved by {user.name if user else 'an approver'}.", user)
        return
    log_event(db, work, "po_rejected", f"{po.po_number} rejected", f"Rejected by {user.name if user else 'an approver'}.", user)
    if work.status == "po_raised" and not _active_pos(db, work):
        _set_status(db, work, "allocated" if work.allocated_employee_id else "assigned")


def on_po_received(db: Session, po: PurchaseOrder, user: User | None):
    work = _get_work(db, po.org_id, po.work_order_id)
    if not work:
        return
    log_event(db, work, "po_received", f"{po.po_number} received in good condition",
              f"Goods checked and added to stock by {user.name if user else 'the warehouse'}.", user, {"po_number": po.po_number})
    if work.status in ("assigned", "allocated", "po_raised", "waiting_new_po"):
        if all(p.status == "received" for p in _active_pos(db, work)):
            _set_status(db, work, "po_received")


def on_po_defective(db: Session, po: PurchaseOrder, user: User | None, notes: str | None = None):
    work = _get_work(db, po.org_id, po.work_order_id)
    if not work:
        return
    log_event(db, work, "po_defective", f"{po.po_number} arrived defective",
              (notes or "Goods were damaged on arrival and were not added to stock.") + " Waiting for a replacement purchase order.",
              user, {"po_number": po.po_number})
    if work.status in ("assigned", "allocated", "po_raised", "po_received", "waiting_new_po"):
        _set_status(db, work, "waiting_new_po")


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


# ------------------------------------------------------------ presentation
def _name(u) -> str | None:
    return u.name if u else None


def summary_row(db: Session, w: WorkOrder) -> dict:
    dept = db.get(Department, w.handling_department_id) if w.handling_department_id else None
    return {
        "id": w.id, "work_number": w.work_number, "client_name": w.client_name, "domain": w.domain,
        "status": w.status, "status_label": STATUSES[w.status]["label"], "status_color": STATUSES[w.status]["color"],
        "quotation_amount": q2(w.quotation_amount), "vendor_amount": q2(w.vendor_amount),
        "discount_percent": q2(w.discount_percent), "discount_amount": discount_amount(w),
        "net_payable": net_payable(w), "profit": profit(w),
        "received_amount": received_amount(w), "pending_amount": pending_amount(w),
        "handling_department": dept.name if dept else None, "handling_department_id": w.handling_department_id,
        "created_at": w.created_at,
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
