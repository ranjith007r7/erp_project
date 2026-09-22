"""
Locks in the invite-by-email flow as permanent regression tests.
"""
from datetime import datetime, timedelta, timezone


def test_invited_user_cannot_log_in_before_accepting(client, signup):
    admin = signup()
    client.post("/api/core/invites", headers=admin, json={"name": "Invitee", "email": "invitee1@test.com"})

    resp = client.post("/api/auth/login", json={"email": "invitee1@test.com", "password": "anything123"})
    assert resp.status_code == 403
    assert "activated" in resp.json()["detail"].lower()


def test_duplicate_invite_to_same_email_is_rejected(client, signup):
    admin = signup()
    client.post("/api/core/invites", headers=admin, json={"name": "Invitee", "email": "invitee2@test.com"})
    resp = client.post("/api/core/invites", headers=admin, json={"name": "Invitee Again", "email": "invitee2@test.com"})
    assert resp.status_code == 400


def test_accept_invite_full_flow(client, signup):
    from app.core.database import SessionLocal
    from app.models.user import User

    admin = signup()
    client.post("/api/core/invites", headers=admin, json={"name": "Invitee", "email": "invitee3@test.com"})

    # Recover the real raw token the same way test_security_hardening.py's
    # password-reset tests do - can't get it back from its hash, so
    # simulate "the invitee clicked the emailed link" by generating one
    # and setting it directly as if create_invite had just issued it.
    import secrets
    from app.core.security import hash_token

    raw_token = secrets.token_urlsafe(32)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "invitee3@test.com").first()
        user.invite_token_hash = hash_token(raw_token)
        user.invite_token_expires = datetime.now(timezone.utc) + timedelta(hours=168)
        db.commit()
    finally:
        db.close()

    resp = client.post("/api/auth/accept-invite", json={"token": raw_token, "password": "realpassword123"})
    assert resp.status_code == 200
    assert "access_token" in resp.json()

    # Confirm status flipped, email counts as verified, and a fresh
    # login with the chosen password now works.
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "invitee3@test.com").first()
        assert user.status == "active"
        assert user.email_verified is True
        assert user.invite_token_hash is None
    finally:
        db.close()

    login_resp = client.post("/api/auth/login", json={"email": "invitee3@test.com", "password": "realpassword123"})
    assert login_resp.status_code == 200


def test_invite_token_is_single_use(client, signup):
    from app.core.database import SessionLocal
    from app.models.user import User
    from app.core.security import hash_token
    import secrets

    admin = signup()
    client.post("/api/core/invites", headers=admin, json={"name": "Invitee", "email": "invitee4@test.com"})

    raw_token = secrets.token_urlsafe(32)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "invitee4@test.com").first()
        user.invite_token_hash = hash_token(raw_token)
        user.invite_token_expires = datetime.now(timezone.utc) + timedelta(hours=168)
        db.commit()
    finally:
        db.close()

    first = client.post("/api/auth/accept-invite", json={"token": raw_token, "password": "firstpassword123"})
    assert first.status_code == 200

    second = client.post("/api/auth/accept-invite", json={"token": raw_token, "password": "secondpassword456"})
    assert second.status_code == 400


def test_resend_invite_is_rate_limited_and_rotates_the_token(client, signup):
    from app.core.database import SessionLocal
    from app.models.user import User

    admin = signup()
    invite_resp = client.post("/api/core/invites", headers=admin, json={"name": "Invitee", "email": "invitee5@test.com"}).json()
    user_id = invite_resp["id"]

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        token_before = user.invite_token_hash
    finally:
        db.close()

    # Immediate resend - within cooldown, must be rejected.
    immediate = client.post(f"/api/core/invites/{user_id}/resend", headers=admin)
    assert immediate.status_code == 429

    # Backdate the cooldown to simulate real time passing.
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        user.last_invite_email_sent_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        db.commit()
    finally:
        db.close()

    later = client.post(f"/api/core/invites/{user_id}/resend", headers=admin)
    assert later.status_code == 200

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        token_after = user.invite_token_hash
        assert token_after != token_before, "resend must issue a genuinely different token"
    finally:
        db.close()


def test_expired_invite_token_is_rejected(client, signup):
    from app.core.database import SessionLocal
    from app.models.user import User
    from app.core.security import hash_token
    import secrets

    admin = signup()
    client.post("/api/core/invites", headers=admin, json={"name": "Invitee", "email": "invitee6@test.com"})

    raw_token = secrets.token_urlsafe(32)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "invitee6@test.com").first()
        user.invite_token_hash = hash_token(raw_token)
        user.invite_token_expires = datetime.now(timezone.utc) - timedelta(hours=1)  # already expired
        db.commit()
    finally:
        db.close()

    resp = client.post("/api/auth/accept-invite", json={"token": raw_token, "password": "somepassword123"})
    assert resp.status_code == 400


def test_creating_an_invite_requires_manage_access(client, signup):
    """Same gate as everything else in this security model - core.create alone must not be enough."""
    admin = signup()
    role = client.post("/api/core/roles", headers=admin, json={"name": "Create Only"}).json()
    client.post(f"/api/core/roles/{role['id']}/permissions", headers=admin, json={"module": "core", "action": "create"})

    import uuid
    email = f"restricted-{uuid.uuid4().hex[:8]}@test.com"
    client.post("/api/core/users", headers=admin, json={
        "name": "Restricted", "email": email, "password": "testpass123", "role_id": role["id"],
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "testpass123"}).json()
    restricted = {"Authorization": f"Bearer {login['access_token']}"}

    resp = client.post("/api/core/invites", headers=restricted, json={"name": "Sneaky Invite", "email": "sneaky@test.com"})
    assert resp.status_code == 403
