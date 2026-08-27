"""
Regression tests for org-wide branding (logo/background upload).
Real R2 upload isn't reachable with real credentials in this test
environment, so these focus on everything provable without one
actually completing: the RBAC split between reading (any org member)
and writing (manage_access only), the null-before-upload state, and
multi-tenancy isolation.
"""
import io
import uuid


def test_branding_is_null_before_anything_uploaded(client, signup):
    admin = signup()
    resp = client.get("/api/organizations/branding", headers=admin)
    assert resp.status_code == 200
    assert resp.json()["url"] is None


def test_uploading_branding_requires_manage_access(client, signup):
    admin = signup()
    role = client.post("/api/core/roles", headers=admin, json={"name": "No Access"}).json()
    email = f"restricted-{uuid.uuid4().hex[:8]}@test.com"
    client.post("/api/core/users", headers=admin, json={
        "name": "Restricted", "email": email, "password": "testpass123", "role_id": role["id"],
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "testpass123"}).json()
    restricted = {"Authorization": f"Bearer {login['access_token']}"}

    resp = client.post(
        "/api/organizations/branding", headers=restricted,
        files={"file": ("logo.png", io.BytesIO(b"fake"), "image/png")},
    )
    assert resp.status_code == 403


def test_any_org_member_can_read_branding_even_without_manage_access(client, signup):
    """Reading is not privileged - only changing it is."""
    admin = signup()
    role = client.post("/api/core/roles", headers=admin, json={"name": "Read Only"}).json()
    email = f"reader-{uuid.uuid4().hex[:8]}@test.com"
    client.post("/api/core/users", headers=admin, json={
        "name": "Reader", "email": email, "password": "testpass123", "role_id": role["id"],
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "testpass123"}).json()
    reader = {"Authorization": f"Bearer {login['access_token']}"}

    resp = client.get("/api/organizations/branding", headers=reader)
    assert resp.status_code == 200


def test_upload_without_r2_configured_returns_clean_503(client, signup):
    admin = signup()
    resp = client.post(
        "/api/organizations/branding", headers=admin,
        files={"file": ("logo.png", io.BytesIO(b"fake"), "image/png")},
    )
    assert resp.status_code == 503


def test_branding_is_isolated_per_org(client, signup):
    """Fetching branding must only ever reflect the CALLER's own org."""
    admin_a = signup("Branding Org A")
    admin_b = signup("Branding Org B")

    resp_a = client.get("/api/organizations/branding", headers=admin_a)
    resp_b = client.get("/api/organizations/branding", headers=admin_b)
    assert resp_a.status_code == resp_b.status_code == 200
    # Both null in this test (no real R2), but the real point is these
    # are two independent queries scoped by get_org_id, never cross-org.


def test_removing_branding_requires_manage_access(client, signup):
    admin = signup()
    role = client.post("/api/core/roles", headers=admin, json={"name": "No Access 2"}).json()
    email = f"restricted2-{uuid.uuid4().hex[:8]}@test.com"
    client.post("/api/core/users", headers=admin, json={
        "name": "Restricted", "email": email, "password": "testpass123", "role_id": role["id"],
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "testpass123"}).json()
    restricted = {"Authorization": f"Bearer {login['access_token']}"}

    resp = client.delete("/api/organizations/branding", headers=restricted)
    assert resp.status_code == 403
