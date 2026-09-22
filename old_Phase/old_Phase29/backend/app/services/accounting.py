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

# Every organization gets these accounts automatically at signup (or via
# self-healing on first use - see get_account below). Adding a new entry
# here (like Payroll Expense in Phase 5) is automatically picked up by
# self-healing for EVERY organization, old or new - no backfill needed.
DEFAULT_ACCOUNTS = [
    ("1000", "Cash", "asset"),
    ("1100", "Accounts Receivable", "asset"),
    ("4000", "Sales Revenue", "revenue"),
    ("5000", "Payroll Expense", "expense"),
]


def seed_default_accounts(db: Session, org_id: str) -> None:
    """Called once, right when a new organization signs up."""
    for code, name, account_type in DEFAULT_ACCOUNTS:
        db.add(ChartOfAccounts(org_id=org_id, code=code, name=name, account_type=account_type))


def get_account(db: Session, org_id: str, code: str) -> ChartOfAccounts:
    """
    Looks up a default account by code, and SELF-HEALS if it's missing.

    Why this matters: seed_default_accounts() only runs once, at signup.
    Any organization created before that code existed (or before we later
    add a NEW default account in a future phase, e.g. Accounts Payable in
    Procurement) would otherwise hit a hard failure here forever, with no
    way to recover except a manual database fix. Self-healing means the
    very next time this account is actually needed, it gets created on
    the spot - permanently closing this entire category of bug, for every
    organization, past or future, without anyone needing to run a script.
    """
    account = (
        db.query(ChartOfAccounts)
        .filter(ChartOfAccounts.org_id == org_id, ChartOfAccounts.code == code)
        .first()
    )
    if account:
        return account

    default = next((d for d in DEFAULT_ACCOUNTS if d[0] == code), None)
    if not default:
        # This code isn't even in our known defaults - a genuine
        # configuration error, not a missing-seed situation. Still fail
        # loudly here, since self-healing an *unknown* account would hide
        # a real bug instead of fixing a data gap.
        raise ValueError(f"Account {code} is not a recognized default account.")

    default_code, name, account_type = default
    account = ChartOfAccounts(org_id=org_id, code=default_code, name=name, account_type=account_type)
    db.add(account)
    db.flush()
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


def post_payroll_journal_entry(db: Session, org_id: str, payroll_run_id: str, total_net_pay) -> JournalEntry:
    """
    The moment a Payroll Run is processed, we record:
        Debit  Payroll Expense   (this cost the company money)
        Credit Cash              (assuming immediate payment - a company
                                  using a 'Salaries Payable' liability
                                  account instead, for payroll paid on a
                                  delay, is a reasonable later refinement)
    One entry for the WHOLE run's total, not one per employee - keeps the
    ledger readable, matching how a real payroll journal entry looks.
    """
    payroll_expense_account = get_account(db, org_id, "5000")
    cash_account = get_account(db, org_id, "1000")

    entry = JournalEntry(org_id=org_id, reference=f"PAYROLL-{payroll_run_id}", description="Payroll processed")
    entry.lines.append(JournalLine(account_id=payroll_expense_account.id, debit=total_net_pay, credit=0))
    entry.lines.append(JournalLine(account_id=cash_account.id, debit=0, credit=total_net_pay))
    db.add(entry)
    return entry
