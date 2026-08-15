import uuid
from datetime import datetime, date

from sqlalchemy import Column, String, ForeignKey, DateTime, Date, Integer
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class ProductCategory(Base):
    __tablename__ = "product_categories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    name = Column(String, nullable=False)


class Warehouse(Base):
    """
    Where physical stock lives. Every org gets one 'Main Warehouse'
    self-healed automatically the first time stock needs to move (see
    app/services/inventory.py get_default_warehouse) - the same pattern
    used for default accounts in Finance. Multi-warehouse support (letting
    a client pick which warehouse an order ships from) is a reasonable
    later enhancement, not needed to prove the concept.
    """
    __tablename__ = "warehouses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    name = Column(String, nullable=False)
    location = Column(String, nullable=True)


class StockLevel(Base):
    """
    The CURRENT quantity of one product in one warehouse. This is the only
    place a stock "total" is ever stored - it's kept in sync by
    StockMovement rows (see app/services/inventory.py), never edited
    directly, so it can never silently drift from the movement history
    that explains how it got there.
    """
    __tablename__ = "stock_levels"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    warehouse_id = Column(UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False)
    quantity = Column(Integer, nullable=False, default=0)


class StockMovement(Base):
    """
    A permanent, append-only ledger of every unit that ever moved in or
    out - exactly like the Audit Log / Journal Entry pattern used
    elsewhere. movement_type is 'in' (Procurement receipt) or 'out'
    (Sales fulfillment). ref_type/ref_id point back to whatever caused
    the movement (e.g. ref_type="purchase_order", ref_id=<po.id>).
    """
    __tablename__ = "stock_movements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    warehouse_id = Column(UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False)
    movement_type = Column(String, nullable=False)  # "in" / "out"
    qty = Column(Integer, nullable=False)
    ref_type = Column(String, nullable=True)   # e.g. "purchase_order", "sales_order"
    ref_id = Column(UUID(as_uuid=True), nullable=True)
    date = Column(Date, default=date.today)
    created_at = Column(DateTime, default=datetime.utcnow)
