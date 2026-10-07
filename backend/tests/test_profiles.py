"""Organization profile (admin edits, everyone reads) and My Profile (self-edit behind an emailed one-time code)."""
import re
import uuid

import pytest

import app.core.database as dbm
from app.core.config import settings
from app.models.hr import Employee
from app.models.user import User
from test_admin_portal_2fa import PW, login, make_admin, make_employee

ORG = "/api/organizations/profile"
ME = "/api/me/profile"


@pytest.fixture
def mailbox(monkeypatch):
    box = []
    import app.services.org_actions as oa
    monkeypatch.setattr(oa, "send_email", lambda to, subject, body, **kw: box.append((to, subject, body)) or "logged")
    monkeypatch.setattr(settings, "ORG_ACTION_RESEND_SECONDS", 0)
    return box


def code(box):
    return re.search(r"Confirmation code: (\d{6})", box[-1][2]).group(1)


def emp_login(client, email):
    return {"Authorization": f"Bearer {login(client, email, 'employee').json()['access_token']}"}


# ---------------- organization profile ----------------
def test_defaults_come_from_the_signup_admin_and_name_is_shown(client):
    email, h = make_admin(client)
    p = client.get(ORG, headers=h).json()
    assert p["name"].startswith("Org ") and p["subdomain"] and p["id"]
    assert p["owner_email"] == email and p["owner_name"] == "Priya Sharma"
    assert p["currency"] == "INR" and p["timezone"] == "Asia/Kolkata" and p["fiscal_year_start_month"] == 4
    assert p["can_edit"] is True
    me = client.get("/api/auth/me", headers=h).json()
    assert me["org_name"] == p["name"]


def test_admin_saves_partial_updates_and_name_changes(client):
    _, h = make_admin(client)
    r = client.patch(ORG, headers=h, json={"name": "Meridian Furnishings", "legal_name": "Meridian Furnishings Pvt Ltd", "owner_phone": "+91 98765 43210",
                                           "gstin": "33abcde1234f1z5", "pan": "abcde1234f", "website": "meridian.example.com", "city": "Chennai", "postal_code": "600001"})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["name"] == "Meridian Furnishings" and p["gstin"] == "33ABCDE1234F1Z5" and p["pan"] == "ABCDE1234F"
    assert p["website"] == "https://meridian.example.com"
    assert p["owner_email"] and p["owner_name"] == "Priya Sharma"   # defaults survive the first save
    # a second partial save leaves the first fields alone
    p = client.patch(ORG, headers=h, json={"state": "Tamil Nadu"}).json()
    assert p["city"] == "Chennai" and p["state"] == "Tamil Nadu" and p["legal_name"].endswith("Pvt Ltd")
    # empty text clears
    assert client.patch(ORG, headers=h, json={"city": ""}).json()["city"] is None
    assert client.get("/api/auth/me", headers=h).json()["org_name"] == "Meridian Furnishings"


@pytest.mark.parametrize("bad", [
    {"gstin": "NOT-A-GSTIN"}, {"pan": "123"}, {"cin": "x"}, {"owner_email": "nope"}, {"owner_phone": "abc"},
    {"fiscal_year_start_month": 13}, {"currency": "RUPEES"}, {"timezone": "Mars/Base"}, {"founded_on": "2999-01-01"},
    {"company_size": "huge"}, {"postal_code": "!!"}, {"name": "A"}, {"unknown_field": "x"},
])
def test_invalid_values_are_rejected(client, bad):
    _, h = make_admin(client)
    assert client.patch(ORG, headers=h, json=bad).status_code == 422


def test_employees_can_read_but_not_change_the_org_profile(client):
    _, h = make_admin(client)
    client.patch(ORG, headers=h, json={"legal_name": "Visible Co"})
    emp = make_employee(client, h)
    eh = emp_login(client, emp)
    p = client.get(ORG, headers=eh).json()
    assert p["legal_name"] == "Visible Co" and p["can_edit"] is False
    assert client.patch(ORG, headers=eh, json={"legal_name": "Hacked"}).status_code == 403
    assert client.get(ORG, headers=h).json()["legal_name"] == "Visible Co"


def test_org_profiles_are_isolated_between_organizations(client):
    _, h1 = make_admin(client); _, h2 = make_admin(client)
    client.patch(ORG, headers=h1, json={"legal_name": "Alpha Ltd"})
    assert client.get(ORG, headers=h2).json()["legal_name"] is None


def test_reset_keeps_the_profile_and_delete_removes_it(client):
    from app.models.organization import OrganizationProfile
    from app.services.org_data import reset_business_data, delete_organization
    email, h = make_admin(client)
    client.patch(ORG, headers=h, json={"legal_name": "Keep Me"})
    db = dbm.SessionLocal()
    org_id = db.query(User).filter(User.email == email).one().org_id
    reset_business_data(db, org_id); db.commit()
    assert db.query(OrganizationProfile).filter(OrganizationProfile.org_id == org_id).one().legal_name == "Keep Me"
    delete_organization(db, org_id); db.commit()
    assert db.query(OrganizationProfile).filter(OrganizationProfile.org_id == org_id).count() == 0
    db.close()


# ---------------- my profile ----------------
def hire(client, h, with_login=True):
    """An employee with an HR record, linked to a working login."""
    d = client.post("/api/hr/departments", headers=h, json={"name": f"Sales{uuid.uuid4().hex[:4]}"}).json()
    pos = client.post("/api/hr/positions", headers=h, json={"department_id": d["id"], "title": "Sales Executive", "base_salary": 45000}).json()
    r = client.post("/api/hr/employees", headers=h, json={"name": "Arjun Nair", "department_id": d["id"], "position_id": pos["id"], "phone": "9000000001"})
    assert r.status_code == 201, r.text
    emp = r.json()
    email = f"arjun{uuid.uuid4().hex[:6]}@test.com"
    r = client.post(f"/api/hr/employees/{emp['id']}/create-login", headers=h, json={"email": email})
    assert r.status_code in (200, 201), r.text
    # accept the invite the quick way: give the invited user a password and activate them
    from app.core.security import hash_password
    db = dbm.SessionLocal()
    db.query(User).filter(User.email == email).update({"password_hash": hash_password(PW), "status": "active", "email_verified": True})
    db.commit(); db.close()
    return emp, email


def test_my_profile_shows_own_hr_details_with_hr_fields_locked(client):
    _, h = make_admin(client)
    emp, email = hire(client, h)
    eh = emp_login(client, email)
    p = client.get(ME, headers=eh).json()
    assert p["employee"]["employee_code"] and p["employee"]["designation"] == "Sales Executive"
    assert p["employee"]["phone"] == "9000000001"
    assert "salary" in p["employee"]
    assert set(p["editable_fields"]) == {"name", "phone", "personal_email", "date_of_birth", "gender", "address", "emergency_contact_name", "emergency_contact_phone"}
    assert p["otp_sent_to"].endswith("@test.com")


def test_edit_needs_a_valid_emailed_code(client, mailbox):
    _, h = make_admin(client)
    emp, email = hire(client, h)
    eh = emp_login(client, email)
    assert client.patch(ME, headers=eh, json={"otp": "123456", "phone": "9111111111"}).status_code == 400   # no code issued yet
    assert client.post(ME + "/request-otp", headers=eh).status_code == 200
    assert mailbox[-1][0] == email and "update your profile" in mailbox[-1][1]
    assert client.patch(ME, headers=eh, json={"otp": "000000" if code(mailbox) != "000000" else "111111", "phone": "9111111111"}).status_code == 400
    assert client.get(ME, headers=eh).json()["employee"]["phone"] == "9000000001"
    r = client.patch(ME, headers=eh, json={"otp": code(mailbox), "phone": "9111111111", "address": "12 Anna Salai, Chennai", "gender": "male"})
    assert r.status_code == 200 and set(r.json()["changed"]) == {"phone", "address", "gender"}
    e = client.get(ME, headers=eh).json()["employee"]
    assert e["phone"] == "9111111111" and e["address"].startswith("12 Anna")
    # HR sees the same change
    hr = client.get(f"/api/hr/employees/{emp['id']}", headers=h).json()
    assert hr["phone"] == "9111111111"
    # the code is single use
    assert client.patch(ME, headers=eh, json={"otp": code(mailbox), "phone": "9222222222"}).status_code == 400


def test_hr_controlled_fields_cannot_be_changed_by_the_employee(client, mailbox):
    _, h = make_admin(client)
    emp, email = hire(client, h)
    eh = emp_login(client, email)
    client.post(ME + "/request-otp", headers=eh)
    for field, value in [("salary", 999999), ("employee_code", "EMP-9999"), ("status", "inactive"), ("department_id", str(uuid.uuid4())), ("position_id", str(uuid.uuid4())), ("joining_date", "2000-01-01"), ("user_id", str(uuid.uuid4()))]:
        assert client.patch(ME, headers=eh, json={"otp": code(mailbox), field: value}).status_code == 422, field
    assert client.get(f"/api/hr/employees/{emp['id']}", headers=h).json()["salary"] in ("45000.00", 45000, "45000")


def test_nothing_to_change_does_not_burn_the_code(client, mailbox):
    _, h = make_admin(client)
    _, email = hire(client, h)
    eh = emp_login(client, email)
    client.post(ME + "/request-otp", headers=eh)
    c = code(mailbox)
    assert client.patch(ME, headers=eh, json={"otp": c, "phone": "9000000001"}).status_code == 400   # same value
    assert client.patch(ME, headers=eh, json={"otp": c, "phone": "9333333333"}).status_code == 200    # same code still works


def test_wrong_codes_lock_out_after_the_attempt_limit(client, mailbox):
    _, h = make_admin(client)
    _, email = hire(client, h)
    eh = emp_login(client, email)
    client.post(ME + "/request-otp", headers=eh)
    good = code(mailbox)
    bad = "000000" if good != "000000" else "111111"
    for _ in range(settings.ORG_ACTION_MAX_ATTEMPTS):
        assert client.patch(ME, headers=eh, json={"otp": bad, "phone": "9444444444"}).status_code == 400
    assert client.patch(ME, headers=eh, json={"otp": good, "phone": "9444444444"}).status_code == 400


def test_a_code_for_one_purpose_or_person_does_not_work_elsewhere(client, mailbox):
    _, h = make_admin(client)
    _, e1 = hire(client, h); _, e2 = hire(client, h)
    h1, h2 = emp_login(client, e1), emp_login(client, e2)
    client.post(ME + "/request-otp", headers=h1)
    c1 = code(mailbox)
    assert client.patch(ME, headers=h2, json={"otp": c1, "phone": "9555555555"}).status_code == 400
    # a danger-zone code (different purpose) cannot be used for a profile edit
    from app.services import org_actions
    db = dbm.SessionLocal(); u = db.query(User).filter(User.email == e1).one()
    org_actions.issue_code(db, u, "X", "reset"); db.close()
    assert client.patch(ME, headers=h1, json={"otp": code(mailbox), "phone": "9555555555"}).status_code == 400


def test_invalid_values_are_rejected_before_any_code_is_used(client, mailbox):
    _, h = make_admin(client)
    _, email = hire(client, h)
    eh = emp_login(client, email)
    client.post(ME + "/request-otp", headers=eh)
    c = code(mailbox)
    for bad in [{"phone": "abc"}, {"personal_email": "nope"}, {"gender": "x"}, {"date_of_birth": "2999-01-01"}]:
        assert client.patch(ME, headers=eh, json={"otp": c, **bad}).status_code == 422
    assert client.patch(ME, headers=eh, json={"otp": c, "phone": "9666666666"}).status_code == 200


def test_user_without_hr_record_can_only_change_their_name(client, mailbox):
    email, h = make_admin(client)
    p = client.get(ME, headers=h).json()
    assert p["employee"] is None and p["editable_fields"] == ["name"]
    client.post(ME + "/request-otp", headers=h)
    assert client.patch(ME, headers=h, json={"otp": code(mailbox), "phone": "9777777777"}).status_code == 400
    assert client.patch(ME, headers=h, json={"otp": code(mailbox), "name": "Priya S"}).status_code == 200
    assert client.get("/api/auth/me", headers=h).json()["name"] == "Priya S"


def test_name_change_updates_login_and_hr_record_and_is_audited(client, mailbox):
    _, h = make_admin(client)
    emp, email = hire(client, h)
    eh = emp_login(client, email)
    client.post(ME + "/request-otp", headers=eh)
    assert client.patch(ME, headers=eh, json={"otp": code(mailbox), "name": "Arjun K Nair"}).status_code == 200
    assert client.get("/api/auth/me", headers=eh).json()["name"] == "Arjun K Nair"
    assert client.get(f"/api/hr/employees/{emp['id']}", headers=h).json()["name"] == "Arjun K Nair"
    log = client.get("/api/core/audit-log", headers=h)
    assert log.status_code == 200 and "update_own_profile:name" in log.text


def test_requesting_codes_is_rate_limited(client, mailbox, monkeypatch):
    monkeypatch.setattr(settings, "ORG_ACTION_RESEND_SECONDS", 60)
    _, h = make_admin(client)
    _, email = hire(client, h)
    eh = emp_login(client, email)
    assert client.post(ME + "/request-otp", headers=eh).status_code == 200
    assert client.post(ME + "/request-otp", headers=eh).status_code == 429


def test_signed_out_requests_are_refused(client):
    assert client.get(ME).status_code in (401, 403)
    assert client.get(ORG).status_code in (401, 403)
