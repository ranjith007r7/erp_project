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
    status = Column(String, default="active")  # active / disabled / invited
    created_at = Column(DateTime, default=datetime.utcnow)

    # --- Email verification ---
    # Enforced at login since real email delivery was connected (see
    # MANUAL.md's "Real Email Delivery" entry) - was deliberately NOT
    # enforced in Phase 13, when this comment used to explain why.
    email_verified = Column(Boolean, nullable=False, default=False)
    verification_token_hash = Column(String, nullable=True)
    verification_token_expires = Column(DateTime, nullable=True)
    # Cooldown for the resend-verification endpoint - prevents a user
    # (or anyone spamming an arbitrary email into that endpoint) from
    # triggering unlimited real sends and burning through Resend's
    # 100/day free-tier quota. See the resend_verification route in
    # app/api/routes/auth.py.
    last_verification_email_sent_at = Column(DateTime, nullable=True)

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

    # --- Invite-by-email ---
    # An invited user's password_hash is set to a hash of a random,
    # unguessable placeholder at invite time - NOT left null. This
    # avoids loosening password_hash's existing NOT NULL constraint
    # (a schema change with its own risk, given this project's recent
    # migration history) while still being cryptographically impossible
    # to log in with until accept-invite sets a real password. status
    # is "invited" until accept-invite flips it to "active" - a real
    # invited row is otherwise a normal User row in every other respect.
    invite_token_hash = Column(String, nullable=True)
    invite_token_expires = Column(DateTime, nullable=True)
    # Separate from last_verification_email_sent_at on purpose - an
    # invited user never goes through the separate email-verification
    # flow at all (accepting the invite IS the verification, since
    # clicking a real emailed link already proves inbox ownership), so
    # conflating the two cooldowns would be tracking unrelated things
    # under one column.
    last_invite_email_sent_at = Column(DateTime, nullable=True)

    role = relationship("Role")
