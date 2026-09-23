import uuid
from datetime import datetime, date

from sqlalchemy import Column, String, ForeignKey, DateTime, Date, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class ChartOfAccounts(Base):
    """
    The master list of 'buckets' money can sit in or flow through -
    e.g. 'Cash', 'Accounts Receivable', 'Sales Revenue'. Every organization
    gets a small default set seeded automatically at signup (see
    app/services/accounting.py) so Finance isn't empty on day one.
    account_type is one of: asset / liability / equity / revenue / expense
    """
    __tablename__ = "chart_of_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    code = Column(String, nullable=False)       # e.g. "1000"
    name = Column(String, nullable=False)        # e.g. "Cash"
    account_type = Column(String, nullable=False)


class JournalEntry(Base):
    """
    One accounting event, e.g. 'Invoice #123 issued' or 'Payment received
    for Invoice #123'. On its own it has no amounts - the actual money
    values live in its JournalLine rows below. This split is what lets a
    single entry touch two (or more) accounts at once, which is the whole
    idea behind double-entry bookkeeping: every entry's debits must equal
    its credits.
    """
    __tablename__ = "journal_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    date = Column(Date, default=date.today)
    reference = Column(String, nullable=True)     # e.g. "INV-<invoice id>"
    description = Column(String, nullable=True)

    lines = relationship("JournalLine", back_populates="entry", cascade="all, delete-orphan")


class JournalLine(Base):
    """
    One half of a Journal Entry - a single debit OR credit against one
    account. A balanced entry (debits == credits) always has at least two
    of these rows.
    """
    __tablename__ = "journal_lines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    journal_entry_id = Column(UUID(as_uuid=True), ForeignKey("journal_entries.id"), nullable=False)
    account_id = Column(UUID(as_uuid=True), ForeignKey("chart_of_accounts.id"), nullable=False)
    debit = Column(Numeric(12, 2), default=0)
    credit = Column(Numeric(12, 2), default=0)

    entry = relationship("JournalEntry", back_populates="lines")
    account = relationship("ChartOfAccounts")


class Payment(Base):
    """
    Money actually received against an Invoice. Recording one of these
    also posts a Journal Entry (Debit Cash, Credit Accounts Receivable) -
    see app/services/accounting.py.
    """
    __tablename__ = "payments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    invoice_id = Column(UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    method = Column(String, default="bank_transfer")
    date = Column(Date, default=date.today)
    created_at = Column(DateTime, default=datetime.utcnow)
