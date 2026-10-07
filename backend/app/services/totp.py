"""
Authenticator-app sign-in (RFC 6238 TOTP: 6 digits, 30 seconds, SHA-1), which is
what Microsoft Authenticator, Google Authenticator, Authy and 1Password all speak.
Written against the RFC with the standard library, so there is no extra dependency.

Secrets are encrypted at rest (Fernet) with TOTP_ENCRYPTION_KEY, or a key derived
from JWT_SECRET_KEY when that is not set. Rotating the key makes stored secrets
unreadable; affected admins then need a 2FA reset.
"""
import base64
import hashlib
import hmac
import json
import secrets
import struct
import time
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

STEP = 30
DIGITS = 6
RECOVERY_CODE_COUNT = 8


def _fernet() -> Fernet:
    raw = settings.TOTP_ENCRYPTION_KEY or settings.JWT_SECRET_KEY
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("totp:" + raw).encode()).digest()))


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def _code_for(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** DIGITS)
    return str(value).zfill(DIGITS)


def current_step(now: float | None = None) -> int:
    return int((now if now is not None else time.time()) // STEP)


def code_now(secret: str, now: float | None = None) -> str:
    return _code_for(secret, current_step(now))


def verify_code(secret: str, code: str, last_step: int | None = None, now: float | None = None, window: int = 1) -> int | None:
    """Return the matched time step (to store as last_step) or None. Accepts +/- `window` steps of clock drift; a step already used is refused."""
    code = (code or "").strip().replace(" ", "")
    if not (code.isdigit() and len(code) == DIGITS):
        return None
    step = current_step(now)
    for s in range(step - window, step + window + 1):
        if last_step is not None and s <= last_step:
            continue
        if hmac.compare_digest(_code_for(secret, s), code):
            return s
    return None


def provisioning_uri(secret: str, email: str) -> str:
    issuer = settings.TOTP_ISSUER
    return f"otpauth://totp/{quote(issuer)}:{quote(email)}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={STEP}"


# ---------------- recovery codes ----------------
def _norm(code: str) -> str:
    return (code or "").strip().lower().replace("-", "").replace(" ", "")


def _hash(code: str) -> str:
    return hashlib.sha256(_norm(code).encode()).hexdigest()


def generate_recovery_codes() -> tuple[list[str], str]:
    """Returns (codes to show once, JSON of hashes to store)."""
    codes = [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}" for _ in range(RECOVERY_CODE_COUNT)]
    return codes, json.dumps([_hash(c) for c in codes])


def consume_recovery_code(stored_json: str | None, code: str) -> str | None:
    """If `code` is an unused recovery code, return the new stored JSON without it; otherwise None."""
    if not stored_json:
        return None
    try:
        hashes = json.loads(stored_json)
    except ValueError:
        return None
    h = _hash(code)
    for i, existing in enumerate(hashes):
        if hmac.compare_digest(existing, h):
            return json.dumps(hashes[:i] + hashes[i + 1:])
    return None


def recovery_codes_left(stored_json: str | None) -> int:
    try:
        return len(json.loads(stored_json)) if stored_json else 0
    except ValueError:
        return 0
