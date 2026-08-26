"""
Finance module routes. Two read-only views (accounts, journal entries) plus
one real action: recording a Payment against an Invoice, which posts its
own Journal Entry through the same shared accounting service Sales uses.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.api.deps import get_current_user, get_org_id, require_permission
from app.models.finance import ChartOfAccounts, JournalEntry, Payment
from app.models.sales import Invoice
from app.schemas.finance import AccountOut, JournalEntryOut, PaymentCreate, PaymentOut
from app.services.accounting import post_payment_journal_entry
from app.services.notifications import notify_role
from app.services.audit import log_audit_event

router = APIRouter(prefix="/api/finance", tags=["finance"], dependencies=[Depends(get_current_user)])


@router.get("/accounts", response_model=list[AccountOut], dependencies=[Depends(require_permission("finance", "view"))])
def list_accounts(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return db.query(ChartOfAccounts).filter(ChartOfAccounts.org_id == org_id).order_by(ChartOfAccounts.code).all()


@router.get("/journal-entries", response_model=list[JournalEntryOut], dependencies=[Depends(require_permission("finance", "view"))])
def list_journal_entries(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return (
        db.query(JournalEntry)
        .options(joinedload(JournalEntry.lines))
        .filter(JournalEntry.org_id == org_id)
        .order_by(JournalEntry.date.desc())
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

    payment = Payment(
        org_id=org_id,
        invoice_id=invoice.id,
        amount=payload.amount,
        method=payload.method,
    )
    db.add(payment)
    db.flush()  # generates payment.id for the journal entry reference

    try:
        post_payment_journal_entry(db, org_id, str(payment.id), payment.amount)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Simple model for now: any payment recorded marks the invoice fully
    # paid. Partial-payment tracking (amount_paid vs amount_due) is a
    # reasonable Phase-4-or-later refinement, not needed for the demo story.
    invoice.status = "paid"

    # Real trigger #1 of 2 for "notifications only cover a few things" -
    # invoice payment recorded is exactly the kind of event a real org
    # would want to know about without someone manually checking Finance.
    notify_role(db, org_id, "Admin", f"Payment of {payment.amount} recorded against an invoice — now marked paid.")

    log_audit_event(db, org_id, current_user.id, "record_payment", "Invoice", invoice.id)
    db.commit()
    db.refresh(payment)
    return payment
