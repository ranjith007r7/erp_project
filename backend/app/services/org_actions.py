"""Emailed one-time codes that confirm a reset or permanent delete of an organization."""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.security import OrgActionCode
from app.models.user import User
from app.services.email import send_email

PURPOSES = {"reset": "reset all data in", "delete": "permanently delete"}


def _hash(code: str, user: User, purpose: str) -> str:
    return hashlib.sha256(f"{user.id}:{purpose}:{code}".encode()).hexdigest()


def _aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def mask_email(email: str) -> str:
    name, _, domain = email.partition("@")
    return (name[:2] + "***" if len(name) > 2 else name[:1] + "***") + "@" + domain


def issue_code(db: Session, user: User, org_name: str, purpose: str) -> None:
    now = datetime.now(timezone.utc)
    last = (db.query(OrgActionCode).filter(OrgActionCode.user_id == user.id, OrgActionCode.purpose == purpose)
            .order_by(OrgActionCode.created_at.desc()).first())
    if last and (now - _aware(last.created_at)).total_seconds() < settings.ORG_ACTION_RESEND_SECONDS:
        raise HTTPException(429, f"Please wait {settings.ORG_ACTION_RESEND_SECONDS} seconds before asking for another code.")
    # one live code at a time
    db.query(OrgActionCode).filter(OrgActionCode.user_id == user.id, OrgActionCode.purpose == purpose,
                                   OrgActionCode.used_at.is_(None)).update({"used_at": now})
    code = f"{secrets.randbelow(1_000_000):06d}"
    db.add(OrgActionCode(org_id=user.org_id, user_id=user.id, purpose=purpose, code_hash=_hash(code, user, purpose),
                         expires_at=now + timedelta(minutes=settings.ORG_ACTION_CODE_MINUTES)))
    db.commit()
    send_email(
        user.email,
        f"Your confirmation code to {PURPOSES[purpose].split(' ')[0]} {org_name}",
        f"Someone (hopefully you) asked to {PURPOSES[purpose]} {org_name}.\n\n"
        f"Confirmation code: {code}\n\n"
        f"It expires in {settings.ORG_ACTION_CODE_MINUTES} minutes and works once. "
        f"If this was not you, do not share the code and change your password.",
    )


def consume_code(db: Session, user: User, purpose: str, code: str) -> None:
    """Raises unless `code` is the live, unused, unexpired code for this user and purpose. Marks it used on success."""
    now = datetime.now(timezone.utc)
    row = (db.query(OrgActionCode).filter(OrgActionCode.user_id == user.id, OrgActionCode.purpose == purpose,
                                          OrgActionCode.used_at.is_(None))
           .order_by(OrgActionCode.created_at.desc()).with_for_update().first())
    bad = HTTPException(400, "That confirmation code is not valid. Ask for a new code.")
    if not row or _aware(row.expires_at) < now or row.attempts >= settings.ORG_ACTION_MAX_ATTEMPTS:
        raise bad
    if not hmac.compare_digest(row.code_hash, _hash((code or "").strip(), user, purpose)):
        row.attempts += 1
        db.commit()
        raise HTTPException(400, "That confirmation code is not correct.")
    row.used_at = now
    db.flush()
