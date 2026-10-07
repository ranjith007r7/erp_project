"""Departments -> positions with fixed salary -> employee application form -> employee code -> login."""
import io
import uuid
from decimal import Decimal

from test_procurement_workflow import make_user

D = Decimal
HR_CLERK = [("hr", "view"), ("hr", "create"), ("hr", "edit")]


def dept(client, h, name="Sales"):
    r = client.post("/api/hr/departments", headers=h, json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def pos(client, h, d, title="Sales Executive", salary=45000, **kw):
    r = client.post("/api/hr/positions", headers=h, json={"department_id": d["id"], "title": title, "base_salary": salary, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def test_salary_comes_from_the_position_and_typed_salary_is_ignored(client, signup):
    admin = signup()
    d = dept(client, admin)
    p = pos(client, admin, d)
    clerk = make_user(client, admin, HR_CLERK, "HR Clerk")
    r = client.post("/api/hr/employees", headers=clerk, json={
        "name": "Arjun Nair", "department_id": d["id"], "position_id": p["id"], "salary": 999999,
        "phone": "9876543210", "personal_email": "arjun@mail.com", "gender": "male", "date_of_birth": "1998-04-02",
        "address": "12 Anna Nagar, Chennai", "emergency_contact_name": "Mr Nair", "emergency_contact_phone": "9000000000",
        "employment_type": "full_time", "joining_date": "2026-10-01"})
    assert r.status_code == 201, r.text
    e = r.json()
    assert D(e["salary"]) == D("45000") and e["designation"] == "Sales Executive" and e["department_name"] == "Sales"
    assert e["employee_code"] == "EMP-0001" and e["phone"] == "9876543210" and e["emergency_contact_name"] == "Mr Nair"
    assert e["login_status"] is None


def test_clerk_cannot_bypass_the_fixed_salary(client, signup):
    admin = signup()
    clerk = make_user(client, admin, HR_CLERK)
    r = client.post("/api/hr/employees", headers=clerk, json={"name": "X", "salary": 100000, "designation": "CEO"})
    assert r.status_code == 400 and "role" in r.json()["detail"].lower()
    # an authoriser (Admin) may still enter one manually
    assert client.post("/api/hr/employees", headers=admin, json={"name": "Y", "salary": 100000}).status_code == 201


def test_only_authorisers_manage_departments_positions_and_policy(client, signup):
    admin = signup()
    clerk = make_user(client, admin, HR_CLERK)
    d = dept(client, admin)
    p = pos(client, admin, d)
    assert client.post("/api/hr/departments", headers=clerk, json={"name": "Hack"}).status_code == 403
    assert client.post("/api/hr/positions", headers=clerk, json={"department_id": d["id"], "title": "T", "base_salary": 1}).status_code == 403
    assert client.patch(f"/api/hr/positions/{p['id']}", headers=clerk, json={"base_salary": 1}).status_code == 403
    assert client.get("/api/hr/positions", headers=clerk).status_code == 200


def test_position_must_match_department_and_names_are_unique(client, signup):
    admin = signup()
    sales, ops = dept(client, admin), dept(client, admin, "Operations")
    p = pos(client, admin, sales)
    r = client.post("/api/hr/employees", headers=admin, json={"name": "Z", "department_id": ops["id"], "position_id": p["id"]})
    assert r.status_code == 400
    assert client.post("/api/hr/departments", headers=admin, json={"name": "sales"}).status_code == 400
    assert client.post("/api/hr/positions", headers=admin, json={"department_id": sales["id"], "title": "sales executive", "base_salary": 1}).status_code == 400
    pos(client, admin, ops, "Sales Executive", 1000)   # same title in another department is fine
    assert client.post("/api/hr/positions", headers=admin, json={"department_id": sales["id"], "title": "T", "base_salary": -5}).status_code == 422


def test_employee_codes_are_sequential_per_org(client, signup):
    a, b = signup(), signup()
    for n in range(3):
        client.post("/api/hr/employees", headers=a, json={"name": f"E{n}", "salary": 1})
    client.post("/api/hr/employees", headers=b, json={"name": "Other", "salary": 1})
    assert [e["employee_code"] for e in client.get("/api/hr/employees", headers=a).json()] == ["EMP-0001", "EMP-0002", "EMP-0003"]
    assert [e["employee_code"] for e in client.get("/api/hr/employees", headers=b).json()] == ["EMP-0001"]


def test_changing_a_position_salary_only_touches_existing_staff_when_asked(client, signup):
    admin = signup()
    d = dept(client, admin)
    p = pos(client, admin, d, salary=40000)
    e = client.post("/api/hr/employees", headers=admin, json={"name": "A", "department_id": d["id"], "position_id": p["id"]}).json()
    r = client.patch(f"/api/hr/positions/{p['id']}", headers=admin, json={"base_salary": 50000})
    assert D(r.json()["base_salary"]) == 50000
    assert D(client.get(f"/api/hr/employees/{e['id']}", headers=admin).json()["salary"]) == 40000      # snapshot kept
    new = client.post("/api/hr/employees", headers=admin, json={"name": "B", "department_id": d["id"], "position_id": p["id"]}).json()
    assert D(new["salary"]) == 50000                                                                     # new hires get the new rate
    client.patch(f"/api/hr/positions/{p['id']}", headers=admin, json={"base_salary": 55000, "apply_to_existing": True})
    assert D(client.get(f"/api/hr/employees/{e['id']}", headers=admin).json()["salary"]) == 55000
    assert [x for x in client.get("/api/hr/positions", headers=admin).json() if x["id"] == p["id"]][0]["employee_count"] == 2


def test_login_for_employee_uses_the_access_role_of_their_position(client, signup):
    admin = signup()
    u = uuid.uuid4().hex[:8]
    arjun, intern, other = f"arjun-{u}@co.com", f"intern-{u}@co.com", f"other-{u}@co.com"
    role = client.post("/api/core/roles", headers=admin, json={"name": "Sales Exec Access"}).json()
    client.post(f"/api/core/roles/{role['id']}/permissions", headers=admin, json={"module": "sales", "action": "view"})
    d = dept(client, admin)
    with_role = pos(client, admin, d, "Sales Executive", 45000, access_role_id=role["id"])
    no_role = pos(client, admin, d, "Intern", 10000)
    e1 = client.post("/api/hr/employees", headers=admin, json={"name": "Arjun", "department_id": d["id"], "position_id": with_role["id"]}).json()
    e2 = client.post("/api/hr/employees", headers=admin, json={"name": "Intern", "department_id": d["id"], "position_id": no_role["id"]}).json()

    r = client.post(f"/api/hr/employees/{e2['id']}/create-login", headers=admin, json={"email": intern})
    # every job role now has its own (initially empty) access role, so a login is allowed and starts with no access
    assert r.status_code == 200 and r.json()["access_role_name"] == "Intern", r.text
    assert client.get(f"/api/core/roles/{no_role['access_role_id']}/permissions", headers=admin).json() == []

    assert client.post(f"/api/hr/employees/{e1['id']}/create-login", headers=admin, json={"email": "bad"}).status_code == 422
    r = client.post(f"/api/hr/employees/{e1['id']}/create-login", headers=admin, json={"email": arjun})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["login_status"] == "invited" and out["login_email"] == arjun and out["access_role_name"] == "Sales Exec Access"
    # reflected in Settings > Users with the right role
    users = client.get("/api/core/users", headers=admin).json()
    u = next(x for x in users if x["email"] == arjun)
    assert u["role_name"] == "Sales Exec Access" and u["status"] == "invited" and u["id"] == out["user_id"]
    # only once, and not for an email already in use
    assert client.post(f"/api/hr/employees/{e1['id']}/create-login", headers=admin, json={"email": other}).status_code == 400
    e3 = client.post("/api/hr/employees", headers=admin, json={"name": "C", "department_id": d["id"], "position_id": with_role["id"]}).json()
    assert client.post(f"/api/hr/employees/{e3['id']}/create-login", headers=admin, json={"email": arjun}).status_code == 400


def test_create_login_needs_manage_access_and_is_org_scoped(client, signup):
    admin, other = signup(), signup()
    role = client.post("/api/core/roles", headers=admin, json={"name": "R"}).json()
    d = dept(client, admin)
    p = pos(client, admin, d, access_role_id=role["id"])
    e = client.post("/api/hr/employees", headers=admin, json={"name": "A", "department_id": d["id"], "position_id": p["id"]}).json()
    clerk = make_user(client, admin, HR_CLERK)
    assert client.post(f"/api/hr/employees/{e['id']}/create-login", headers=clerk, json={"email": "a@co.com"}).status_code == 403
    assert client.post(f"/api/hr/employees/{e['id']}/create-login", headers=other, json={"email": "a@co.com"}).status_code == 404
    other_role = client.post("/api/core/roles", headers=other, json={"name": "Foreign"}).json()
    assert client.post("/api/hr/positions", headers=admin, json={"department_id": d["id"], "title": "Z", "base_salary": 1, "access_role_id": other_role["id"]}).status_code == 404


def test_employee_update_and_role_change_needs_authority(client, signup):
    admin = signup()
    d = dept(client, admin)
    p1, p2 = pos(client, admin, d, "Junior", 20000), pos(client, admin, d, "Senior", 40000)
    clerk = make_user(client, admin, HR_CLERK)
    e = client.post("/api/hr/employees", headers=clerk, json={"name": "A", "department_id": d["id"], "position_id": p1["id"]}).json()
    r = client.patch(f"/api/hr/employees/{e['id']}", headers=clerk, json={"phone": "12345", "address": "New addr"})
    assert r.status_code == 200 and r.json()["phone"] == "12345"
    assert client.patch(f"/api/hr/employees/{e['id']}", headers=clerk, json={"position_id": p2["id"]}).status_code == 403
    r = client.patch(f"/api/hr/employees/{e['id']}", headers=admin, json={"position_id": p2["id"]})
    assert r.status_code == 200 and D(r.json()["salary"]) == 40000 and r.json()["designation"] == "Senior"


def test_csv_import_uses_position_salary_and_ignores_typed_salary_for_clerks(client, signup):
    admin = signup()
    d = dept(client, admin)
    pos(client, admin, d, "Sales Executive", 45000)
    clerk = make_user(client, admin, HR_CLERK)
    csv_text = "name,designation,department_name,salary\nAsha,Sales Executive,Sales,1\nBala,Freelancer,Sales,77777\n"
    files = {"file": ("e.csv", io.BytesIO(csv_text.encode()), "text/csv")}
    r = client.post("/api/hr/employees/import", headers=clerk, files=files)
    assert r.status_code == 200 and r.json()["imported"] == 2
    emps = {e["name"]: e for e in client.get("/api/hr/employees", headers=admin).json()}
    assert D(emps["Asha"]["salary"]) == 45000 and emps["Asha"]["employee_code"]
    assert D(emps["Bala"]["salary"]) == 0                       # no matching position + clerk -> typed salary not honoured
    files = {"file": ("e.csv", io.BytesIO(b"name,salary\nCharu,12345\n"), "text/csv")}
    assert client.post("/api/hr/employees/import", headers=admin, files=files).json()["imported"] == 1
    assert D({e["name"]: e for e in client.get("/api/hr/employees", headers=admin).json()}["Charu"]["salary"]) == 12345


def test_org_isolation_for_structure(client, signup):
    a, b = signup(), signup()
    d = dept(client, a)
    p = pos(client, a, d)
    e = client.post("/api/hr/employees", headers=a, json={"name": "A", "department_id": d["id"], "position_id": p["id"]}).json()
    assert client.get("/api/hr/positions", headers=b).json() == []
    assert client.get(f"/api/hr/employees/{e['id']}", headers=b).status_code == 404
    assert client.patch(f"/api/hr/positions/{p['id']}", headers=b, json={"base_salary": 1}).status_code == 404
    assert client.post("/api/hr/positions", headers=b, json={"department_id": d["id"], "title": "T", "base_salary": 1}).status_code == 404
    assert client.post("/api/hr/employees", headers=b, json={"name": "Z", "department_id": d["id"], "position_id": p["id"]}).status_code == 404
