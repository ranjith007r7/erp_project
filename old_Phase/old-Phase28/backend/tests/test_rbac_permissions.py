"""
Locks in Phase 11's RBAC enforcement as a permanent regression test —
without this, a future change could silently reintroduce "any logged-in
user can do anything" and nothing would catch it until a demo.
"""


def create_restricted_user(client, admin_headers, module, action, email_prefix="viewer"):
    """Creates a role with exactly one permission, a user with that role, and logs them in."""
    import uuid
    unique = uuid.uuid4().hex[:8]

    role = client.post("/api/core/roles", headers=admin_headers, json={"name": f"Restricted {unique}"}).json()
    client.post(f"/api/core/roles/{role['id']}/permissions", headers=admin_headers, json={
        "module": module, "action": action,
    })
    email = f"{email_prefix}-{unique}@test.com"
    client.post("/api/core/users", headers=admin_headers, json={
        "name": "Restricted User", "email": email, "password": "restrictedpass123", "role_id": role["id"],
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "restrictedpass123"}).json()
    return {"Authorization": f"Bearer {login['access_token']}"}


def test_view_only_role_can_view_but_not_create(client, signup):
    admin = signup()
    restricted = create_restricted_user(client, admin, module="sales", action="view")

    view_resp = client.get("/api/sales/products", headers=restricted)
    assert view_resp.status_code == 200

    create_resp = client.post("/api/sales/products", headers=restricted, json={"name": "Should Fail", "unit_price": 50})
    assert create_resp.status_code == 403, create_resp.text


def test_restricted_role_has_zero_access_to_unrelated_modules(client, signup):
    admin = signup()
    restricted = create_restricted_user(client, admin, module="sales", action="view")

    resp = client.get("/api/hr/employees", headers=restricted)
    assert resp.status_code == 403, "a role granted ONLY sales.view must not be able to see HR data"


def test_restricted_role_cannot_manage_roles_or_users(client, signup):
    admin = signup()
    restricted = create_restricted_user(client, admin, module="sales", action="view")

    resp = client.get("/api/core/users", headers=restricted)
    assert resp.status_code == 403, "a role with no 'core' permissions must not be able to list org users"


def test_admin_role_retains_full_access(client, signup):
    """The Admin role itself must never be accidentally restricted by this system."""
    admin = signup()
    view_resp = client.get("/api/sales/products", headers=admin)
    create_resp = client.post("/api/sales/products", headers=admin, json={"name": "Admin Product", "unit_price": 100})
    assert view_resp.status_code == 200
    assert create_resp.status_code == 201


def test_admin_role_self_heals_missing_permissions_for_a_module(client, signup):
    """
    Regression test for the real bug found in Phase 11: an org whose
    Admin role predates a module (simulated here by directly deleting
    its permission rows) must self-heal on first access, not lock the
    admin out permanently.
    """
    admin = signup()

    # Confirm access works normally first.
    assert client.get("/api/custom-fields", headers=admin).status_code == 200

    # Simulate an "old org" by deleting this org's Admin custom_fields rows directly.
    from app.core.database import SessionLocal
    from app.models.role import Role, Permission
    from app.core.security import decode_access_token

    token = admin["Authorization"].split(" ")[1]
    payload = decode_access_token(token)
    org_id = payload["org_id"]

    db = SessionLocal()
    try:
        role = db.query(Role).filter(Role.org_id == org_id, Role.name == "Admin").first()
        db.query(Permission).filter(Permission.role_id == role.id, Permission.module == "custom_fields").delete()
        db.commit()

        remaining = db.query(Permission).filter(Permission.role_id == role.id, Permission.module == "custom_fields").count()
        assert remaining == 0, "setup failed: rows should be deleted before testing self-heal"
    finally:
        db.close()

    # Should self-heal and succeed, not 403.
    resp = client.get("/api/custom-fields", headers=admin)
    assert resp.status_code == 200, f"expected self-heal to restore access, got {resp.status_code}"

    # Confirm it actually wrote exactly 5 rows (one per action), not zero, not duplicates.
    db = SessionLocal()
    try:
        role = db.query(Role).filter(Role.org_id == org_id, Role.name == "Admin").first()
        count = db.query(Permission).filter(Permission.role_id == role.id, Permission.module == "custom_fields").count()
        assert count == 5, f"expected exactly 5 self-healed permission rows, found {count}"
    finally:
        db.close()
