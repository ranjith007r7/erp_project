"""Departments & Roles page -> Roles & Permissions tree, kept in step automatically."""
from test_hr_structure import dept, pos
from test_procurement_workflow import make_user


def tree(client, h):
    r = client.get("/api/core/roles/tree", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def find_dept(t, name):
    return next(d for d in t["departments"] if d["name"] == name)


def test_new_position_gets_its_own_access_role_and_appears_in_the_tree(client, signup):
    admin = signup()
    fin = dept(client, admin, "Finance")
    ops = dept(client, admin, "Operations")
    p = pos(client, admin, fin, "Accounts Manager", 50000)
    assert p["access_role_id"] and p["access_role_name"] == "Accounts Manager"
    t = tree(client, admin)
    f = find_dept(t, "Finance")
    assert [x["title"] for x in f["positions"]] == ["Accounts Manager"]
    assert f["positions"][0]["role_id"] == p["access_role_id"]
    assert find_dept(t, "Operations")["positions"] == []  # empty departments still shown
    assert {r["name"] for r in t["other_roles"]} == {"Admin"}
    # the new role is a normal role: permissions can be granted to it
    rid = p["access_role_id"]
    assert client.post(f"/api/core/roles/{rid}/permissions", headers=admin, json={"module": "finance", "action": "view"}).status_code == 201


def test_many_roles_per_department_and_same_title_in_two_departments(client, signup):
    admin = signup()
    fin, sales = dept(client, admin, "Finance"), dept(client, admin, "Sales")
    for t_ in ["Accounts Manager", "Accounts Supervisor", "Cashier", "Auditor"]:
        pos(client, admin, fin, t_)
    a = pos(client, admin, sales, "Manager")
    b = pos(client, admin, fin, "Manager")
    assert a["access_role_name"] == "Manager" and b["access_role_name"] == "Finance - Manager"
    assert a["access_role_id"] != b["access_role_id"]
    t = tree(client, admin)
    assert len(find_dept(t, "Finance")["positions"]) == 5


def test_admin_role_is_never_adopted_by_a_position_called_admin(client, signup):
    admin = signup()
    d = dept(client, admin, "Board Office")   # (a fresh org already ships a standard "Management")
    p = pos(client, admin, d, "Admin")
    roles = {r["id"]: r["name"] for r in client.get("/api/core/roles", headers=admin).json()}
    assert roles[p["access_role_id"]] != "Admin"
    assert list(roles.values()).count("Admin") == 1


def test_existing_hand_made_role_with_same_name_is_adopted_once(client, signup):
    admin = signup()
    hand = client.post("/api/core/roles", headers=admin, json={"name": "Field Executive"}).json()
    d = dept(client, admin, "Field Sales")
    p1 = pos(client, admin, d, "Field Executive")
    assert p1["access_role_id"] == hand["id"]
    d2 = dept(client, admin, "Retail")
    p2 = pos(client, admin, d2, "Field Executive")
    assert p2["access_role_id"] != hand["id"] and p2["access_role_name"] == "Retail - Field Executive"


def test_chosen_access_role_is_respected_and_unlinked_roles_go_to_other(client, signup):
    admin = signup()
    custom = client.post("/api/core/roles", headers=admin, json={"name": "Viewer"}).json()
    lone = client.post("/api/core/roles", headers=admin, json={"name": "Auditor Lite"}).json()
    d = dept(client, admin, "Sales")
    p = pos(client, admin, d, "Jr Sales Executive", access_role_id=custom["id"])
    assert p["access_role_id"] == custom["id"]
    t = tree(client, admin)
    others = {r["name"] for r in t["other_roles"]}
    assert "Auditor Lite" in others and "Viewer" not in others and "Admin" in others


def test_self_heal_repairs_a_position_without_a_role(client, signup):
    admin = signup()
    d = dept(client, admin, "Finance")
    p = pos(client, admin, d, "Cashier")
    # clearing the link (or an old row from before this feature) is repaired on the next read
    r = client.patch(f"/api/hr/positions/{p['id']}", headers=admin, json={"clear_access_role": True})
    assert r.status_code == 200 and r.json()["access_role_id"]
    t = tree(client, admin)
    assert find_dept(t, "Finance")["positions"][0]["role_id"]


def test_rename_follows_an_unshared_auto_role_but_not_a_shared_one(client, signup):
    admin = signup()
    d = dept(client, admin, "Finance")
    p = pos(client, admin, d, "Cashier")
    r = client.patch(f"/api/hr/positions/{p['id']}", headers=admin, json={"title": "Senior Cashier"})
    assert r.json()["access_role_name"] == "Senior Cashier"
    shared = client.post("/api/core/roles", headers=admin, json={"name": "Shared"}).json()
    q1 = pos(client, admin, d, "A1", access_role_id=shared["id"])
    pos(client, admin, d, "A2", access_role_id=shared["id"])
    r = client.patch(f"/api/hr/positions/{q1['id']}", headers=admin, json={"title": "A1 renamed"})
    assert r.json()["access_role_name"] == "Shared"


def test_hired_employee_login_gets_the_auto_role_and_counts_show_in_tree(client, signup):
    admin = signup()
    d = dept(client, admin, "Finance")
    p = pos(client, admin, d, "Accounts Manager", 50000)
    client.post(f"/api/core/roles/{p['access_role_id']}/permissions", headers=admin, json={"module": "finance", "action": "view"})
    e = client.post("/api/hr/employees", headers=admin, json={"name": "Meera", "department_id": d["id"], "position_id": p["id"]}).json()
    r = client.post(f"/api/hr/employees/{e['id']}/create-login", headers=admin, json={"email": "meera.pr@co.com"})
    assert r.status_code in (200, 201), r.text
    entry = find_dept(tree(client, admin), "Finance")["positions"][0]
    assert entry["employee_count"] == 1 and entry["user_count"] == 1


def test_tree_needs_core_view_and_is_tenant_isolated(client, signup):
    a, b = signup(), signup()
    d = dept(client, a, "Secret Dept")
    pos(client, a, d, "Secret Role")
    names = [x["name"] for x in tree(client, b)["departments"]]
    assert "Secret Dept" not in names
    none_user = make_user(client, a, [], "Nobody")
    assert client.get("/api/core/roles/tree", headers=none_user).status_code == 403
