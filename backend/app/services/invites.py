"""
Creating an invited (no-password-yet) login and emailing the invite link.
Shared by Settings > Users (roles.py) and HR "create login for this employee",
so both create identical accounts the same way.
"""
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password, generate_one_time_token
from app.models.user import User
from app.services.email import send_invite_email


def issue_invite_token(db: Session, user: User, org_name: str) -> None:
    """Overwriting invite_token_hash kills any earlier link, so a resend never leaves two valid ones."""
    raw_token, token_hash = generate_one_time_token()
    user.invite_token_hash = token_hash
    user.invite_token_expires = datetime.now(timezone.utc) + timedelta(hours=settings.INVITE_TOKEN_EXPIRE_HOURS)
    user.last_invite_email_sent_at = datetime.now(timezone.utc)
    send_invite_email(user.email, org_name, raw_token)


def create_invited_user(db: Session, org_id, org_name: str, name: str, email: str, role_id) -> User:
    user = User(
        org_id=org_id, name=name, email=email,
        # An unguessable placeholder, not a usable password (see the User model docstring).
        password_hash=hash_password(secrets.token_urlsafe(32)),
        role_id=role_id, status="invited",
    )
    db.add(user)
    db.flush()  # user needs a real id before the token is issued
    issue_invite_token(db, user, org_name)
    return user
