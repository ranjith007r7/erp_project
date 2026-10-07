"""
Keeps strangers from creating organizations in bulk.

Layers, cheapest first:
  1. Optional access code (SIGNUP_ACCESS_CODE): when set, only people you gave it to can sign up.
  2. Per-IP limit per hour and a global daily limit, stored in the database so they survive restarts.
  3. Email verification before a new organization can use the API (see api/deps.py).
  4. scripts/purge_unverified_orgs.py removes organizations nobody verified.
"""
import hmac
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.security import SignupAttempt


def client_ip(request: Request) -> str:
    """The caller's address. Behind N trusted proxies the real client is the Nth entry from the right of X-Forwarded-For (a client can forge entries on the left, never the one our own proxy appended)."""
    hops = settings.TRUSTED_PROXY_HOPS
    if hops > 0:
        parts = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
        if len(parts) >= hops:
            return parts[-hops]
    return request.client.host if request.client else "unknown"


def access_code_required() -> bool:
    return bool(settings.SIGNUP_ACCESS_CODE.strip())


def check_signup_allowed(db: Session, request: Request, access_code: str | None) -> None:
    if access_code_required():
        given = (access_code or "").strip()
        if not hmac.compare_digest(given.encode(), settings.SIGNUP_ACCESS_CODE.strip().encode()):
            raise HTTPException(403, "A valid access code is required to create an organization. Ask the person who shared this link.")

    now = datetime.now(timezone.utc)
    ip = client_ip(request)
    per_ip = db.query(func.count(SignupAttempt.id)).filter(SignupAttempt.ip == ip, SignupAttempt.created_at > now - timedelta(hours=1)).scalar() or 0
    if per_ip >= settings.SIGNUP_MAX_PER_IP_PER_HOUR:
        raise HTTPException(429, "Too many sign-ups from this network. Please try again later.")
    per_day = db.query(func.count(SignupAttempt.id)).filter(SignupAttempt.created_at > now - timedelta(hours=24)).scalar() or 0
    if per_day >= settings.SIGNUP_MAX_PER_DAY:
        raise HTTPException(429, "Sign-ups are temporarily paused. Please try again tomorrow.")

    db.add(SignupAttempt(ip=ip))
    db.commit()  # counted even if the rest of the sign-up fails, so probing is limited too
    # housekeeping: forget attempts older than 2 days
    db.query(SignupAttempt).filter(SignupAttempt.created_at < now - timedelta(days=2)).delete()
    db.commit()
