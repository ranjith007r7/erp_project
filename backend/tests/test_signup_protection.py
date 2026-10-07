"""Anti-spam: access code, per-IP and daily limits, verified-email gate, purge script."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
import app.core.database as dbm
from app.models.organization import Organization
from app.models.security import SignupAttempt
from app.models.user import User


def body(code=None):
    u = uuid.uuid4().hex[:10]
    d = {"org_name": f"Spam {u}", "subdomain": f"sp{u}", "admin_name": "Spammer", "admin_email": f"sp{u}@test.com", "admin_password": "testpass123"}
    if code is not None:
        d["access_code"] = code
    return d


@pytest.fixture
def strict(monkeypatch):
    def _set(**kw):
        for k, v in kw.items():
            monkeypatch.setattr(settings, k, v)
    yield _set
    db = dbm.SessionLocal(); db.query(SignupAttempt).delete(); db.commit(); db.close()


def test_access_code_required_when_configured(client, strict):
    strict(SIGNUP_ACCESS_CODE="demo-2026")
    assert client.get("/api/auth/signup-config").json() == {"access_code_required": True}
    assert client.post("/api/auth/signup", json=body()).status_code == 403
    assert client.post("/api/auth/signup", json=body("wrong")).status_code == 403
    r = client.post("/api/auth/signup", json=body("demo-2026"))
    assert r.status_code == 201, r.text


def test_open_signup_reports_no_code_needed(client, strict):
    strict(SIGNUP_ACCESS_CODE="")
    assert client.get("/api/auth/signup-config").json() == {"access_code_required": False}


def test_per_ip_limit_uses_the_proxy_address_not_a_forged_one(client, strict):
    strict(SIGNUP_MAX_PER_IP_PER_HOUR=2, TRUSTED_PROXY_HOPS=1)
    h = {"X-Forwarded-For": "6.6.6.6, 203.0.113.9"}      # the left entry is forged; our proxy appended the right one
    assert client.post("/api/auth/signup", json=body(), headers=h).status_code == 201
    assert client.post("/api/auth/signup", json=body(), headers=h).status_code == 201
    r = client.post("/api/auth/signup", json=body(), headers=h)
    assert r.status_code == 429
    # forging a different left-hand address does not help
    assert client.post("/api/auth/signup", json=body(), headers={"X-Forwarded-For": "7.7.7.7, 203.0.113.9"}).status_code == 429
    # a different real client is unaffected
    assert client.post("/api/auth/signup", json=body(), headers={"X-Forwarded-For": "1.1.1.1, 198.51.100.4"}).status_code == 201


def test_global_daily_cap(client, strict):
    strict(SIGNUP_MAX_PER_DAY=1, SIGNUP_MAX_PER_IP_PER_HOUR=100)
    assert client.post("/api/auth/signup", json=body(), headers={"X-Forwarded-For": "10.0.0.1"}).status_code == 201
    assert client.post("/api/auth/signup", json=body(), headers={"X-Forwarded-For": "10.0.0.2"}).status_code == 429


def test_unverified_organization_cannot_use_the_api_until_verified(client, strict, monkeypatch):
    strict(REQUIRE_VERIFIED_EMAIL_FOR_API=True, SIGNUP_MAX_PER_IP_PER_HOUR=100)
    sent = {}
    import app.api.routes.auth as auth_routes
    monkeypatch.setattr(auth_routes, "send_verification_email", lambda to, raw: sent.update(token=raw, to=to))
    b = body()
    r = client.post("/api/auth/signup", json=b)
    assert r.status_code == 201 and r.json()["email_verification_required"] is True
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/api/crm/leads", headers=h).status_code == 403            # blocked
    assert client.get("/api/auth/me", headers=h).status_code == 200              # still can see who they are
    assert client.post("/api/auth/verify-email", json={"token": sent["token"]}).status_code == 200
    assert client.get("/api/crm/leads", headers=h).status_code == 200            # unlocked


def test_purge_script_deletes_only_old_unverified_orgs(client, strict):
    import importlib.util, pathlib
    strict(SIGNUP_MAX_PER_IP_PER_HOUR=100)
    old_bad, old_good, new_bad = body(), body(), body()
    for b in (old_bad, old_good, new_bad):
        assert client.post("/api/auth/signup", json=b).status_code == 201
    db = dbm.SessionLocal()
    try:
        for b, age in ((old_bad, 30), (old_good, 30), (new_bad, 1)):
            org = db.query(Organization).filter(Organization.subdomain == b["subdomain"]).one()
            org.created_at = datetime.utcnow() - timedelta(days=age)
        db.query(User).filter(User.email == old_bad["admin_email"]).update({"email_verified": False})
        db.query(User).filter(User.email == old_good["admin_email"]).update({"email_verified": True})
        db.query(User).filter(User.email == new_bad["admin_email"]).update({"email_verified": False})
        db.commit()
    finally:
        db.close()
    spec = importlib.util.spec_from_file_location("purge", pathlib.Path(__file__).parents[1] / "scripts" / "purge_unverified_orgs.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    import sys
    sys.argv = ["purge", "--days", "7", "--yes"]
    mod.main()
    db = dbm.SessionLocal()
    try:
        left = {o.subdomain for o in db.query(Organization).all()}
        assert old_bad["subdomain"] not in left          # old and unverified: gone
        assert old_good["subdomain"] in left             # verified: kept
        assert new_bad["subdomain"] in left              # unverified but recent: kept
        assert db.query(User).filter(User.email == old_bad["admin_email"]).first() is None
    finally:
        db.close()
