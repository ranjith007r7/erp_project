import uuid
from datetime import datetime, date

from sqlalchemy import (Column, String, ForeignKey, DateTime, Date, Numeric, Integer, Text, Boolean, LargeBinary,
                        UniqueConstraint)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class WarrantyRecord(Base):
    """
    One product line of a delivered work: the units sold, to be registered for warranty.

    Created automatically when a work is delivered (never typed). Its status:
      pending_details  -> an employee fills model / serial / manufacture month / expiry per unit, picks the period,
      pending_approval -> submitted; only a user holding warranty.approve decides,
      active           -> approved: end date and card number set, the printable card is available,
      no_warranty      -> the product is sold without warranty (with a reason),
      cancelled        -> the work was cancelled after delivery.
    The start date is the delivery date and is never editable.
    """
    __tablename__ = "warranty_records"
    __table_args__ = (UniqueConstraint("work_id", "product_id", name="uq_warranty_work_product"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    work_id = Column(UUID(as_uuid=True), ForeignKey("work_orders.id"), nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    qty = Column(Integer, nullable=False, default=1)
    amount = Column(Numeric(14, 2), nullable=False, default=0)          # this line's share of the work's taxable value (excl. GST)

    status = Column(String, nullable=False, default="pending_details", server_default="pending_details")
    warranty_months = Column(Integer, nullable=True)
    warranty_terms = Column(Text, nullable=True)
    start_date = Column(Date, nullable=False, default=date.today)       # = delivery date
    end_date = Column(Date, nullable=True)                              # set on approval: start + period
    card_number = Column(String, nullable=True)                         # "WC-0001", given on approval

    submitted_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)
    no_warranty_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    work = relationship("WorkOrder")
    product = relationship("Product")
    units = relationship("WarrantyUnit", back_populates="warranty", cascade="all, delete-orphan", order_by="WarrantyUnit.position")
    submitter = relationship("User", foreign_keys=[submitted_by])
    approver = relationship("User", foreign_keys=[approved_by])


class WarrantyUnit(Base):
    """One physical unit that was sold: its own model and serial number."""
    __tablename__ = "warranty_units"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    warranty_id = Column(UUID(as_uuid=True), ForeignKey("warranty_records.id"), nullable=False)
    position = Column(Integer, nullable=False, default=1)
    model_number = Column(String, nullable=True)
    serial_number = Column(String, nullable=True)
    manufacture_month = Column(Date, nullable=True)                     # the 1st of the month
    expiry_date = Column(Date, nullable=True)
    batch_id = Column(UUID(as_uuid=True), ForeignKey("stock_batches.id"), nullable=True)   # the lot this unit came from (vendor trace)

    warranty = relationship("WarrantyRecord", back_populates="units")
    batch = relationship("StockBatch")


class WarrantyClaim(Base):
    """A customer's claim against one unit under warranty. Filled by employees, decided by an approver."""
    __tablename__ = "warranty_claims"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    claim_number = Column(String, nullable=False)                       # "CL-0001"
    warranty_id = Column(UUID(as_uuid=True), ForeignKey("warranty_records.id"), nullable=False)
    unit_id = Column(UUID(as_uuid=True), ForeignKey("warranty_units.id"), nullable=False)
    issue = Column(Text, nullable=False)
    # open (being filled) -> pending_approval (all six documents attached) -> replaced / repaired / rejected
    status = Column(String, nullable=False, default="open", server_default="open")
    out_of_warranty = Column(Boolean, nullable=False, default=False, server_default="false")   # the end date had passed when it was raised
    resolution = Column(String, nullable=True)                          # replace / repair (chosen by the approver)
    decision_note = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    decided_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    decided_at = Column(DateTime, nullable=True)
    replacement_work_id = Column(UUID(as_uuid=True), ForeignKey("work_orders.id"), nullable=True)
    vendor_notice_at = Column(DateTime, nullable=True)
    vendor_notice_to = Column(String, nullable=True)
    vendor_notice_channel = Column(String, nullable=True)               # email / print
    created_at = Column(DateTime, default=datetime.utcnow)

    warranty = relationship("WarrantyRecord")
    unit = relationship("WarrantyUnit")
    files = relationship("WarrantyClaimFile", back_populates="claim", cascade="all, delete-orphan", order_by="WarrantyClaimFile.created_at")
    creator = relationship("User", foreign_keys=[created_by])
    decider = relationship("User", foreign_keys=[decided_by])
    replacement_work = relationship("WorkOrder", foreign_keys=[replacement_work_id])


class WarrantyClaimFile(Base):
    """customer_invoice / warranty_copy / model_photo / serial_photo / defect_image / supporting (bytes kept in the database)."""
    __tablename__ = "warranty_claim_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    claim_id = Column(UUID(as_uuid=True), ForeignKey("warranty_claims.id"), nullable=False)
    kind = Column(String, nullable=False)
    filename = Column(String, nullable=False)
    content_type = Column(String, nullable=False)
    size = Column(Integer, nullable=False)
    content = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    claim = relationship("WarrantyClaim", back_populates="files")
