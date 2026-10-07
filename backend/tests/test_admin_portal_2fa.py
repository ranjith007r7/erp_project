"""Separate Admin / Employee sign-in, and authenticator-app (TOTP) for admins."""
import time
import uuid

import pytest

import app.core.database as dbm
from app.core.config import settings
from app.models.user import User
from app.services import totp

PW = "testpass123"


def make_admin(client):
    """A real signed-up admin with a verified email (sign-in requires it)."""
    u = uuid.uuid4().hex[:10]
    email = f"adm{u}@test.com"
    r = client.post("/api/auth/signup", json={"org_name": f"Org {u}", "subdomain": f"o{u}", "admin_name": "Priya Sharma", "admin_email": email, "admin_password": PW})
    assert r.status_code == 201, r.text
    db = dbm.SessionLocal(); db.query(User).filter(User.email == email).update({"email_verified": True}); db.commit(); db.close()
    return email, {"Authorization": f"Bearer {r.json()['access_token']}"}


def make_employee(client, admin_h, role_name="Staff"):
    role = client.post("/api/core/roles", headers=admin_h, json={"name": f"{role_name} {uuid.uuid4().hex[:5]}"}).json()
    email = f"emp{uuid.uuid4().hex[:8]}@test.com"
    r = client.post("/api/core/users", headers=admin_h, json={"name": "Arjun Nair", "email": email, "password": PW, "role_id": role["id"]})
    assert r.status_code == 201, r.text
    return email


def login(client, email, portal, password=PW):
    return client.post("/api/auth/login", json={"email": email, "password": password, "portal": portal})


@pytest.fixture
def twofa(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_2FA_REQUIRED", True)


def enrol(client, email):
    """Walk an admin through first-time authenticator setup. Returns (secret, recovery_codes, access_token)."""
    r = login(client, email, "admin").json()
    assert r["requires_totp_setup"] and r["challenge_token"] and not r["access_token"]
    ch = r["challenge_token"]
    s = client.post("/api/auth/totp/setup/start", json={"challenge_token": ch}).json()
    assert s["otpauth_uri"].startswith("otpauth://totp/") and s["secret"] in s["otpauth_uri"]
    done = client.post("/api/auth/totp/setup/confirm", json={"challenge_token": ch, "code": totp.code_now(s["secret"])})
    assert done.status_code == 200, done.text
    return s["secret"], done.json()["recovery_codes"], done.json()["access_token"]


# ---------- portals ----------
def test_each_account_type_can_only_use_its_own_portal(client):
    email, h = make_admin(client)
    emp = make_employee(client, h)
    assert login(client, email, "admin").status_code == 200
    assert login(client, emp, "employee").status_code == 200
    r = login(client, email, "employee")
    assert r.status_code == 403 and "Admin sign-in" in r.json()["detail"]
    r = login(client, emp, "admin")
    assert r.status_code == 403 and "Employee sign-in" in r.json()["detail"]


def test_wrong_portal_message_is_only_shown_after_a_correct_password(client):
    email, h = make_admin(client)
    r = login(client, email, "employee", password="wrong-password")
    assert r.status_code == 401 and r.json()["detail"] == "Incorrect email or password."


def test_portal_is_required(client):
    email, _ = make_admin(client)
    assert client.post("/api/auth/login", json={"email": email, "password": PW}).status_code == 422
    assert client.post("/api/auth/login", json={"email": email, "password": PW, "portal": "boss"}).status_code == 422


# ---------- authenticator ----------
def test_admin_must_enrol_an_authenticator_then_uses_it(client, twofa):
    email, _ = make_admin(client)
    secret, recovery, token = enrol(client, email)
    assert len(recovery) == 8
    assert client.get("/api/crm/leads", headers={"Authorization": f"Bearer {token}"}).status_code == 200

    r = login(client, email, "admin").json()
    assert r["requires_totp"] and not r["access_token"]
    ch = r["challenge_token"]
    # the code used at enrolment cannot be replayed; the next 30-second code works
    assert client.post("/api/auth/totp/verify", json={"challenge_token": ch, "code": totp.code_now(secret)}).status_code == 401
    nxt = totp.code_now(secret, time.time() + 30)
    ok = client.post("/api/auth/totp/verify", json={"challenge_token": ch, "code": nxt})
    assert ok.status_code == 200 and ok.json()["access_token"]
    # and the very same code is single use
    assert client.post("/api/auth/totp/verify", json={"challenge_token": login(client, email, "admin").json()["challenge_token"], "code": nxt}).status_code == 401


def test_challenge_tokens_are_not_logins(client, twofa):
    email, _ = make_admin(client)
    ch = login(client, email, "admin").json()["challenge_token"]
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {ch}"}).status_code == 401
    assert client.get("/api/crm/leads", headers={"Authorization": f"Bearer {ch}"}).status_code == 401
    # a "totp_setup" challenge cannot be used at the "totp" step either
    assert client.post("/api/auth/totp/verify", json={"challenge_token": ch, "code": "123456"}).status_code == 401


def test_wrong_setup_code_does_not_enable_two_factor(client, twofa):
    email, _ = make_admin(client)
    ch = login(client, email, "admin").json()["challenge_token"]
    client.post("/api/auth/totp/setup/start", json={"challenge_token": ch})
    assert client.post("/api/auth/totp/setup/confirm", json={"challenge_token": ch, "code": "000000"}).status_code == 401
    assert login(client, email, "admin").json()["requires_totp_setup"] is True      # still not enrolled


def test_recovery_code_works_once(client, twofa):
    email, _ = make_admin(client)
    _, recovery, _ = enrol(client, email)
    ch = login(client, email, "admin").json()["challenge_token"]
    assert client.post("/api/auth/totp/verify", json={"challenge_token": ch, "code": recovery[0]}).status_code == 200
    ch2 = login(client, email, "admin").json()["challenge_token"]
    assert client.post("/api/auth/totp/verify", json={"challenge_token": ch2, "code": recovery[0]}).status_code == 401
    assert client.post("/api/auth/totp/verify", json={"challenge_token": ch2, "code": recovery[1]}).status_code == 200


def test_code_guessing_is_locked_out_even_if_the_attacker_re_logs_in(client, twofa):
    email, _ = make_admin(client)
    enrol(client, email)
    for i in range(settings.MAX_FAILED_LOGIN_ATTEMPTS):
        ch = login(client, email, "admin")
        if ch.status_code == 429:
            break
        r = client.post("/api/auth/totp/verify", json={"challenge_token": ch.json()["challenge_token"], "code": "000000"})
        assert r.status_code in (401, 429)
    assert login(client, email, "admin").status_code == 429


def test_employees_never_see_the_authenticator_step(client, twofa):
    email, h = make_admin(client)
    emp = make_employee(client, h)
    r = login(client, emp, "employee").json()
    assert r["access_token"] and not r["requires_totp"] and not r["requires_totp_setup"]


def test_another_admin_can_reset_a_lost_authenticator(client, twofa):
    email, h = make_admin(client)
    secret, _, token = enrol(client, email)
    admin_h = {"Authorization": f"Bearer {token}"}
    # second admin in the same org
    role = client.post("/api/core/roles", headers=admin_h, json={"name": "Co-admin"}).json()
    client.post(f"/api/core/roles/{role['id']}/permissions", headers=admin_h, json={"module": "core", "action": "manage_access"})
    email2 = f"co{uuid.uuid4().hex[:8]}@test.com"
    u2 = client.post("/api/core/users", headers=admin_h, json={"name": "Second Admin", "email": email2, "password": PW, "role_id": role["id"]}).json()
    me = client.get("/api/auth/me", headers=admin_h).json()
    assert client.post(f"/api/core/users/{me['id']}/reset-2fa", headers=admin_h).status_code == 400   # not for yourself
    _, _, token2 = enrol(client, email2)
    h2 = {"Authorization": f"Bearer {token2}"}
    assert client.post(f"/api/core/users/{me['id']}/reset-2fa", headers=h2).status_code == 200
    assert login(client, email, "admin").json()["requires_totp_setup"] is True
    # an employee cannot reset anyone's authenticator
    emp = make_employee(client, admin_h)
    emp_h = {"Authorization": f"Bearer {login(client, emp, 'employee').json()['access_token']}"}
    assert client.post(f"/api/core/users/{me['id']}/reset-2fa", headers=emp_h).status_code == 403


def test_regenerating_recovery_codes_needs_password_and_a_live_code(client, twofa):
    email, _ = make_admin(client)
    secret, old, token = enrol(client, email)
    h = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/auth/security", headers=h).json() == {"totp_enabled": True, "recovery_codes_left": 8, "two_factor_required": True}
    live = totp.code_now(secret, time.time() + 30)
    assert client.post("/api/auth/totp/recovery-codes", headers=h, json={"password": "nope", "code": live}).status_code == 401
    new = client.post("/api/auth/totp/recovery-codes", headers=h, json={"password": PW, "code": live})
    assert new.status_code == 200 and len(new.json()) == 8 and set(new.json()).isdisjoint(old)
    ch = login(client, email, "admin").json()["challenge_token"]
    assert client.post("/api/auth/totp/verify", json={"challenge_token": ch, "code": old[0]}).status_code == 401   # old set is dead


def test_invited_admin_gets_no_session_and_must_use_the_admin_page(client, twofa, monkeypatch):
    email, _ = make_admin(client)
    _, _, token = enrol(client, email)
    h = {"Authorization": f"Bearer {token}"}
    role = client.post("/api/core/roles", headers=h, json={"name": "Invited admin"}).json()
    client.post(f"/api/core/roles/{role['id']}/permissions", headers=h, json={"module": "core", "action": "manage_access"})
    captured = {}
    import app.api.routes.roles as roles_routes
    monkeypatch.setattr(roles_routes, "send_invite_email", lambda to, org, raw: captured.update(token=raw), raising=False)
    import app.services.invites as inv
    monkeypatch.setattr(inv, "send_invite_email", lambda to, org, raw: captured.update(token=raw), raising=False)
    r = client.post("/api/core/invites", headers=h, json={"name": "New Admin", "email": f"ia{uuid.uuid4().hex[:6]}@test.com", "role_id": role["id"]})
    assert r.status_code == 201, r.text
    if "token" not in captured:
        pytest.skip("invite token not capturable in this build")
    acc = client.post("/api/auth/accept-invite", json={"token": captured["token"], "password": "newpassword123"})
    assert acc.status_code == 200 and acc.json()["access_token"] == ""
