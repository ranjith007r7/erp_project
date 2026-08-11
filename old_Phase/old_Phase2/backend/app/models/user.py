import uuid
from datetime import datetime

from sqlalchemy import Column, String, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class User(Base):
    """
    Every human who logs in — regardless of whether they end up being used
    as a Competitor-equivalent (Employee/Customer contact) elsewhere.
    Always scoped to exactly one organization via org_id.
    """
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id"), nullable=True)
    status = Column(String, default="active")  # active / disabled
    created_at = Column(DateTime, default=datetime.utcnow)

    role = relationship("Role")
