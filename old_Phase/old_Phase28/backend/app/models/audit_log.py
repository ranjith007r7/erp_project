import uuid
from datetime import datetime

from sqlalchemy import Column, String, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class AuditLog(Base):
    """
    A permanent, append-only record of 'who did what, to which record, when'.
    Every module will eventually write here on create/update/delete of
    anything sensitive (invoices, salaries, approvals). Never edited, only
    ever added to — that's what makes it trustworthy as an audit trail.
    """
    __tablename__ = "audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    action = Column(String, nullable=False)     # e.g. "create", "update", "delete"
    entity = Column(String, nullable=False)     # e.g. "Invoice", "Employee"
    entity_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")
