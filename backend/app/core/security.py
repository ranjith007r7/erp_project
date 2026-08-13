"""
Two jobs live here, and nowhere else in the app:
1. Turning a plain-text password into an unreadable hash (and checking it back).
2. Creating and verifying the JWT "wristband" that proves someone is logged in.
3. (Phase 13) Generating and hashing one-time tokens for password reset /
   email verification links.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from jose import jwt, JWTError
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def generate_one_time_token() -> tuple[str, str]:
    """
    Returns (raw_token, hashed_token). The raw token goes in the emailed
    link and is NEVER stored; the hash goes in the database. This is
    deliberately a fast, unsalted SHA-256 hash rather than bcrypt —
    unlike a human-chosen password, this token is already 32 bytes of
    real randomness (secrets.token_urlsafe), so it doesn't need slow,
    salted hashing to resist brute-force; a fast deterministic hash is
    both correct here and lets lookup-by-token-hash use a plain equality
    query instead of checking every stored hash one by one.
    """
    raw_token = secrets.token_urlsafe(32)
    hashed = hashlib.sha256(raw_token.encode()).hexdigest()
    return raw_token, hashed


def hash_token(raw_token: str) -> str:
    """Same hashing as generate_one_time_token, exposed separately for verifying an incoming token."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


def create_access_token(data: dict) -> str:
    """
    'data' should contain at least {"sub": user_id, "org_id": ..., "role": ...}
    so that every future request can be scoped to the right tenant/org
    without a second database lookup.
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None
