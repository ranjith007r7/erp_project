"""
Regression tests for global search, bulk delete, bulk role assignment,
and CSV import/export. TestClient runs FastAPI in-process, so these
don't depend on a live background server the way manual curl testing
does - a more reliable way to lock in correctness regardless of
environment conditions.
"""
import io
import uuid


# ---------------- Global Search ----------------

def test_search_respects_rbac_per_module(client, signup):
    """The core security property: a restricted role must not see results from modules it can't view."""
    admin = signup()
    client.post("/api/crm/leads", headers=admin, json={"name": "Zephyr Lead", "source": "Website"})
    client.post("/api/hr/employees", headers=admin, json={"name": "Zephyr Employee", "salary": 50000})
    client.post("/api/sales/products", headers=admin, json={"name": "Zephyr Product", "unit_price": 100})

    admin_results = client.get("/api/search?q=Zephyr", headers=admin).json()["results"]
    assert {r["type"] for r in admin_results} == {"lead", "employee", "product"}

    role = client.post("/api/core/roles", headers=admin, json={"name": "Sales Only"}).json()
    client.post(f"/api/core/roles/{role['id']}/permissions", headers=admin, json={"module": "sales", "action": "view"})
    email = f"salesonly-{uuid.uuid4().hex[:8]}@test.com"
    client.post("/api/core/users", headers=admin, json={
        "name": "Sales Only User", "email": email, "password": "testpass123", "role_id": role["id"],
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "testpass123"}).json()
    restricted = {"Authorization": f"Bearer {login['access_token']}"}

    restricted_results = client.get("/api/search?q=Zephyr", headers=restricted).json()["results"]
    assert {r["type"] for r in restricted_results} == {"product"}


def test_admin_sees_search_results_even_with_zero_permission_rows_for_that_module(client, signup):
    """Admin's self-heal only fires through require_permission()'s dependency path - search bypasses that, so Admin needs its own bypass by role name."""
    from app.core.database import SessionLocal
    from app.models.role import Permission, Role

    admin = signup()
    client.post("/api/documents", headers=admin, json={"title": "Zeta Contract", "file_url": "https://example.com/x.pdf"})

    db = SessionLocal()
    try:
        admin_role = db.query(Role).filter(Role.name == "Admin").first()
        db.query(Permission).filter(Permission.role_id == admin_role.id, Permission.module == "documents").delete()
        db.commit()
    finally:
        db.close()

    results = client.get("/api/search?q=Zeta", headers=admin).json()["results"]
    assert any(r["type"] == "document" for r in results)


def test_search_is_isolated_per_org(client, signup):
    admin_a = signup("Search Org A")
    admin_b = signup("Search Org B")
    client.post("/api/crm/leads", headers=admin_a, json={"name": "OnlyInA", "source": "Website"})

    results_b = client.get("/api/search?q=OnlyInA", headers=admin_b).json()["results"]
    assert results_b == []


# ---------------- Bulk Delete ----------------

def test_bulk_delete_reports_deleted_and_not_found_separately(client, signup):
    admin = signup()
    lead1 = client.post("/api/crm/leads", headers=admin, json={"name": "Lead 1", "source": "Website"}).json()
    lead2 = client.post("/api/crm/leads", headers=admin, json={"name": "Lead 2", "source": "Website"}).json()
    fake_id = "00000000-0000-0000-0000-000000000000"

    resp = client.post("/api/crm/leads/bulk-delete", headers=admin, json={"ids": [lead1["id"], lead2["id"], fake_id]})
    body = resp.json()
    assert set(body["deleted"]) == {lead1["id"], lead2["id"]}
    assert body["not_found"] == [fake_id]

    remaining = client.get("/api/crm/leads", headers=admin).json()
    assert remaining == []


def test_bulk_delete_requires_crm_delete_permission(client, signup):
    admin = signup()
    role = client.post("/api/core/roles", headers=admin, json={"name": "View Only"}).json()
    client.post(f"/api/core/roles/{role['id']}/permissions", headers=admin, json={"module": "crm", "action": "view"})
    email = f"viewonly-{uuid.uuid4().hex[:8]}@test.com"
    client.post("/api/core/users", headers=admin, json={
        "name": "Viewer", "email": email, "password": "testpass123", "role_id": role["id"],
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "testpass123"}).json()
    restricted = {"Authorization": f"Bearer {login['access_token']}"}

    resp = client.post("/api/crm/leads/bulk-delete", headers=restricted, json={"ids": ["00000000-0000-0000-0000-000000000000"]})
    assert resp.status_code == 403


# ---------------- Bulk Role Assignment (the RBAC-sensitive one) ----------------

def test_bulk_role_assign_succeeds_when_admin_coverage_remains(client, signup):
    admin = signup()
    me = client.get("/api/auth/me", headers=admin).json()

    second_role = client.post("/api/core/roles", headers=admin, json={"name": "Second Admin"}).json()
    client.post(f"/api/core/roles/{second_role['id']}/permissions", headers=admin, json={"module": "core", "action": "manage_access"})
    email = f"second-{uuid.uuid4().hex[:8]}@test.com"
    client.post("/api/core/users", headers=admin, json={
        "name": "Second Admin", "email": email, "password": "testpass123", "role_id": second_role["id"],
    })

    powerless = client.post("/api/core/roles", headers=admin, json={"name": "Powerless"}).json()
    resp = client.post("/api/core/users/bulk-role-assign", headers=admin, json={
        "user_ids": [me["id"]], "role_id": powerless["id"],
    })
    body = resp.json()
    assert me["id"] in body["updated"]
    assert body["skipped"] == []


def test_bulk_role_assign_skips_change_that_would_leave_zero_admins(client, signup):
    """The real regression this locks in: the sole remaining admin-equivalent must be SKIPPED, not silently demoted, in a bulk batch."""
    admin = signup()
    me = client.get("/api/auth/me", headers=admin).json()
    powerless = client.post("/api/core/roles", headers=admin, json={"name": "Powerless"}).json()

    resp = client.post("/api/core/users/bulk-role-assign", headers=admin, json={
        "user_ids": [me["id"]], "role_id": powerless["id"],
    })
    body = resp.json()
    assert body["updated"] == []
    assert len(body["skipped"]) == 1
    assert "no admin-equivalent" in body["skipped"][0]["reason"]

    from app.core.database import SessionLocal
    from app.models.user import User
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == me["id"]).first()
        role_name = user.role.name if user.role else None
        assert role_name == "Admin", "the sole admin's role must genuinely be unchanged after being skipped"
    finally:
        db.close()


# ---------------- CSV Export / Import ----------------

def test_csv_export_contains_real_lead_data(client, signup):
    admin = signup()
    client.post("/api/crm/leads", headers=admin, json={"name": "Export Test Lead", "company_name": "Acme", "source": "Website"})

    resp = client.get("/api/crm/leads/export", headers=admin)
    assert resp.status_code == 200
    assert "Export Test Lead" in resp.text
    assert "Acme" in resp.text


def test_csv_import_partial_success_with_per_row_errors(client, signup):
    admin = signup()
    csv_content = "name,company_name\nValid Lead A,Corp A\n,Missing Name Corp\nValid Lead B,Corp B\n"

    resp = client.post(
        "/api/crm/leads/import", headers=admin,
        files={"file": ("leads.csv", io.BytesIO(csv_content.encode()), "text/csv")},
    )
    body = resp.json()
    assert body["imported"] == 2
    assert body["failed"] == 1
    assert body["errors"][0]["row"] == 3  # header is row 1, so the blank-name row is row 3

    leads = client.get("/api/crm/leads", headers=admin).json()
    assert len(leads) == 2  # confirms the bad row was genuinely never persisted, not just reported as failed


def test_csv_import_rejects_missing_name_column(client, signup):
    admin = signup()
    csv_content = "company_name\nSome Corp\n"
    resp = client.post(
        "/api/crm/leads/import", headers=admin,
        files={"file": ("leads.csv", io.BytesIO(csv_content.encode()), "text/csv")},
    )
    assert resp.status_code == 400


def test_csv_import_rejects_files_over_the_row_cap(client, signup):
    admin = signup()
    rows = "\n".join(f"Lead {i}" for i in range(1001))
    csv_content = f"name\n{rows}\n"
    resp = client.post(
        "/api/crm/leads/import", headers=admin,
        files={"file": ("leads.csv", io.BytesIO(csv_content.encode()), "text/csv")},
    )
    assert resp.status_code == 400


def test_csv_import_requires_crm_create_permission(client, signup):
    admin = signup()
    role = client.post("/api/core/roles", headers=admin, json={"name": "View Only Import"}).json()
    client.post(f"/api/core/roles/{role['id']}/permissions", headers=admin, json={"module": "crm", "action": "view"})
    email = f"importviewer-{uuid.uuid4().hex[:8]}@test.com"
    client.post("/api/core/users", headers=admin, json={
        "name": "Viewer", "email": email, "password": "testpass123", "role_id": role["id"],
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "testpass123"}).json()
    restricted = {"Authorization": f"Bearer {login['access_token']}"}

    csv_content = "name\nSome Lead\n"
    resp = client.post(
        "/api/crm/leads/import", headers=restricted,
        files={"file": ("leads.csv", io.BytesIO(csv_content.encode()), "text/csv")},
    )
    assert resp.status_code == 403
