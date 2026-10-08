"""Standard departments / job roles / starting permissions: seeded, editable, restorable, never locked."""
import uuid

from conftest import login_any
from app.services.default_structure import DEFAULT_STRUCTURE, ACTION_OF

VALID_MODULES = {"core", "dashboard", "crm", "sales", "procurement", "inventory", "finance", "hr", "projects",
                 "documents", "reports", "custom_fields", "intelligence", "workpage"}


def tree(client, h):
    return client.get("/api/core/roles/tree", headers=h).json()


def perms_of(client, h, role_id):
    return {(p["module"], p["action"]) for p in client.get(f"/api/core/roles/{role_id}/permissions", headers=h).json()}


def role_named(client, h, title):
    for d in tree(client, h)["departments"]:
        for p in d["positions"]:
            if p["title"] == title:
                return p
    raise AssertionError(title)


def test_definitions_are_sane():
    seen = set()
    for dept, roles in DEFAULT_STRUCTURE.items():
        for title, perms in roles:
            assert title not in seen and title.lower() != "admin"
            seen.add(title)
            for module, letters in perms.items():
                assert module in VALID_MODULES, module
                assert set(letters) <= set(ACTION_OF), letters
                assert module != "core" or "a" not in letters
    # nobody but Admin gets to manage access (it is not even expressible here)
    assert len(DEFAULT_STRUCTURE) >= 8


def test_new_org_gets_departments_roles_and_permissions(client, signup):
    h = signup()
    t = tree(client, h)
    names = {d["name"] for d in t["departments"]}
    assert set(DEFAULT_STRUCTURE) == names
    se = role_named(client, h, "Sales Executive")
    p = perms_of(client, h, se["role_id"])
    assert ("sales", "create") in p and ("crm", "edit") in p and ("sales", "approve") not in p and ("finance", "view") not in p
    pm = role_named(client, h, "Procurement Manager")
    assert ("procurement", "approve") in perms_of(client, h, pm["role_id"])
    for d in t["departments"]:
        for pos in d["positions"]:
            assert ("core", "manage_access") not in perms_of(client, h, pos["role_id"])
    assert [r["name"] for r in t["other_roles"]] == ["Admin"]


def test_defaults_are_editable_not_locked(client, signup):
    h = signup()
    se = role_named(client, h, "Sales Executive")
    perms = client.get(f"/api/core/roles/{se['role_id']}/permissions", headers=h).json()
    target = next(p for p in perms if p["module"] == "sales" and p["action"] == "create")
    assert client.delete(f"/api/core/roles/{se['role_id']}/permissions/{target['id']}", headers=h).status_code == 204
    assert client.post(f"/api/core/roles/{se['role_id']}/permissions", headers=h, json={"module": "finance", "action": "view"}).status_code == 201
    p = perms_of(client, h, se["role_id"])
    assert ("sales", "create") not in p and ("finance", "view") in p
    # rename the job role: the access role follows
    t = tree(client, h)
    dept = next(d for d in t["departments"] if d["name"] == "Sales & Marketing")
    pid = next(x for x in dept["positions"] if x["title"] == "Sales Executive")["position_id"]
    assert client.patch(f"/api/hr/positions/{pid}", headers=h, json={"title": "Account Executive"}).status_code == 200
    assert role_named(client, h, "Account Executive")["role_name"] == "Account Executive"


def test_deleted_default_is_not_resurrected_but_restore_adds_it_back(client, signup):
    h = signup()
    pos = role_named(client, h, "Marketing Executive")
    assert client.patch(f"/api/hr/positions/{pos['position_id']}", headers=h, json={"title": "Brand Lead"}).status_code == 200
    # edit a role's permissions, then restore: edited role must stay as edited
    se = role_named(client, h, "Sales Executive")
    before = perms_of(client, h, se["role_id"])
    perm = next(p for p in client.get(f"/api/core/roles/{se['role_id']}/permissions", headers=h).json() if p["module"] == "crm" and p["action"] == "edit")
    client.delete(f"/api/core/roles/{se['role_id']}/permissions/{perm['id']}", headers=h)
    for _ in range(2):
        tree(client, h)     # loading the tree must not re-seed
    assert ("Marketing Executive" not in [p["title"] for d in tree(client, h)["departments"] for p in d["positions"]])
    r = client.post("/api/core/roles/defaults/restore", headers=h)
    assert r.status_code == 200
    assert r.json()["roles"] == 1                       # only the renamed-away one is missing
    assert role_named(client, h, "Marketing Executive")
    assert perms_of(client, h, se["role_id"]) == before - {("crm", "edit")}     # untouched
    assert client.post("/api/core/roles/defaults/restore", headers=h).json() == {"departments": 0, "roles": 0, "permissions": 0}


def test_default_preview_endpoint(client, signup):
    h = signup()
    r = client.get("/api/core/roles/defaults", headers=h)
    assert r.status_code == 200 and {d["department"] for d in r.json()} == set(DEFAULT_STRUCTURE)


def test_hired_employee_gets_matching_access(client, signup):
    admin = signup()
    t = tree(client, admin)
    dept = next(d for d in t["departments"] if d["name"] == "Sales & Marketing")
    pos = next(x for x in dept["positions"] if x["title"] == "Sales Executive")
    email = f"se-{uuid.uuid4().hex[:8]}@test.com"
    r = client.post("/api/core/users", headers=admin, json={"name": "Sam", "email": email, "password": "pass12345", "role_id": pos["role_id"]})
    assert r.status_code == 201, r.text
    tok = login_any(client, email, "pass12345").json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/api/sales/quotations", headers=h).status_code == 200
    assert client.get("/api/finance/accounts", headers=h).status_code == 403
    assert client.get("/api/procurement/vendors", headers=h).status_code == 403
    assert client.get("/api/workpage/works", headers=h).status_code == 200


def test_old_org_without_departments_is_healed_once(client, signup):
    from app.core import database as dbm
    from app.models.hr import Department, Position
    from app.models.organization import Organization
    from app.models.role import Role, Permission
    h = signup()
    org_id = client.get("/api/auth/me", headers=h).json()["org_id"]
    s = dbm.SessionLocal()
    try:
        # make it look like an org created before this feature: nothing seeded
        pos_ids = [p.access_role_id for p in s.query(Position).filter(Position.org_id == org_id)]
        s.query(Position).filter(Position.org_id == org_id).delete()
        s.query(Department).filter(Department.org_id == org_id).delete()
        s.query(Permission).filter(Permission.role_id.in_(pos_ids)).delete(synchronize_session=False)
        s.query(Role).filter(Role.id.in_(pos_ids)).delete(synchronize_session=False)
        s.query(Organization).filter(Organization.id == org_id).update({"defaults_seeded_at": None})
        s.commit()
    finally:
        s.close()
    assert len(tree(client, h)["departments"]) == len(DEFAULT_STRUCTURE)    # healed on first view
    # an old org that already has its own departments is left alone
    h2 = signup()
    org2 = client.get("/api/auth/me", headers=h2).json()["org_id"]
    s = dbm.SessionLocal()
    try:
        ids = [p.access_role_id for p in s.query(Position).filter(Position.org_id == org2)]
        s.query(Position).filter(Position.org_id == org2).delete()
        s.query(Department).filter(Department.org_id == org2).delete()
        s.query(Permission).filter(Permission.role_id.in_(ids)).delete(synchronize_session=False)
        s.query(Role).filter(Role.id.in_(ids)).delete(synchronize_session=False)
        s.query(Organization).filter(Organization.id == org2).update({"defaults_seeded_at": None})
        s.commit()
    finally:
        s.close()
    client.post("/api/hr/departments", headers=h2, json={"name": "Own Dept"})
    assert [d["name"] for d in tree(client, h2)["departments"]] == ["Own Dept"]
