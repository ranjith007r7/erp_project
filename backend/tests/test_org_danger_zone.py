"""Reset and permanent delete of an organization: three-step confirmation, exact scope, tenant isolation."""
import re
import time
import uuid

import pytest
from sqlalchemy import func, select

import app.core.database as dbm
from app.core.config import settings
from app.core.database import Base
from app.models.organization import Organization
from app.models.user import User
from app.services import totp
from test_admin_portal_2fa import PW, login, make_admin, make_employee
from test_procurement_workflow import PO, setup

D = "/api/organizations/danger"


@pytest.fixture
def mailbox(monkeypatch):
    box = []
    import app.services.org_actions as oa
    import app.api.routes.org_danger as od
    monkeypatch.setattr(oa, "send_email", lambda to, subject, body, **kw: box.append((to, subject, body)) or "logged")
    monkeypatch.setattr(od, "send_email", lambda to, subject, body, **kw: box.append((to, subject, body)) or "logged")
    monkeypatch.setattr(settings, "ORG_ACTION_RESEND_SECONDS", 0)
    return box


def code_from(box):
    return re.search(r"Confirmation code: (\d{6})", box[-1][2]).group(1)


def populate(client, h):
    product, vendor, po = setup(client, h)
    client.post("/api/crm/leads", headers=h, json={"name": "Lead One", "email": "l1@x.com"})
    d = client.post("/api/hr/departments", headers=h, json={"name": "Finance"}).json()
    p = client.post("/api/hr/positions", headers=h, json={"department_id": d["id"], "title": "Accounts Manager", "base_salary": 50000}).json()
    e = client.post("/api/hr/employees", headers=h, json={"name": "Meera Rao", "department_id": d["id"], "position_id": p["id"]}).json()
    client.put(f"/api/finance/payroll-deductions/{e['id']}", headers=h, json={"pf_percent": 12, "insurance_percent": 0, "tds_percent": 0})
    return {"dept": d, "pos": p, "emp": e}


def counts(org_id):
    """{table: rows} for every table that belongs to the organization (directly or via a parent)."""
    from app.services.org_data import _org_condition
    db = dbm.SessionLocal()
    try:
        out = {}
        for t in Base.metadata.sorted_tables:
            if t.name in ("organizations", "signup_attempts"):
                continue
            cond = _org_condition(t, org_id)
            if cond is None:
                continue
            n = db.execute(select(func.count()).select_from(t).where(cond)).scalar()
            if n:
                out[t.name] = n
        return out
    finally:
        db.close()


def org_id_of(email):
    db = dbm.SessionLocal()
    try:
        return db.query(User).filter(User.email == email).one().org_id
    finally:
        db.close()


def ask(client, h, purpose, password=PW):
    return client.post(f"{D}/request-code", headers=h, json={"purpose": purpose, "password": password})


# ---------- guards ----------
def test_only_admins_reach_the_danger_zone(client):
    email, h = make_admin(client)
    emp = make_employee(client, h)
    eh = {"Authorization": f"Bearer {login(client, emp, 'employee').json()['access_token']}"}
    for call in (lambda: client.get(f"{D}/status", headers=eh), lambda: ask(client, eh, "delete"),
                 lambda: client.post(f"{D}/reset", headers=eh, json={"code": "123456", "confirm_text": "RESET"}),
                 lambda: client.post(f"{D}/delete", headers=eh, json={"code": "123456", "subdomain": "x"})):
        assert call().status_code == 403
    assert client.get(f"{D}/status", headers=h).status_code == 200
    assert client.get(D + "/status").status_code == 401


def test_password_and_code_rules(client, mailbox):
    email, h = make_admin(client)
    assert ask(client, h, "delete", password="wrong").status_code == 401
    assert mailbox == []                                       # nothing is sent for a wrong password
    assert ask(client, h, "delete").status_code == 200
    assert mailbox[-1][0] == email and "Confirmation code" in mailbox[-1][2]
    good = code_from(mailbox)
    bad = "000000" if good != "000000" else "111111"
    sub = client.get(f"{D}/status", headers=h).json()["subdomain"]
    assert client.post(f"{D}/delete", headers=h, json={"code": bad, "subdomain": sub}).status_code == 400
    # a delete code cannot confirm a reset
    assert client.post(f"{D}/reset", headers=h, json={"code": good, "confirm_text": "RESET"}).status_code == 400
    # wrong subdomain stops it before the code is spent
    assert client.post(f"{D}/delete", headers=h, json={"code": good, "subdomain": "not-mine"}).status_code == 400
    assert client.get("/api/auth/me", headers=h).status_code == 200


def test_code_locks_after_too_many_wrong_tries(client, mailbox):
    _, h = make_admin(client)
    ask(client, h, "reset")
    good = code_from(mailbox)
    bad = "000000" if good != "000000" else "111111"
    for _ in range(settings.ORG_ACTION_MAX_ATTEMPTS):
        assert client.post(f"{D}/reset", headers=h, json={"code": bad, "confirm_text": "RESET"}).status_code == 400
    assert client.post(f"{D}/reset", headers=h, json={"code": good, "confirm_text": "RESET"}).status_code == 400   # even the right one now


def test_code_works_once_and_expires(client, mailbox):
    _, h = make_admin(client)
    ask(client, h, "reset")
    c = code_from(mailbox)
    assert client.post(f"{D}/reset", headers=h, json={"code": c, "confirm_text": "reset"}).status_code == 400    # must be typed exactly
    assert client.post(f"{D}/reset", headers=h, json={"code": c, "confirm_text": "RESET"}).status_code == 200
    assert client.post(f"{D}/reset", headers=h, json={"code": c, "confirm_text": "RESET"}).status_code == 400    # single use
    ask(client, h, "reset")
    c2 = code_from(mailbox)
    from datetime import datetime, timedelta, timezone
    from app.models.security import OrgActionCode
    db = dbm.SessionLocal(); db.query(OrgActionCode).update({"expires_at": datetime.now(timezone.utc) - timedelta(minutes=1)}); db.commit(); db.close()
    assert client.post(f"{D}/reset", headers=h, json={"code": c2, "confirm_text": "RESET"}).status_code == 400


def test_resend_cooldown(client, mailbox, monkeypatch):
    _, h = make_admin(client)
    monkeypatch.setattr(settings, "ORG_ACTION_RESEND_SECONDS", 60)
    assert ask(client, h, "reset").status_code == 200
    assert ask(client, h, "reset").status_code == 429


# ---------- reset ----------
def test_reset_clears_business_data_but_keeps_people_and_structure(client, mailbox):
    email, h = make_admin(client)
    emp = make_employee(client, h)
    keep = populate(client, h)
    org = org_id_of(email)
    before = counts(org)
    assert before.get("products") and before.get("vendors") and before.get("purchase_orders") and before.get("crm_leads")

    ask(client, h, "reset")
    r = client.post(f"{D}/reset", headers=h, json={"code": code_from(mailbox), "confirm_text": "RESET"})
    assert r.status_code == 200, r.text
    after = counts(org)

    for gone in ("products", "vendors", "purchase_orders", "purchase_order_items", "crm_leads", "stock_levels", "notifications"):
        assert gone not in after, (gone, after)
    for kept in ("users", "roles", "permissions", "departments", "positions", "employees", "employee_payroll_profiles", "chart_of_accounts", "leave_types", "audit_log"):
        assert kept in after or kept == "leave_types", (kept, after)
    assert after["users"] == before["users"] and after["employees"] == before["employees"]
    assert after["positions"] == before["positions"]

    # still signed in, staff can still sign in, work continues from a clean slate
    assert client.get("/api/auth/me", headers=h).status_code == 200
    assert login(client, emp, "employee").status_code == 200
    assert client.get("/api/hr/employees", headers=h).json()[0]["employee_code"] == "EMP-0001"
    assert "Accounts Manager" in [x["title"] for x in client.get("/api/hr/positions", headers=h).json()]
    assert client.get("/api/sales/products", headers=h).json() == []
    product, vendor, po = setup(client, h)
    assert po["po_number"] == "PO-0001"                       # numbering starts again
    audit = client.get("/api/core/audit-log", headers=h).json()
    assert any(a["action"] == "reset_organization_data" for a in (audit if isinstance(audit, list) else audit.get("items", [])))


def test_reset_leaves_other_organizations_untouched(client, mailbox):
    email, h = make_admin(client)
    other_email, other_h = make_admin(client)
    populate(client, h); populate(client, other_h)
    other_before = counts(org_id_of(other_email))
    ask(client, h, "reset")
    assert client.post(f"{D}/reset", headers=h, json={"code": code_from(mailbox), "confirm_text": "RESET"}).status_code == 200
    assert counts(org_id_of(other_email)) == other_before


# ---------- delete ----------
def test_delete_removes_everything_and_the_email_can_sign_up_again(client, mailbox):
    email, h = make_admin(client)
    emp = make_employee(client, h)
    populate(client, h)
    other_email, other_h = make_admin(client)
    populate(client, other_h)
    other_before = counts(org_id_of(other_email))
    org = org_id_of(email)
    sub = client.get(f"{D}/status", headers=h).json()["subdomain"]
    assert counts(org)

    ask(client, h, "delete")
    r = client.post(f"{D}/delete", headers=h, json={"code": code_from(mailbox), "subdomain": sub})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "deleted"

    assert counts(org) == {}                                   # no row in any table, however deep
    db = dbm.SessionLocal()
    try:
        assert db.query(Organization).filter(Organization.id == org).first() is None
        assert db.query(User).filter(User.email.in_([email, emp])).count() == 0
    finally:
        db.close()
    assert client.get("/api/auth/me", headers=h).status_code == 401                 # session is dead
    assert login(client, email, "admin").status_code == 401
    assert login(client, emp, "employee").status_code == 401
    assert any("permanently deleted" in m[1] for m in mailbox)

    # same address, same sub-domain: a clean new start
    again = client.post("/api/auth/signup", json={"org_name": "Fresh Start", "subdomain": sub, "admin_name": "Priya Sharma", "admin_email": email, "admin_password": PW})
    assert again.status_code == 201, again.text
    assert counts(org_id_of(other_email)) == other_before


def test_delete_needs_the_authenticator_code_when_the_admin_has_one(client, mailbox, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_2FA_REQUIRED", True)
    email, _ = make_admin(client)
    from test_admin_portal_2fa import enrol
    secret, _, token = enrol(client, email)
    h = {"Authorization": f"Bearer {token}"}
    sub = client.get(f"{D}/status", headers=h).json()["subdomain"]
    ask(client, h, "delete")
    c = code_from(mailbox)
    assert client.post(f"{D}/delete", headers=h, json={"code": c, "subdomain": sub}).status_code == 400
    ask(client, h, "delete")
    c = code_from(mailbox)
    live = totp.code_now(secret, time.time() + 30)
    assert client.post(f"{D}/delete", headers=h, json={"code": c, "subdomain": sub, "totp_code": live}).status_code == 200
