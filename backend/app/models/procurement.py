import uuid
from datetime import datetime, date

from sqlalchemy import Column, String, ForeignKey, DateTime, Date, Numeric, Integer, Text, LargeBinary, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class Vendor(Base):
    __tablename__ = "vendors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    name = Column(String, nullable=False)
    contact = Column(String, nullable=True)
    address = Column(String, nullable=True)
    # Optional. Used only to PRE-FILL the "send PO by email" screen; the
    # buyer can always type a different address there, and vendors with no
    # email at all are served by the PDF / print route instead.
    email = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PurchaseOrder(Base):
    """
    The mirror image of Sales' SalesOrder - instead of stock going OUT to
    a customer, this brings stock IN from a vendor.

    TWO separate status fields, because they answer different questions:
      approval_status: "pending" -> "approved" | "rejected"   (may we order?)
      status:          "pending" -> "received"                (did it arrive?)
                       "pending" -> "defective" -> "received" (arrived damaged,
                                                     replacement came later)
                       "cancelled"                            (rejected PO)
    Only an APPROVED PO can be emailed to the vendor or received.
    """
    __tablename__ = "purchase_orders"
    __table_args__ = (UniqueConstraint("org_id", "po_number", name="uq_po_org_number"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    vendor_id = Column(UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=False)
    order_date = Column(Date, default=date.today)
    status = Column(String, default="pending")  # pending / received / defective / cancelled
    total = Column(Numeric(12, 2), default=0)   # taxable value (the cost basis: input GST is claimable, so it is not cost)
    cgst_amount = Column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    sgst_amount = Column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    grand_total = Column(Numeric(12, 2), nullable=False, default=0, server_default="0")   # what the vendor is paid, GST included

    # Human-readable number printed on emails and PDFs ("PO-0007"), unique
    # per organization. Nullable only so rows created by old scripts that
    # bypass the route still load; the migration back-fills existing rows.
    po_number = Column(String, nullable=True)
    approval_status = Column(String, nullable=False, default="pending", server_default="pending")
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    # Optional: the customer work this PO is bought for. Procurement never reads
    # it; app/services/workpages.py uses it to keep the work's status in step.
    work_order_id = Column(UUID(as_uuid=True), ForeignKey("work_orders.id"), nullable=True)
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    items = relationship("PurchaseOrderItem", back_populates="purchase_order", cascade="all, delete-orphan")
    vendor = relationship("Vendor")
    creator = relationship("User", foreign_keys=[created_by])
    approver = relationship("User", foreign_keys=[approved_by])
    receipts = relationship("GoodsReceipt", back_populates="purchase_order", order_by="GoodsReceipt.created_at")
    corrections = relationship("PoPriceCorrection", order_by="PoPriceCorrection.created_at", cascade="all, delete-orphan")


class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    po_id = Column(UUID(as_uuid=True), ForeignKey("purchase_orders.id"), nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    qty = Column(Integer, nullable=False, default=1)
    unit_price = Column(Numeric(12, 2), nullable=False)   # excludes GST
    cgst_percent = Column(Numeric(5, 2), nullable=False, default=0, server_default="0")
    sgst_percent = Column(Numeric(5, 2), nullable=False, default=0, server_default="0")
    received_qty = Column(Integer, nullable=False, default=0, server_default="0")   # units accepted into stock so far
    warranty_months = Column(Integer, nullable=True)   # warranty the vendor gives us on this line (copied to the lot on receipt)

    @property
    def outstanding_qty(self) -> int:
        return max(int(self.qty) - int(self.received_qty or 0), 0)

    purchase_order = relationship("PurchaseOrder", back_populates="items")
    product = relationship("Product")


class GoodsReceipt(Base):
    """
    Records that a Purchase Order's items physically arrived. Creating one
    of these is what actually triggers stock to increase (see
    app/services/inventory.py receive_stock) - a PO existing does NOT mean
    stock exists yet, only a matching GoodsReceipt does.
    """
    __tablename__ = "goods_receipts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    po_id = Column(UUID(as_uuid=True), ForeignKey("purchase_orders.id"), nullable=False)
    received_date = Column(Date, default=date.today)
    # "good": every item checked by hand and fine -> stock increases.
    # "bad":  damaged/defective -> stock does NOT increase; the proof
    #         (invoice, courier copy, defect photos) and a notice to the
    #         vendor are what this record exists for.
    condition = Column(String, nullable=False, default="good", server_default="good")
    notes = Column(Text, nullable=True)  # free-text defect description
    received_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    purchase_order = relationship("PurchaseOrder", back_populates="receipts")
    receiver = relationship("User", foreign_keys=[received_by])
    files = relationship("GoodsReceiptFile", back_populates="receipt", cascade="all, delete-orphan",
                         order_by="GoodsReceiptFile.created_at")
    lines = relationship("GoodsReceiptLine", back_populates="receipt", cascade="all, delete-orphan")


class GoodsReceiptLine(Base):
    """How many units of one PO line were accepted (qty_good, added to stock) and how many were defective (qty_defective,
    returned for replacement) in one receipt."""
    __tablename__ = "goods_receipt_lines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    receipt_id = Column(UUID(as_uuid=True), ForeignKey("goods_receipts.id"), nullable=False)
    po_item_id = Column(UUID(as_uuid=True), ForeignKey("purchase_order_items.id"), nullable=False)
    qty_good = Column(Integer, nullable=False, default=0, server_default="0")
    qty_defective = Column(Integer, nullable=False, default=0, server_default="0")

    receipt = relationship("GoodsReceipt", back_populates="lines")
    item = relationship("PurchaseOrderItem")


class GoodsReceiptFile(Base):
    """
    One uploaded proof document for a goods receipt: the vendor's original
    invoice ("invoice"), the courier proof-of-delivery copy ("pod"), or a
    photo of damage ("defect"). Stored in the database itself (bytea) rather
    than object storage so the receiving flow never depends on a bucket
    being configured; sizes are capped at MAX_UPLOAD_SIZE_MB per file.
    """
    __tablename__ = "goods_receipt_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    receipt_id = Column(UUID(as_uuid=True), ForeignKey("goods_receipts.id"), nullable=False)
    kind = Column(String, nullable=False)  # invoice / pod / defect
    filename = Column(String, nullable=False)
    content_type = Column(String, nullable=False)
    size = Column(Integer, nullable=False)
    content = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    receipt = relationship("GoodsReceipt", back_populates="files")


class ProcurementEmailLog(Base):
    """
    A record every time a PO or a defect notice leaves the system towards a
    vendor: emailed ("sent"), written to the server log because no email
    provider delivered it ("logged"), or printed / saved as PDF for hand
    delivery ("printed").
    """
    __tablename__ = "procurement_email_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    po_id = Column(UUID(as_uuid=True), ForeignKey("purchase_orders.id"), nullable=False)
    receipt_id = Column(UUID(as_uuid=True), ForeignKey("goods_receipts.id"), nullable=True)
    kind = Column(String, nullable=False)       # po / defect
    channel = Column(String, nullable=False)    # email / print
    to_email = Column(String, nullable=True)
    subject = Column(String, nullable=True)
    status = Column(String, nullable=False)     # sent / logged / printed
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PoPriceCorrection(Base):
    """One corrected unit price on a received purchase order. The original price is never lost: every correction
    keeps old price, new price, who, when and why (a received PO is amended with a trail, not silently edited)."""
    __tablename__ = "po_price_corrections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    po_id = Column(UUID(as_uuid=True), ForeignKey("purchase_orders.id"), nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    qty = Column(Integer, nullable=False)
    old_price = Column(Numeric(12, 2), nullable=False)
    new_price = Column(Numeric(12, 2), nullable=False)
    reason = Column(Text, nullable=False)
    corrected_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product")
    corrector = relationship("User", foreign_keys=[corrected_by])
