"""
Refunds after a cancellation.

When a work that had received money is cancelled, a PENDING refund appears in Finance > Refunds. Finance records the
cancellation charge (a percentage of what the customer paid; 0% = full refund), pays the rest back by cash, card, GPay,
bank transfer or cheque, pastes the transaction id for anything that is not cash, and marks it COMPLETED. That posts
the journal entry (the sale is reversed, the charge is kept as income, the rest leaves Cash) and the work's payment
reconciliation shows "Cancelled, refunded".

A cancelled direct Sales order also gets a credit note: its invoice is cancelled and reversed, then the same refund
flow pays the customer back.
"""
import re
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.finance import Refund
from app.models.organization import Organization
from app.models.sales import Invoice, SalesOrder
from app.models.workpage import WorkOrder
from app.services import gst
from app.services.accounting import post_credit_note_journal_entry, post_refund_journal_entry

METHODS = ("cash", "card", "gpay", "bank_transfer", "cheque")
METHODS_NEEDING_REFERENCE = ("card", "gpay", "bank_transfer", "cheque")
TXN_RE = re.compile(r"^[A-Za-z0-9._\-/]{4,64}$")
q2 = gst.q2


class RefundError(Exception):
    pass


def next_refund_number(db: Session, org_id) -> str:
    db.flush()
    db.query(Organization).filter(Organization.id == org_id).with_for_update().first()
    n = db.query(func.count(Refund.id)).filter(Refund.org_id == org_id).scalar() or 0
    while True:
        n += 1
        number = f"RF-{n:04d}"
        if not db.query(Refund.id).filter(Refund.org_id == org_id, Refund.refund_number == number).first():
            return number


def split(received, charge_percent) -> tuple[Decimal, Decimal]:
    """(cancellation charge, amount to refund) for a charge in percent of what was received."""
    received = q2(received)
    charge = q2(received * Decimal(charge_percent or 0) / 100)
    return charge, received - charge


def credit_note_for_sales_order(db: Session, work: WorkOrder, user) -> Invoice | None:
    """Cancel the invoice of a cancelled direct Sales order and reverse it (credit note). Idempotent."""
    from app.services import workpages as wp
    inv = wp.sales_invoice(db, work)
    if inv is None or inv.status == "cancelled":
        return inv
    post_credit_note_journal_entry(db, work.org_id, str(inv.id), inv.amount, inv.cgst_amount, inv.sgst_amount)
    inv.status = "cancelled"
    order = db.get(SalesOrder, work.sales_order_id) if work.sales_order_id else None
    if order:
        order.status = "cancelled"
    wp.log_event(db, work, "credit_note", "Invoice cancelled (credit note)",
                 f"{inv.invoice_number or 'The invoice'} for {q2(inv.amount)} was reversed in the books because the order was cancelled.", user)
    return inv


def create_pending(db: Session, work: WorkOrder, user=None) -> Refund | None:
    """A cancelled work that had received money gets one pending refund (none if it already has one)."""
    from app.services import workpages as wp
    got = wp.received_amount(work)
    if got <= 0:
        return None
    existing = db.query(Refund).filter(Refund.work_id == work.id).first()
    if existing:
        return existing
    inv = wp.sales_invoice(db, work) if wp.is_sales_order(work) else None
    r = Refund(org_id=work.org_id, refund_number=next_refund_number(db, work.org_id), work_id=work.id, invoice_id=inv.id if inv else None,
               client_name=work.client_name, reason=work.cancel_reason, received_amount=got, charge_percent=0, charge_amount=0,
               refund_amount=got, status="pending")
    db.add(r)
    db.flush()
    wp.log_event(db, work, "refund_pending", f"Refund {r.refund_number} pending",
                 f"{got} was received from the customer. Finance records the cancellation charge and pays it back in Finance > Refunds.", user)
    return r


def heal_pending(db: Session, org_id) -> int:
    """Cancelled works that received money before refunds existed (or whose refund row is missing) get their pending refund."""
    n = 0
    for w in db.query(WorkOrder).filter(WorkOrder.org_id == org_id, WorkOrder.status == "cancelled").all():
        if not db.query(Refund.id).filter(Refund.work_id == w.id).first():
            from app.services import workpages as wp
            if wp.is_sales_order(w):
                credit_note_for_sales_order(db, w, None)
            if create_pending(db, w, None):
                n += 1
    return n


def complete(db: Session, refund: Refund, user, *, charge_percent, method, transaction_id=None, note=None, refund_date: date | None = None) -> Refund:
    from app.services import workpages as wp
    if refund.status == "completed":
        raise RefundError("This refund is already completed.")
    cp = Decimal(charge_percent or 0)
    if cp < 0 or cp > 100:
        raise RefundError("The cancellation charge must be between 0% and 100%.")
    charge, pay = split(refund.received_amount, cp)
    txn = (transaction_id or "").strip() or None
    if pay > 0:
        if method not in METHODS:
            raise RefundError("Pick how the refund is paid: cash, card, GPay, bank transfer or cheque.")
        if method in METHODS_NEEDING_REFERENCE:
            if not txn:
                raise RefundError("Paste the transaction / reference id of the refund. A refund that is not paid in cash is only completed with its transaction id.")
            if not TXN_RE.match(txn):
                raise RefundError("The transaction id must be 4-64 characters: letters, numbers, dash, underscore, dot or slash.")
            if db.query(Refund.id).filter(Refund.org_id == refund.org_id, Refund.transaction_id == txn, Refund.id != refund.id).first():
                raise RefundError(f"Transaction id {txn} is already recorded against another refund.")
        else:
            txn = None
    else:
        method, txn = None, None          # the whole amount is kept as the cancellation charge: nothing is paid out
    work = db.get(WorkOrder, refund.work_id)
    refund.charge_percent, refund.charge_amount, refund.refund_amount = q2(cp), charge, pay
    refund.method, refund.transaction_id, refund.note = method, txn, (note or "").strip() or None
    refund.refund_date = refund_date or date.today()
    refund.status, refund.completed_by, refund.completed_at = "completed", user.id, datetime.utcnow()
    post_refund_journal_entry(db, refund.org_id, str(refund.id), refund.received_amount, pay, charge,
                              against_invoice=refund.invoice_id is not None, cgst_percent=work.cgst_percent, sgst_percent=work.sgst_percent,
                              note=f"{refund.refund_number}, {work.work_number}" + (f", {method}" if method else "") + (f", {txn}" if txn else ""))
    label = {"cash": "Cash", "card": "Card", "gpay": "GPay", "bank_transfer": "Bank transfer", "cheque": "Cheque"}.get(method or "", "")
    wp.log_event(db, work, "refund_completed", f"Refund {refund.refund_number} completed",
                 f"Received {refund.received_amount}; cancellation charge {charge} ({q2(cp)}%); refunded {pay}"
                 + (f" by {label}" + (f" (ref {txn})" if txn else "") if pay else "") + ".", user,
                 {"refund": str(pay), "charge": str(charge), "method": method, "transaction_id": txn})
    return refund


def totals_for_works(db: Session, org_id) -> dict:
    """work_id -> {"refunded", "kept", "status"} for the reconciliation view."""
    out: dict = {}
    for r in db.query(Refund).filter(Refund.org_id == org_id).all():
        o = out.setdefault(r.work_id, {"refunded": Decimal(0), "kept": Decimal(0), "pending": Decimal(0), "number": r.refund_number, "method": None, "reference": None})
        if r.status == "completed":
            o["refunded"] += Decimal(r.refund_amount)
            o["kept"] += Decimal(r.charge_amount)
            o["method"], o["reference"] = r.method, r.transaction_id
        else:
            o["pending"] += Decimal(r.refund_amount)
    return out
