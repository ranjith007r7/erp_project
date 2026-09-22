import uuid
from datetime import datetime

from sqlalchemy import Column, String, ForeignKey, DateTime, Boolean, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class CustomField(Base):
    """
    THE customization engine. This is what lets a client add their own
    extra field to a module (e.g. "Batch Number" on Inventory for a
    manufacturing client) without you ever touching the database schema
    or writing new code for that specific client.

    field_type controls what kind of input the frontend renders for it —
    "text", "number", "date", "dropdown". entity_type is the specific
    record type this field attaches to within that module (e.g. module
    "inventory", entity_type "product") — kept separate from module so a
    module with several record types (Sales has Customer AND Quotation,
    say) can eventually offer fields scoped to just one of them.

    options holds the choice list for "dropdown" fields, comma-separated
    (e.g. "Small,Medium,Large") — plain text is enough here; this isn't
    trying to be a full form-builder, just enough to prove the mechanism.

    is_active lets an admin retire a field without deleting it and
    orphaning any CustomFieldValue rows that already reference it.
    """
    __tablename__ = "custom_fields"
    __table_args__ = (
        UniqueConstraint("org_id", "entity_type", "field_name", name="uq_custom_field_org_entity_name"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    module = Column(String, nullable=False)        # e.g. "inventory", "crm"
    entity_type = Column(String, nullable=False)    # e.g. "product", "lead", "customer"
    field_name = Column(String, nullable=False)     # e.g. "Batch Number"
    field_type = Column(String, nullable=False)     # "text" | "number" | "date" | "dropdown"
    options = Column(String, nullable=True)          # comma-separated, only used for "dropdown"
    is_required = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    display_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    values = relationship("CustomFieldValue", back_populates="field", cascade="all, delete-orphan")


class CustomFieldValue(Base):
    """
    ONE saved value of ONE custom field on ONE real record. Deliberately
    its own table with entity_type/entity_id, the exact same polymorphic-
    attachment pattern Phase 7's ApprovalRequest and the Documents module
    already use (rather than a JSON blob column bolted onto Product/Lead/
    Customer themselves). This is what keeps the mechanism generic: the
    same read/write code works for CRM, Sales, and Inventory, and adding
    a 4th module later needs zero schema changes here.

    value is stored as plain text regardless of field_type — the field
    definition's field_type is what tells the frontend how to render and
    validate it, not the storage layer. Keeping storage untyped is what
    lets one CustomFieldValue table serve every field_type without a
    separate nullable column per type.
    """
    __tablename__ = "custom_field_values"
    __table_args__ = (
        UniqueConstraint("custom_field_id", "entity_id", name="uq_custom_field_value_field_entity"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    custom_field_id = Column(UUID(as_uuid=True), ForeignKey("custom_fields.id"), nullable=False)
    entity_type = Column(String, nullable=False)
    entity_id = Column(UUID(as_uuid=True), nullable=False)
    value = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    field = relationship("CustomField", back_populates="values")
