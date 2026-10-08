"""Employee self-service leave (balances, rules, cancel) and attendance marked by an administrator only."""
from datetime import date, timedelta

import app.core.database as dbm
from app.models.notification import Notification
from test_admin_portal_2fa import make_admin
from test_profiles import emp_login, hire

LV = "/api/me/leaves"
ATT = "/api/hr/attendance"


def d(n):
    return (date.today() + timedelta(days=n)).isoformat()


def apply(client, h, kind="Casual Leave", start=1, end=1, reason=None):
    return client.post(LV, headers=h, json={"leave_type": kind, "start_date": d(start), "end_date": d(end), **({"reason": reason} if reason else {})})


def setup(client):
    _, ah = make_admin(client)
    emp, email = hire(client, ah)
    return ah, emp, emp_login(client, email)


def balance(client, h, name):
    return next(b for b in client.get(LV, headers=h).json()["balances"] if b["name"] == name)


# ---------------- leave ----------------
def test_employee_files_leave_and_sees_balance_and_approvers_are_notified(client):
    ah, emp, eh = setup(client)
    b = balance(client, eh, "Casual Leave")
    assert float(b["entitlement"]) == 12 and float(b["remaining"]) == 12
    r = apply(client, eh, "Casual Leave", 2, 4, "Family function")
    assert r.status_code == 201, r.text
    lr = r.json()
    assert lr["status"] == "pending" and lr["days"] == 3 and lr["reason"] == "Family function"
    b = balance(client, eh, "Casual Leave")
    assert float(b["pending"]) == 3 and float(b["remaining"]) == 9
    db = dbm.SessionLocal()
    msgs = [n.message for n in db.query(Notification).all()]
    db.close()
    assert any("applied for Casual Leave" in m and "3 day" in m for m in msgs)
    # the admin sees it in HR with the days and reason
    row = next(x for x in client.get("/api/hr/leave-requests", headers=ah).json() if x["id"] == lr["id"])
    assert row["days"] == 3 and row["reason"] == "Family function"


def test_type_can_be_given_by_code_and_unknown_types_are_refused(client):
    _, _, eh = setup(client)
    assert apply(client, eh, "CL", 1, 1).json()["leave_type"] == "Casual Leave"
    assert apply(client, eh, "Holiday on Mars", 5, 5).status_code == 400


def test_date_rules(client):
    _, _, eh = setup(client)
    assert apply(client, eh, "Casual Leave", 5, 3).status_code == 400            # end before start
    assert apply(client, eh, "Loss of Pay (Unpaid)", 1, 70).status_code == 400   # longer than 60 days
    assert apply(client, eh, "Casual Leave", -45, -44).status_code == 400        # too far back for self-service
    assert apply(client, eh, "Casual Leave", -5, -5).status_code == 201           # recent past is fine
    assert apply(client, eh, "Sick Leave", -5, -4).status_code == 400            # overlaps the pending one


def test_balance_is_enforced_and_cancelling_gives_days_back(client):
    _, _, eh = setup(client)
    first = apply(client, eh, "Casual Leave", 1, 12)
    assert first.status_code == 201
    r = apply(client, eh, "Casual Leave", 20, 20)
    assert r.status_code == 400 and "Not enough Casual Leave" in r.json()["detail"]
    assert client.post(f"{LV}/{first.json()['id']}/cancel", headers=eh).json()["status"] == "cancelled"
    assert float(balance(client, eh, "Casual Leave")["remaining"]) == 12
    assert apply(client, eh, "Casual Leave", 20, 20).status_code == 201


def test_unpaid_and_unlimited_types_have_no_cap(client):
    _, _, eh = setup(client)
    assert apply(client, eh, "Loss of Pay (Unpaid)", 1, 40).status_code == 201
    assert balance(client, eh, "Loss of Pay (Unpaid)")["remaining"] is None


def test_admin_decision_flows_back_to_the_employee(client):
    ah, _, eh = setup(client)
    lr = apply(client, eh, "Sick Leave", 1, 2).json()
    r = client.patch(f"/api/hr/leave-requests/{lr['id']}/status", headers=ah, json={"status": "approved", "note": "Get well soon"})
    assert r.status_code == 200
    mine = next(x for x in client.get(LV, headers=eh).json()["requests"] if x["id"] == lr["id"])
    assert mine["status"] == "approved" and mine["decision_note"] == "Get well soon"
    b = balance(client, eh, "Sick Leave")
    assert float(b["approved"]) == 2 and float(b["pending"]) == 0
    db = dbm.SessionLocal()
    assert any("was approved" in n.message and "Get well soon" in n.message for n in db.query(Notification).all())
    db.close()
    # an approved request cannot be cancelled by the employee
    assert client.post(f"{LV}/{lr['id']}/cancel", headers=eh).status_code == 400


def test_cancelled_request_cannot_be_decided(client):
    ah, _, eh = setup(client)
    lr = apply(client, eh, "Casual Leave", 1, 1).json()
    client.post(f"{LV}/{lr['id']}/cancel", headers=eh)
    assert client.patch(f"/api/hr/leave-requests/{lr['id']}/status", headers=ah, json={"status": "approved"}).status_code == 400


def test_people_only_ever_touch_their_own_leave(client):
    ah, _, e1 = setup(client)
    # a second employee in the same organization
    _, email2 = hire(client, ah)
    e2 = emp_login(client, email2)
    mine = apply(client, e1, "Casual Leave", 1, 1).json()
    assert client.post(f"{LV}/{mine['id']}/cancel", headers=e2).status_code == 404
    assert client.get(LV, headers=e2).json()["requests"] == []
    # naming another employee in the body is refused outright
    assert client.post(LV, headers=e2, json={"employee_id": "x", "leave_type": "Casual Leave", "start_date": d(1), "end_date": d(1)}).status_code == 422


def test_login_without_an_hr_record_gets_a_clear_message(client):
    _, ah = make_admin(client)
    r = client.get(LV, headers=ah)
    assert r.status_code == 404 and "HR record" in r.json()["detail"]


def test_admin_can_record_leave_for_someone_with_the_same_rules_but_no_backdating_limit(client):
    ah, emp, _ = setup(client)
    old = client.post("/api/hr/leave-requests", headers=ah, json={"employee_id": emp["id"], "leave_type": "Sick Leave", "start_date": d(-90), "end_date": d(-89)})
    assert old.status_code == 201, old.text
    bad = client.post("/api/hr/leave-requests", headers=ah, json={"employee_id": emp["id"], "leave_type": "Nonsense", "start_date": d(1), "end_date": d(1)})
    assert bad.status_code == 400


def test_other_organizations_cannot_see_or_decide_the_request(client):
    ah, _, eh = setup(client)
    lr = apply(client, eh, "Casual Leave", 1, 1).json()
    _, other = make_admin(client)
    assert all(x["id"] != lr["id"] for x in client.get("/api/hr/leave-requests", headers=other).json())
    assert client.patch(f"/api/hr/leave-requests/{lr['id']}/status", headers=other, json={"status": "approved"}).status_code == 404


# ---------------- attendance ----------------
def test_only_an_administrator_can_mark_attendance(client):
    ah, emp, eh = setup(client)
    body = {"employee_id": emp["id"], "status": "present"}
    assert client.post(ATT, headers=eh, json=body).status_code == 403                 # the employee, for themselves
    assert client.post(f"{ATT}/bulk", headers=eh, json={"date": d(0), "entries": [body]}).status_code == 403
    # even a user with the HR create permission is not enough
    users = client.get("/api/core/users", headers=ah).json()
    role_id = next(u["role_id"] for u in users if u["role_id"] and u["email"] != "" and u["name"] != "Priya Sharma")
    client.post(f"/api/core/roles/{role_id}/permissions", headers=ah, json={"module": "hr", "action": "create"})
    assert client.post(ATT, headers=eh, json=body).status_code == 403
    assert client.post(ATT, headers=ah, json=body).status_code == 201


def test_marking_dates_and_updating_a_mark(client):
    ah, emp, _ = setup(client)
    eid = emp["id"]
    assert client.post(ATT, headers=ah, json={"employee_id": eid, "status": "present", "date": d(1)}).status_code == 400    # future
    assert client.post(ATT, headers=ah, json={"employee_id": eid, "status": "present", "date": d(-61)}).status_code == 400  # too old
    assert client.post(ATT, headers=ah, json={"employee_id": eid, "status": "present", "date": d(-3)}).status_code == 201
    r = client.post(ATT, headers=ah, json={"employee_id": eid, "status": "half_day", "date": d(-3)})
    assert r.status_code == 201 and r.json()["status"] == "half_day"
    rows = [a for a in client.get(ATT, headers=ah).json() if a["date"] == d(-3)]
    assert len(rows) == 1                                                            # updated, not duplicated
    assert client.post(ATT, headers=ah, json={"employee_id": eid, "status": "sleeping"}).status_code == 422


def test_bulk_day_sheet_grid_and_summary(client):
    ah, emp, _ = setup(client)
    _, email2 = hire(client, ah)
    emps = client.get("/api/hr/employees", headers=ah).json()
    assert len(emps) == 2
    r = client.post(f"{ATT}/bulk", headers=ah, json={"date": d(-1), "entries": [{"employee_id": emps[0]["id"], "status": "present"}, {"employee_id": emps[1]["id"], "status": "absent"}]})
    assert r.status_code == 200 and r.json()["saved"] == 2
    grid = client.get(f"{ATT}/day", headers=ah, params={"date": d(-1)}).json()
    assert {x["status"] for x in grid["employees"]} == {"present", "absent"} and all(x["marked"] for x in grid["employees"])
    today = client.get(f"{ATT}/day", headers=ah).json()
    assert all(not x["marked"] and x["status"] is None for x in today["employees"])
    m = date.today() - timedelta(days=1)
    summ = client.get(f"{ATT}/summary", headers=ah, params={"month": m.month, "year": m.year}).json()
    assert sum(x["present"] for x in summ) == 1 and sum(x["absent"] for x in summ) == 1
    # an unknown employee id fails the whole save and writes nothing
    bad = client.post(f"{ATT}/bulk", headers=ah, json={"date": d(-2), "entries": [{"employee_id": emps[0]["id"], "status": "present"}, {"employee_id": "00000000-0000-0000-0000-000000000000", "status": "present"}]})
    assert bad.status_code == 404
    assert not [a for a in client.get(ATT, headers=ah).json() if a["date"] == d(-2)]


def test_approved_leave_shows_as_leave_for_unmarked_days(client):
    ah, emp, eh = setup(client)
    lr = client.post("/api/hr/leave-requests", headers=ah, json={"employee_id": emp["id"], "leave_type": "Casual Leave", "start_date": d(-2), "end_date": d(-1)}).json()
    client.patch(f"/api/hr/leave-requests/{lr['id']}/status", headers=ah, json={"status": "approved"})
    grid = client.get(f"{ATT}/day", headers=ah, params={"date": d(-1)}).json()["employees"][0]
    assert grid["on_approved_leave"] is True and grid["marked"] is False
    mine = client.get("/api/me/attendance", headers=eh).json()
    leave_days = [x for x in mine["days"] if x["from_approved_leave"]]
    # only days inside the current month show; the two leave days may straddle a month edge
    assert len(leave_days) >= 1 and all(x["status"] == "leave" for x in leave_days)
    # an explicit admin mark wins over the derived value
    client.post(ATT, headers=ah, json={"employee_id": emp["id"], "status": "present", "date": d(-1)})
    mine = client.get("/api/me/attendance", headers=eh).json()
    assert next(x for x in mine["days"] if x["date"] == d(-1))["status"] == "present"


def test_employee_sees_only_their_own_attendance_read_only(client):
    ah, emp, eh = setup(client)
    _, email2 = hire(client, ah)
    e2 = emp_login(client, email2)
    client.post(ATT, headers=ah, json={"employee_id": emp["id"], "status": "present", "date": d(0)})
    mine = client.get("/api/me/attendance", headers=eh).json()
    assert mine["counts"]["present"] == 1
    assert client.get("/api/me/attendance", headers=e2).json()["counts"]["present"] == 0
    # the employee has no way to edit it, and the org-wide list needs hr.view
    assert client.get(ATT, headers=eh).status_code == 403


def test_attendance_is_isolated_between_organizations(client):
    _, emp, _ = setup(client)
    ah2 = make_admin(client)[1]
    assert client.post(ATT, headers=ah2, json={"employee_id": emp["id"], "status": "present"}).status_code == 404
