"""
Locks in a real security fix found through actual deployed use (not
code review) as permanent regression tests. See MANUAL.md's writeup for
the full story - reproduced here as automated tests so a future change
can't silently reopen either hole.
"""
import uuid


def make_role_with_permissions(client, admin_headers, name, permissions):
    """permissions: list of (module, action) tuples."""
    role = client.post("/api/core/roles", headers=admin_headers, json={"name": name}).json()
    for module, action in permissions:
        client.post(f"/api/core/roles/{role['id']}/permissions", headers=admin_headers, json={
            "module": module, "action": action,
        })
    return role


def create_login(client, admin_headers, role_id, email_prefix="user"):
    email = f"{email_prefix}-{uuid.uuid4().hex[:8]}@test.com"
    resp = client.post("/api/core/users", headers=admin_headers, json={
        "name": "Test User", "email": email, "password": "testpass123", "role_id": role_id,
    })
    assert resp.status_code == 201, resp.text
    login = client.post("/api/auth/login", json={"email": email, "password": "testpass123"}).json()
    return {"Authorization": f"Bearer {login['access_token']}"}, resp.json()["id"]


def test_core_edit_alone_cannot_change_a_users_role(client, signup):
    """
    THE core finding: a role with view/edit/approve on every module
    (exactly the 'Secondary_Admin' configuration reported) but no
    manage_access must NOT be able to reassign anyone's role - including
    its own holder's role to Admin.
    """
    admin = signup()
    modules = ["core", "dashboard", "crm", "sales", "procurement", "inventory",
               "finance", "hr", "projects", "documents", "reports", "custom_fields"]
    role = make_role_with_permissions(
        client, admin, "Secondary_Admin",
        [(m, a) for m in modules for a in ("view", "edit", "approve")],
    )
    restricted, restricted_user_id = create_login(client, admin, role["id"], "secondary")

    admin_role_id = next(r["id"] for r in client.get("/api/core/roles", headers=admin).json() if r["name"] == "Admin")

    resp = client.patch(f"/api/core/users/{restricted_user_id}/role", headers=restricted, json={"role_id": admin_role_id})
    assert resp.status_code == 403, f"core.edit alone must not permit a role change, got {resp.status_code}: {resp.text}"


def test_core_edit_alone_cannot_grant_or_revoke_any_permission(client, signup):
    admin = signup()
    role = make_role_with_permissions(client, admin, "Editor Only", [("sales", "view"), ("sales", "edit")])
    restricted, _ = create_login(client, admin, role["id"], "editor")

    resp = client.post(f"/api/core/roles/{role['id']}/permissions", headers=restricted, json={
        "module": "finance", "action": "delete",
    })
    assert resp.status_code == 403


def test_manage_access_role_can_legitimately_change_roles(client, signup):
    """The positive case: a role that DOES hold manage_access can do exactly what Secondary_Admin incorrectly could."""
    admin = signup()
    role = make_role_with_permissions(client, admin, "Real Admin Delegate", [("core", "manage_access"), ("core", "view")])
    delegate, delegate_user_id = create_login(client, admin, role["id"], "delegate")

    other_role = client.post("/api/core/roles", headers=admin, json={"name": "Some Other Role"}).json()
    resp = client.patch(f"/api/core/users/{delegate_user_id}/role", headers=delegate, json={"role_id": other_role["id"]})
    # This demotes the delegate themselves, but the ORIGINAL Admin still
    # exists and still qualifies - so this specific change is legitimate
    # and must succeed.
    assert resp.status_code == 200, resp.text


def test_sole_admin_cannot_demote_themselves(client, signup):
    """THE lockout finding: the last user with manage_access must not be able to remove their own access, even via self-demotion."""
    admin = signup()
    me = client.get("/api/auth/me", headers=admin).json()
    powerless_role = client.post("/api/core/roles", headers=admin, json={"name": "Powerless"}).json()

    resp = client.patch(f"/api/core/users/{me['id']}/role", headers=admin, json={"role_id": powerless_role["id"]})
    assert resp.status_code == 400, f"expected the last-admin guard to block this, got {resp.status_code}"

    # Confirm the role genuinely didn't change, not just that an error was returned.
    users = client.get("/api/core/users", headers=admin).json()
    this_user = next(u for u in users if u["id"] == me["id"])
    assert this_user["role_name"] == "Admin"


def test_sole_manage_access_holder_cannot_revoke_their_own_permission(client, signup):
    """Same invariant, reached via the OTHER route (revoking a permission, not changing a role)."""
    admin = signup()
    me = client.get("/api/auth/me", headers=admin).json()
    admin_role = next(r for r in client.get("/api/core/roles", headers=admin).json() if r["name"] == "Admin")
    perms = client.get(f"/api/core/roles/{admin_role['id']}/permissions", headers=admin).json()
    manage_access_perm = next(p for p in perms if p["action"] == "manage_access")

    resp = client.delete(f"/api/core/roles/{admin_role['id']}/permissions/{manage_access_perm['id']}", headers=admin)
    assert resp.status_code == 400

    # Confirm it's genuinely still there (rollback actually happened, not just an error message).
    perms_after = client.get(f"/api/core/roles/{admin_role['id']}/permissions", headers=admin).json()
    assert any(p["action"] == "manage_access" for p in perms_after)


def test_demotion_succeeds_when_another_admin_equivalent_remains(client, signup):
    """The guard should only block the LAST one - a legitimate demotion with coverage remaining must work."""
    admin = signup()
    me = client.get("/api/auth/me", headers=admin).json()

    delegate_role = make_role_with_permissions(client, admin, "Delegate", [("core", "manage_access"), ("core", "view")])
    delegate, _ = create_login(client, admin, delegate_role["id"], "delegate2")

    powerless_role = client.post("/api/core/roles", headers=admin, json={"name": "Powerless2"}).json()

    # The delegate (who also has manage_access) demotes the original admin - should succeed.
    resp = client.patch(f"/api/core/users/{me['id']}/role", headers=delegate, json={"role_id": powerless_role["id"]})
    assert resp.status_code == 200, resp.text


def test_creating_a_user_with_admin_role_requires_manage_access_not_just_create(client, signup):
    """Closes the sidestep: assigning a powerful role AT creation time must be gated the same as changing it after."""
    admin = signup()
    role = make_role_with_permissions(client, admin, "Create Only", [("core", "create")])
    restricted, _ = create_login(client, admin, role["id"], "creator")

    admin_role_id = next(r["id"] for r in client.get("/api/core/roles", headers=admin).json() if r["name"] == "Admin")
    resp = client.post("/api/core/users", headers=restricted, json={
        "name": "Sneaky New Admin", "email": f"sneaky-{uuid.uuid4().hex[:8]}@test.com",
        "password": "testpass123", "role_id": admin_role_id,
    })
    assert resp.status_code == 403, f"core.create alone must not allow assigning the Admin role at creation, got {resp.status_code}"
