import uuid
from datetime import datetime

from sqlalchemy import Column, String, ForeignKey, DateTime, Boolean, Integer
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

    # --- Email verification (Phase 13) ---
    # Deliberately NOT enforced on login yet — there's no real email
    # provider wired up in this codebase (no SMTP/SendGrid/SES config
    # anywhere), so blocking login on an unverified email would lock out
    # every single existing user the moment this ships, with no way for
    # them to actually receive a verification link. The mechanism is
    # built and correct; flip it on once a real provider is connected.
    email_verified = Column(Boolean, nullable=False, default=False)
    verification_token_hash = Column(String, nullable=True)
    verification_token_expires = Column(DateTime, nullable=True)

    # --- Password reset (Phase 13) ---
    # Stores a HASH of the reset token, never the raw token — same
    # principle as password_hash. If the database ever leaked, raw
    # tokens would be directly usable to take over any account; hashed
    # tokens are not.
    reset_token_hash = Column(String, nullable=True)
    reset_token_expires = Column(DateTime, nullable=True)

    # --- Login rate limiting (Phase 13) ---
    failed_login_attempts = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime, nullable=True)

    role = relationship("Role")
