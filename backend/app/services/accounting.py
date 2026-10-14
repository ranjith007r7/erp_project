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
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.organization import Organization

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
    # PF, insurance and TDS withheld from salaries: owed to the authorities
    # until paid out, so a liability. Created on first use like every default.
    ("2100", "Payroll Deductions Payable", "liability"),
    # GST collected from customers on sales: owed to the government until it is paid over, so liabilities.
    ("2210", "CGST Payable", "liability"),
    ("2220", "SGST Payable", "liability"),
    # the part of a customer's money kept when they cancel (a % of what they paid)
    ("4100", "Cancellation Charges", "revenue"),
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


def next_entry_number(db: Session, org_id: str) -> str:
    """
    Readable running number ("JE-0001") per organization. The organization row
    is locked for the rest of the transaction so two simultaneous postings can
    never be given the same number.
    """
    db.flush()  # entries added earlier in this transaction must be visible to the count below
    db.query(Organization).filter(Organization.id == org_id).with_for_update().first()
    n = db.query(func.count(JournalEntry.id)).filter(JournalEntry.org_id == org_id).scalar() or 0
    while True:
        n += 1
        number = f"JE-{n:04d}"
        taken = db.query(JournalEntry.id).filter(JournalEntry.org_id == org_id, JournalEntry.entry_number == number).first()
        if not taken:
            return number


def post_invoice_journal_entry(db: Session, org_id: str, invoice_id: str, amount, cgst=0, sgst=0) -> JournalEntry:
    """
    The moment an Invoice is generated, we record:
        Debit  Accounts Receivable   (we're now owed the full amount, GST included)
        Credit Sales Revenue         (the taxable value we have earned)
        Credit CGST Payable / SGST Payable (GST collected on behalf of the government, only when there is any)
    This does NOT commit - the caller (Sales route) commits once, so the
    Invoice row and this Journal Entry are saved together or not at all.
    """
    ar_account = get_account(db, org_id, "1100")
    revenue_account = get_account(db, org_id, "4000")

    entry = JournalEntry(org_id=org_id, entry_number=next_entry_number(db, org_id),
                         reference=f"INV-{invoice_id}", description="Invoice issued")
    cgst, sgst = Decimal(cgst or 0), Decimal(sgst or 0)
    entry.lines.append(JournalLine(account_id=ar_account.id, debit=amount, credit=0))
    entry.lines.append(JournalLine(account_id=revenue_account.id, debit=0, credit=Decimal(amount) - cgst - sgst))
    if cgst:
        entry.lines.append(JournalLine(account_id=get_account(db, org_id, "2210").id, debit=0, credit=cgst))
    if sgst:
        entry.lines.append(JournalLine(account_id=get_account(db, org_id, "2220").id, debit=0, credit=sgst))
    db.add(entry)
    return entry


def post_payment_journal_entry(db: Session, org_id: str, payment_id: str, amount, note: str | None = None) -> JournalEntry:
    """
    The moment a Payment is recorded against an Invoice, we record:
        Debit  Cash                  (money has arrived)
        Credit Accounts Receivable   (they no longer owe us this part)
    """
    cash_account = get_account(db, org_id, "1000")
    ar_account = get_account(db, org_id, "1100")

    entry = JournalEntry(org_id=org_id, entry_number=next_entry_number(db, org_id), reference=f"PMT-{payment_id}",
                         description="Payment received" + (f" ({note})" if note else ""))
    entry.lines.append(JournalLine(account_id=cash_account.id, debit=amount, credit=0))
    entry.lines.append(JournalLine(account_id=ar_account.id, debit=0, credit=amount))
    db.add(entry)
    return entry


def post_work_receipt_journal_entry(db: Session, org_id: str, payment_id: str, amount, note: str | None = None,
                                    cgst_percent=0, sgst_percent=0) -> JournalEntry:
    """
    Money received straight against a customer work (Workpage), which has no
    Sales invoice behind it to have raised a receivable first:
        Debit  Cash             (money has arrived)
        Credit Sales Revenue    (it is earned income)
    """
    cash_account = get_account(db, org_id, "1000")
    revenue_account = get_account(db, org_id, "4000")
    entry = JournalEntry(org_id=org_id, entry_number=next_entry_number(db, org_id), reference=f"WPMT-{payment_id}",
                         description="Work payment received" + (f" ({note})" if note else ""))
    # The payment is GST-inclusive: split it pro rata into revenue and the GST payable accounts.
    amount = Decimal(amount)
    c, s_ = Decimal(cgst_percent or 0), Decimal(sgst_percent or 0)
    cgst = (amount * c / (100 + c + s_)).quantize(Decimal("0.01")) if c else Decimal(0)
    sgst = (amount * s_ / (100 + c + s_)).quantize(Decimal("0.01")) if s_ else Decimal(0)
    entry.lines.append(JournalLine(account_id=cash_account.id, debit=amount, credit=0))
    entry.lines.append(JournalLine(account_id=revenue_account.id, debit=0, credit=amount - cgst - sgst))
    if cgst:
        entry.lines.append(JournalLine(account_id=get_account(db, org_id, "2210").id, debit=0, credit=cgst))
    if sgst:
        entry.lines.append(JournalLine(account_id=get_account(db, org_id, "2220").id, debit=0, credit=sgst))
    db.add(entry)
    return entry


def post_credit_note_journal_entry(db: Session, org_id: str, invoice_id: str, amount, cgst=0, sgst=0) -> JournalEntry:
    """A cancelled Sales invoice is reversed in full (nothing was supplied):
        Debit  Sales Revenue (taxable value) and CGST / SGST Payable    Credit Accounts Receivable (gross)"""
    amount, cgst, sgst = Decimal(amount), Decimal(cgst or 0), Decimal(sgst or 0)
    entry = JournalEntry(org_id=org_id, entry_number=next_entry_number(db, org_id), reference=f"CN-{invoice_id}",
                         description="Credit note: invoice cancelled")
    entry.lines.append(JournalLine(account_id=get_account(db, org_id, "4000").id, debit=amount - cgst - sgst, credit=0))
    if cgst:
        entry.lines.append(JournalLine(account_id=get_account(db, org_id, "2210").id, debit=cgst, credit=0))
    if sgst:
        entry.lines.append(JournalLine(account_id=get_account(db, org_id, "2220").id, debit=sgst, credit=0))
    entry.lines.append(JournalLine(account_id=get_account(db, org_id, "1100").id, debit=0, credit=amount))
    db.add(entry)
    return entry


def post_refund_journal_entry(db: Session, org_id: str, refund_id: str, received, refund_amount, charge_amount, *,
                              against_invoice: bool, cgst_percent=0, sgst_percent=0, note: str | None = None) -> JournalEntry:
    """Money going back to a customer after a cancellation.
    Cancelled work paid straight on the work (revenue and GST were booked with each receipt): reverse them,
        Debit  Sales Revenue + CGST / SGST Payable (everything received)
        Credit Cash (refund paid out)   Credit Cancellation Charges (the part kept)
    Cancelled Sales order: the credit note already reversed the sale, so the debit lands on Accounts Receivable instead."""
    received, refund_amount, charge_amount = Decimal(received), Decimal(refund_amount), Decimal(charge_amount)
    entry = JournalEntry(org_id=org_id, entry_number=next_entry_number(db, org_id), reference=f"RFND-{refund_id}",
                         description="Refund to customer" + (f" ({note})" if note else ""))
    if against_invoice:
        entry.lines.append(JournalLine(account_id=get_account(db, org_id, "1100").id, debit=received, credit=0))
    else:
        c, s_ = Decimal(cgst_percent or 0), Decimal(sgst_percent or 0)
        cg = (received * c / (100 + c + s_)).quantize(Decimal("0.01")) if c else Decimal(0)
        sg = (received * s_ / (100 + c + s_)).quantize(Decimal("0.01")) if s_ else Decimal(0)
        entry.lines.append(JournalLine(account_id=get_account(db, org_id, "4000").id, debit=received - cg - sg, credit=0))
        if cg:
            entry.lines.append(JournalLine(account_id=get_account(db, org_id, "2210").id, debit=cg, credit=0))
        if sg:
            entry.lines.append(JournalLine(account_id=get_account(db, org_id, "2220").id, debit=sg, credit=0))
    if refund_amount:
        entry.lines.append(JournalLine(account_id=get_account(db, org_id, "1000").id, debit=0, credit=refund_amount))
    if charge_amount:
        entry.lines.append(JournalLine(account_id=get_account(db, org_id, "4100").id, debit=0, credit=charge_amount))
    db.add(entry)
    return entry


def post_payroll_journal_entry(db: Session, org_id: str, payroll_run_id: str, total_net_pay,
                               total_expense=None, statutory_deductions=0) -> JournalEntry:
    """
    The moment a Payroll Run is processed, we record ONE entry for the whole run:
        Debit  Payroll Expense              earned pay (gross less unpaid-leave deduction)
        Credit Cash                         net pay actually paid out
        Credit Payroll Deductions Payable   PF + insurance + TDS withheld, owed onward
    expense = net + withheld, so it always balances. Unpaid-leave money is simply
    never an expense. Called with only the net amount (old callers), it behaves as
    before: Debit Payroll Expense / Credit Cash for that amount.
    """
    statutory = statutory_deductions or 0
    expense = total_expense if total_expense is not None else total_net_pay + statutory
    payroll_expense_account = get_account(db, org_id, "5000")
    cash_account = get_account(db, org_id, "1000")

    entry = JournalEntry(org_id=org_id, entry_number=next_entry_number(db, org_id),
                         reference=f"PAYROLL-{payroll_run_id}", description="Payroll processed")
    entry.lines.append(JournalLine(account_id=payroll_expense_account.id, debit=expense, credit=0))
    entry.lines.append(JournalLine(account_id=cash_account.id, debit=0, credit=total_net_pay))
    if statutory:
        payable = get_account(db, org_id, "2100")
        entry.lines.append(JournalLine(account_id=payable.id, debit=0, credit=statutory))
    db.add(entry)
    return entry
