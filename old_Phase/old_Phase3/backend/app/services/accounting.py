"""
This is the ONE place that knows how to post a Journal Entry. Both the
Sales module (when an Invoice is generated) and the Finance module (when a
Payment is recorded) call into here, instead of each writing their own
copy of "create two balanced lines" logic.

Living here (not inside routes/sales.py or routes/finance.py) also avoids
a circular import: Sales needs Finance's accounts to post to, and Finance
needs Sales' Invoice model for Payments - putting the shared logic in its
own module means neither route file has to import the other.
"""
from sqlalchemy.orm import Session

from app.models.finance import ChartOfAccounts, JournalEntry, JournalLine

# Every organization gets these three accounts automatically at signup.
# More get added when Procurement/HR/Inventory need their own (e.g.
# Accounts Payable, Payroll Expense) - this list is deliberately minimal
# for what Sales needs today.
DEFAULT_ACCOUNTS = [
    ("1000", "Cash", "asset"),
    ("1100", "Accounts Receivable", "asset"),
    ("4000", "Sales Revenue", "revenue"),
]


def seed_default_accounts(db: Session, org_id: str) -> None:
    """Called once, right when a new organization signs up."""
    for code, name, account_type in DEFAULT_ACCOUNTS:
        db.add(ChartOfAccounts(org_id=org_id, code=code, name=name, account_type=account_type))


def get_account(db: Session, org_id: str, code: str) -> ChartOfAccounts:
    account = (
        db.query(ChartOfAccounts)
        .filter(ChartOfAccounts.org_id == org_id, ChartOfAccounts.code == code)
        .first()
    )
    if not account:
        raise ValueError(
            f"Account {code} not found for this organization - "
            f"default accounts may not have been seeded at signup."
        )
    return account


def post_invoice_journal_entry(db: Session, org_id: str, invoice_id: str, amount) -> JournalEntry:
    """
    The moment an Invoice is generated, we record:
        Debit  Accounts Receivable   (we're now owed this money)
        Credit Sales Revenue         (we've earned this revenue)
    This does NOT commit - the caller (Sales route) commits once, so the
    Invoice row and this Journal Entry are saved together or not at all.
    """
    ar_account = get_account(db, org_id, "1100")
    revenue_account = get_account(db, org_id, "4000")

    entry = JournalEntry(org_id=org_id, reference=f"INV-{invoice_id}", description="Invoice issued")
    entry.lines.append(JournalLine(account_id=ar_account.id, debit=amount, credit=0))
    entry.lines.append(JournalLine(account_id=revenue_account.id, debit=0, credit=amount))
    db.add(entry)
    return entry


def post_payment_journal_entry(db: Session, org_id: str, payment_id: str, amount) -> JournalEntry:
    """
    The moment a Payment is recorded against an Invoice, we record:
        Debit  Cash                  (money has arrived)
        Credit Accounts Receivable   (they no longer owe us this part)
    """
    cash_account = get_account(db, org_id, "1000")
    ar_account = get_account(db, org_id, "1100")

    entry = JournalEntry(org_id=org_id, reference=f"PMT-{payment_id}", description="Payment received")
    entry.lines.append(JournalLine(account_id=cash_account.id, debit=amount, credit=0))
    entry.lines.append(JournalLine(account_id=ar_account.id, debit=0, credit=amount))
    db.add(entry)
    return entry
