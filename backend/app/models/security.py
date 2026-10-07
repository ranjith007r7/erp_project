"""Tables that support sign-up protection and the organization reset / delete confirmation."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, ForeignKey, DateTime, Integer
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


def _now():
    return datetime.now(timezone.utc)


class SignupAttempt(Base):
    """One row per sign-up request, so the per-IP and per-day limits survive restarts and work across instances."""
    __tablename__ = "signup_attempts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ip = Column(String, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now, index=True)


class OrgActionCode(Base):
    """
    A single-use emailed confirmation code for a dangerous organization action
    ('reset' or 'delete'). Only a hash of the code is stored. Bound to the
    requesting user and the purpose, so a reset code cannot confirm a delete.
    """
    __tablename__ = "org_action_codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    purpose = Column(String, nullable=False)           # reset | delete
    code_hash = Column(String, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
