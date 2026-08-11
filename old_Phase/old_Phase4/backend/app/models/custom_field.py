import uuid

from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class CustomField(Base):
    """
    THE customization engine. This is what lets a client add their own
    extra field to a module (e.g. "Batch Number" on Inventory for a
    manufacturing client) without you ever touching the database schema
    or writing new code for that specific client.

    field_type controls what kind of input the frontend renders for it —
    e.g. "text", "number", "date", "dropdown".
    """
    __tablename__ = "custom_fields"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    module = Column(String, nullable=False)       # e.g. "inventory", "crm"
    field_name = Column(String, nullable=False)    # e.g. "Batch Number"
    field_type = Column(String, nullable=False)    # e.g. "text", "number", "date", "dropdown"
