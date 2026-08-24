import uuid

from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class Role(Base):
    """
    A named bucket of permissions within one organization, e.g. 'Admin',
    'Accountant', 'Sales Executive'. Each organization defines its own roles —
    Role is per-org, not shared globally, since different clients want
    different role names/structures (this IS the "customizable" part).
    """
    __tablename__ = "roles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    name = Column(String, nullable=False)

    permissions = relationship("Permission", back_populates="role")


class Permission(Base):
    """
    One specific allowed action for a role, e.g. (module="sales", action="create_invoice").
    Keeping this granular (module + action) rather than one big flag per role
    is what lets a client fine-tune access without you writing new code.
    """
    __tablename__ = "permissions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False)
    module = Column(String, nullable=False)   # e.g. "sales", "hr", "finance"
    action = Column(String, nullable=False)   # e.g. "view", "create", "edit", "delete", "approve"

    role = relationship("Role", back_populates="permissions")
