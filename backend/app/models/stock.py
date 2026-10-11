import uuid
from datetime import datetime, date

from sqlalchemy import Column, String, ForeignKey, DateTime, Date, Numeric, Integer, Text
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class StockBatch(Base):
    """
    One lot of a product that came in at one purchase rate: what we paid for it,
    the most it may be sold for (MRP), and the largest discount allowed on it.

    StockLevel still holds the per-product total; batches are the PRICED breakdown
    of that total. They are filled by Stock Intake (existing stock, opening stock,
    CSV import) and by every good Purchase Order receipt, and used up when a work
    takes stock from inventory (first-expiry-first-out). Never edited by hand
    except the rates and dates, so quantity_remaining always has a movement behind it.
    """
    __tablename__ = "stock_batches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    vendor_id = Column(UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=True)
    vendor_name = Column(String, nullable=False)
    quantity_in = Column(Integer, nullable=False)
    quantity_remaining = Column(Integer, nullable=False)
    vendor_amount = Column(Numeric(12, 2), nullable=False)          # rate we bought it at, per unit
    mrp = Column(Numeric(12, 2), nullable=False)                    # most it can be sold for, per unit
    max_discount_percent = Column(Numeric(5, 2), nullable=False, default=0)
    inward_date = Column(Date, nullable=False, default=date.today)
    manufacture_month = Column(Date, nullable=True)                 # always the 1st of the month
    expiry_date = Column(Date, nullable=True)
    source = Column(String, nullable=False, default="manual")       # manual / csv / purchase_order / opening
    po_id = Column(UUID(as_uuid=True), ForeignKey("purchase_orders.id"), nullable=True)
    note = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
