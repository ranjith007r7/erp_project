"""
Locks in Phase 13's security hardening as permanent regression tests —
without these, a future change (e.g. someone "simplifying" the login
route) could silently remove rate limiting and nothing would catch it
until a real attacker did.
"""
from datetime import datetime, timedelta, timezone


def create_user_directly(client, signup_headers, email_prefix, password="testpass123"):
    """
    Uses the roles.py user-management endpoint from Phase 11 to create a
    second real login. email is always made unique via a uuid suffix,
    same discipline conftest.py's signup() fixture already uses - a
    fixed literal email string would collide on any second run against
    the same persistent test database (found by this test genuinely
    failing that way on a rerun, not by anticipating it in advance).
    """
    import uuid
    email = f"{email_prefix}-{uuid.uuid4().hex[:8]}@test.com"
    resp = client.post("/api/core/users", headers=signup_headers, json={
        "name": "Second User", "email": email, "password": password,
    })
    assert resp.status_code == 201, resp.text
    return email, password


def test_login_locks_out_after_max_failed_attempts(client, signup):
    admin = signup()
    email, password = create_user_directly(client, admin, "lockout-test")

    for _ in range(5):
        resp = client.post("/api/auth/login", json={"email": email, "password": "wrongpassword"})
        assert resp.status_code == 401

    # 6th attempt, even with the CORRECT password, must be blocked.
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 429, f"expected lockout, got {resp.status_code}: {resp.text}"


def test_lockout_clears_after_the_window_expires(client, signup):
    admin = signup()
    email, password = create_user_directly(client, admin, "lockout-expiry-test")

    for _ in range(5):
        client.post("/api/auth/login", json={"email": email, "password": "wrong"})

    # Confirm actually locked first.
    assert client.post("/api/auth/login", json={"email": email, "password": password}).status_code == 429

    # Directly expire the lockout window, same as a real 15 minutes passing.
    from app.core.database import SessionLocal
    from app.models.user import User

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        user.locked_until = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    finally:
        db.close()

    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, f"expected lockout to have cleared, got {resp.status_code}"


def test_successful_login_resets_failed_attempt_count(client, signup):
    """A user who mistypes their password twice then gets it right shouldn't be one step closer to lockout next time."""
    admin = signup()
    email, password = create_user_directly(client, admin, "reset-attempts-test")

    client.post("/api/auth/login", json={"email": email, "password": "wrong"})
    client.post("/api/auth/login", json={"email": email, "password": "wrong"})
    assert client.post("/api/auth/login", json={"email": email, "password": password}).status_code == 200

    from app.core.database import SessionLocal
    from app.models.user import User

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        assert user.failed_login_attempts == 0, "successful login must reset the failed-attempt counter"
    finally:
        db.close()


def test_password_reset_full_flow(client, signup):
    admin = signup()
    email, old_password = create_user_directly(client, admin, "reset-flow-test")

    forgot_resp = client.post("/api/auth/forgot-password", json={"email": email})
    assert forgot_resp.status_code == 200

    # Extract the real token the same way it would come from an email link,
    # since no real email provider is configured (see app/services/email.py).
    from app.core.database import SessionLocal
    from app.models.user import User
    from app.core.security import hash_token
    import secrets as secrets_module

    # We can't recover the RAW token from the hash (that's the point), so
    # generate one, hash it, and directly set it as if forgot-password had
    # just issued it - a faithful simulation of "click the emailed link"
    # without needing a real email provider in the test environment.
    raw_token = secrets_module.token_urlsafe(32)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        user.reset_token_hash = hash_token(raw_token)
        user.reset_token_expires = datetime.now(timezone.utc) + timedelta(minutes=60)
        db.commit()
    finally:
        db.close()

    new_password = "brandnewpassword456"
    reset_resp = client.post("/api/auth/reset-password", json={"token": raw_token, "new_password": new_password})
    assert reset_resp.status_code == 200, reset_resp.text

    assert client.post("/api/auth/login", json={"email": email, "password": old_password}).status_code == 401
    assert client.post("/api/auth/login", json={"email": email, "password": new_password}).status_code == 200

    # Single-use: the same token must not work a second time.
    reuse_resp = client.post("/api/auth/reset-password", json={"token": raw_token, "new_password": "yet-another-pw"})
    assert reuse_resp.status_code == 400


def test_forgot_password_does_not_leak_whether_email_exists(client):
    real_email_resp = client.post("/api/auth/forgot-password", json={"email": "definitely-not-registered@nonexistent-domain-xyz123.com"})
    assert real_email_resp.status_code == 200
    assert "sent" in real_email_resp.json()["message"].lower()


def test_expired_reset_token_is_rejected(client, signup):
    admin = signup()
    email, _ = create_user_directly(client, admin, "expired-token-test")

    from app.core.database import SessionLocal
    from app.models.user import User
    from app.core.security import hash_token
    import secrets as secrets_module

    raw_token = secrets_module.token_urlsafe(32)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        user.reset_token_hash = hash_token(raw_token)
        user.reset_token_expires = datetime.now(timezone.utc) - timedelta(minutes=1)  # already expired
        db.commit()
    finally:
        db.close()

    resp = client.post("/api/auth/reset-password", json={"token": raw_token, "new_password": "newpassword123"})
    assert resp.status_code == 400
