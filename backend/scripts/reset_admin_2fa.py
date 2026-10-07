"""
Last-resort recovery for an admin who lost both their phone and their recovery codes
and has no other administrator to reset them: clears the authenticator so they can
enrol a new one at their next Admin sign-in. Needs shell access to the server, so only
the platform owner can run it.

Usage (from backend/):  python scripts/reset_admin_2fa.py someone@example.com
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal  # noqa: E402
from app.models.user import User  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Usage: python scripts/reset_admin_2fa.py <email>")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == sys.argv[1]).first()
        if not user:
            sys.exit("No user with that email.")
        user.totp_enabled = False
        user.totp_secret_enc = None
        user.totp_last_step = None
        user.recovery_codes_hash = None
        user.failed_login_attempts = 0
        user.locked_until = None
        db.commit()
        print(f"Authenticator cleared for {user.email}. They will set up a new one at their next Admin sign-in.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
