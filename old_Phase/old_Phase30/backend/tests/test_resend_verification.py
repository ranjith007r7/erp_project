"""
Locks in the resend-verification fix as a permanent regression test — the
real gap found while thinking through an edge case: a user whose
original verification link expired, landed in spam, or was never
clicked had no self-service way back in before this existed.
"""
from datetime import datetime, timedelta, timezone


def test_resend_verification_issues_a_genuinely_different_token(client, signup):
    """The core mechanism: a fresh token must actually replace the old one, not just re-log it."""
    from app.core.database import SessionLocal
    from app.models.user import User

    admin = signup()
    me = client.get("/api/auth/me", headers=admin).json()

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == me["id"]).first()
        old_hash = user.verification_token_hash
        assert old_hash is not None
        # Backdate the cooldown so this test can exercise resend without
        # waiting a real 60 seconds - same technique used throughout
        # this project's own security tests.
        user.last_verification_email_sent_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        db.commit()
    finally:
        db.close()

    resp = client.post("/api/auth/resend-verification", json={"email": me["email"]})
    assert resp.status_code == 200

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == me["id"]).first()
        new_hash = user.verification_token_hash
        assert new_hash != old_hash, "resend must issue a genuinely different token, not reuse the old one"
    finally:
        db.close()


def test_old_token_is_invalidated_after_a_resend(client, signup):
    """A stale link a user might still have open in another tab must stop working once a fresh one is issued."""
    import re
    from app.core.database import SessionLocal
    from app.models.user import User
    from app.core.security import hash_token
    import secrets

    admin = signup()
    me = client.get("/api/auth/me", headers=admin).json()

    # Simulate holding the original raw token (same technique as
    # test_security_hardening.py's password-reset tests - we can't
    # recover the real raw token from its hash, so issue a known one
    # directly and set the cooldown as already past.
    original_raw_token = secrets.token_urlsafe(32)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == me["id"]).first()
        user.verification_token_hash = hash_token(original_raw_token)
        user.verification_token_expires = datetime.now(timezone.utc) + timedelta(hours=24)
        user.last_verification_email_sent_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        db.commit()
    finally:
        db.close()

    client.post("/api/auth/resend-verification", json={"email": me["email"]})

    old_link_resp = client.post("/api/auth/verify-email", json={"token": original_raw_token})
    assert old_link_resp.status_code == 400, "the old token must be dead after a resend issued a new one"


def test_resend_verification_is_rate_limited(client, signup):
    """Rapid repeat requests must not each trigger a real send - protects the Resend free-tier quota."""
    from app.core.database import SessionLocal
    from app.models.user import User

    admin = signup()
    me = client.get("/api/auth/me", headers=admin).json()

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == me["id"]).first()
        token_before = user.verification_token_hash
    finally:
        db.close()

    # Immediately request a resend - well within the cooldown window
    # (signup itself just set last_verification_email_sent_at seconds ago).
    resp = client.post("/api/auth/resend-verification", json={"email": me["email"]})
    assert resp.status_code == 200  # still the generic success message, not an error

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == me["id"]).first()
        token_after = user.verification_token_hash
        assert token_after == token_before, "a request within the cooldown window must NOT issue a new token"
    finally:
        db.close()


def test_resend_verification_does_not_leak_account_existence_or_status(client, signup):
    """Same anti-enumeration discipline as forgot-password: three different real states, one identical response."""
    admin = signup()
    me = client.get("/api/auth/me", headers=admin).json()

    # A real, still-unverified email.
    pending_resp = client.post("/api/auth/resend-verification", json={"email": me["email"]})

    # An email that has never existed.
    nonexistent_resp = client.post("/api/auth/resend-verification", json={
        "email": "never-existed-xyz@nonexistent-domain-abc123.com",
    })

    assert pending_resp.status_code == nonexistent_resp.status_code == 200
    assert pending_resp.json() == nonexistent_resp.json()


def test_resend_verification_does_not_leak_already_verified_status(client, signup):
    from app.core.database import SessionLocal
    from app.models.user import User

    admin = signup()
    me = client.get("/api/auth/me", headers=admin).json()

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == me["id"]).first()
        user.email_verified = True
        user.verification_token_hash = None
        db.commit()
    finally:
        db.close()

    resp = client.post("/api/auth/resend-verification", json={"email": me["email"]})
    assert resp.status_code == 200
    assert "sent" in resp.json()["message"].lower()

    # Confirm no token was actually issued for an already-verified account.
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == me["id"]).first()
        assert user.verification_token_hash is None
    finally:
        db.close()
