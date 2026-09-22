import uuid
from datetime import datetime, date

from sqlalchemy import Column, String, ForeignKey, DateTime, Date, Numeric, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class Product(Base):
    """
    Started DELIBERATELY MINIMAL in Phase 2 (Sales) - just enough for a
    Sales Order to have line items with a price. Now extended here in
    Phase 4 (Inventory) with the fields real stock tracking needs -
    exactly as planned back then, this is the SAME table gaining columns,
    not a second competing table. Nothing built in Sales needed to change.
    """
    __tablename__ = "products"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    name = Column(String, nullable=False)
    unit_price = Column(Numeric(12, 2), nullable=False, default=0)
    sku = Column(String, nullable=True)
    category_id = Column(UUID(as_uuid=True), ForeignKey("product_categories.id"), nullable=True)
    reorder_level = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class Customer(Base):
    """
    A confirmed, paying customer - distinct from a CRM Account because not
    every Account becomes a Customer, and Sales needs billing-specific
    fields (GST number, billing address) that CRM doesn't care about.
    """
    __tablename__ = "customers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    account_id = Column(UUID(as_uuid=True), ForeignKey("crm_accounts.id"), nullable=True)
    name = Column(String, nullable=False)
    billing_address = Column(String, nullable=True)
    gst_number = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Quotation(Base):
    """A price quote sent to a customer, before they've committed to buying."""
    __tablename__ = "quotations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False)
    opportunity_id = Column(UUID(as_uuid=True), ForeignKey("crm_opportunities.id"), nullable=True)
    total = Column(Numeric(12, 2), default=0)
    status = Column(String, default="draft")  # draft / sent / accepted / rejected
    created_at = Column(DateTime, default=datetime.utcnow)

    items = relationship("QuotationItem", back_populates="quotation", cascade="all, delete-orphan")


class QuotationItem(Base):
    __tablename__ = "quotation_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quotation_id = Column(UUID(as_uuid=True), ForeignKey("quotations.id"), nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    qty = Column(Integer, nullable=False, default=1)
    unit_price = Column(Numeric(12, 2), nullable=False)

    quotation = relationship("Quotation", back_populates="items")
    product = relationship("Product")


class SalesOrder(Base):
    """A confirmed order - created once a customer accepts a Quotation."""
    __tablename__ = "sales_orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False)
    quotation_id = Column(UUID(as_uuid=True), ForeignKey("quotations.id"), nullable=True)
    order_date = Column(Date, default=date.today)
    status = Column(String, default="pending")  # pending / fulfilled / cancelled
    total = Column(Numeric(12, 2), default=0)

    items = relationship("SalesOrderItem", back_populates="order", cascade="all, delete-orphan")


class SalesOrderItem(Base):
    __tablename__ = "sales_order_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("sales_orders.id"), nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    qty = Column(Integer, nullable=False, default=1)
    unit_price = Column(Numeric(12, 2), nullable=False)

    order = relationship("SalesOrder", back_populates="items")
    product = relationship("Product")


class Invoice(Base):
    """
    The bill sent to the customer for a Sales Order. This is deliberately
    NOT connected to Finance's Journal Entry yet - that wiring gets added
    when we build the Finance & Accounting module, without changing
    anything here.
    """
    __tablename__ = "invoices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    order_id = Column(UUID(as_uuid=True), ForeignKey("sales_orders.id"), nullable=False)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    due_date = Column(Date, nullable=True)
    status = Column(String, default="unpaid")  # unpaid / paid / overdue
    created_at = Column(DateTime, default=datetime.utcnow)
