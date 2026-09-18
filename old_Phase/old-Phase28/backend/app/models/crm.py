import uuid
from datetime import datetime, date

from sqlalchemy import Column, String, ForeignKey, DateTime, Date, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class Account(Base):
    """
    A company/organization that the CRM tracks - a customer's business,
    not to be confused with our own 'Organization' (tenant) model.
    Named 'Account' deliberately, matching standard CRM terminology
    (Salesforce, HubSpot, etc. all call this an Account).
    """
    __tablename__ = "crm_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    name = Column(String, nullable=False)
    industry = Column(String, nullable=True)
    address = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    contacts = relationship("Contact", back_populates="account")


class Contact(Base):
    """A specific person at an Account."""
    __tablename__ = "crm_contacts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    account_id = Column(UUID(as_uuid=True), ForeignKey("crm_accounts.id"), nullable=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    account = relationship("Account", back_populates="contacts")


class Lead(Base):
    """
    A not-yet-qualified potential customer. The very top of the funnel -
    hasn't been confirmed as a real Account/Contact yet.
    status moves through: "new" -> "contacted" -> "qualified" -> "converted" / "lost"
    """
    __tablename__ = "crm_leads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    name = Column(String, nullable=False)
    company_name = Column(String, nullable=True)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    source = Column(String, nullable=True)   # e.g. "Website", "Referral", "Cold Call"
    status = Column(String, default="new")
    assigned_to = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Opportunity(Base):
    """
    A qualified, in-progress deal with a real Account/Contact attached.
    stage moves through: "prospecting" -> "proposal" -> "negotiation" -> "won" / "lost"
    This is the record that eventually becomes a Sales Quotation.
    """
    __tablename__ = "crm_opportunities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    account_id = Column(UUID(as_uuid=True), ForeignKey("crm_accounts.id"), nullable=True)
    contact_id = Column(UUID(as_uuid=True), ForeignKey("crm_contacts.id"), nullable=True)
    name = Column(String, nullable=False)
    stage = Column(String, default="prospecting")
    value = Column(Numeric(12, 2), default=0)
    expected_close = Column(Date, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    account = relationship("Account")
    contact = relationship("Contact")
