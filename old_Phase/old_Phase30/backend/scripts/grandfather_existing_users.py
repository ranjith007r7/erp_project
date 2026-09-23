"""
Run this ONCE, manually, before (or right after) deploying the email-
verification-enforcement change - and never again.

Why this exists: every account that already exists was created before
real email delivery existed (Phase 13 shipped with no provider
connected). None of them ever had a real, clickable verification link -
the verification email was only ever logged to the server console. If
login enforcement went live without this, every existing user - real
customers included - would be locked out immediately with no way to
receive the link that would let them back in.

This is deliberately a STANDALONE script, not an Alembic migration. It's
a one-time data correction for accounts that already exist, not a
recurring structural need the way Alembic migrations are - bundling it
into `alembic upgrade head` would mean it silently re-runs on every
future deploy forever, which is unnecessary and, worse, hides a
one-time action inside routine deploy machinery. Run it once, by hand,
see exactly what it did, done.

Usage:
    cd backend
    $env:DATABASE_URL = "..."          # PowerShell
    python scripts/grandfather_existing_users.py
"""
import os
import sys

from sqlalchemy import create_engine, text


def main():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: set DATABASE_URL first (same connection string you use for alembic).", file=sys.stderr)
        sys.exit(1)

    engine = create_engine(database_url)
    with engine.begin() as conn:
        before = conn.execute(text("SELECT count(*) FROM users WHERE email_verified = false")).scalar()
        print(f"Users currently NOT verified: {before}")

        if before == 0:
            print("Nothing to do - every user is already marked verified.")
            return

        result = conn.execute(text("UPDATE users SET email_verified = true WHERE email_verified = false"))
        print(f"Updated {result.rowcount} user(s) to email_verified = true.")

        after = conn.execute(text("SELECT count(*) FROM users WHERE email_verified = false")).scalar()
        print(f"Users still NOT verified afterward: {after} (should be 0)")
        assert after == 0, "Something's wrong - some users are still unverified after the update."

    print("\nDone. Every pre-existing account can now log in normally.")
    print("Accounts created from now on will need to click their real verification email.")


if __name__ == "__main__":
    main()
