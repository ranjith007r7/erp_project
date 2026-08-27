"""
Regression tests for this phase's three extensions: search's full-results
mode, Documents bulk delete, and Employee CSV import/export (including
the department-name lookup, which is genuinely different from Leads'
plain-column import).
"""
import io


# ---------------- Search full mode ----------------

def test_search_full_mode_returns_more_than_default_cap(client, signup):
    admin = signup()
    for i in range(8):
        client.post("/api/crm/leads", headers=admin, json={"name": f"Zeta Lead {i}", "source": "Website"})

    default_results = client.get("/api/search?q=Zeta", headers=admin).json()["results"]
    full_results = client.get("/api/search?q=Zeta&full=true", headers=admin).json()["results"]

    assert len(default_results) == 5  # RESULTS_PER_TYPE
    assert len(full_results) == 8


# ---------------- Documents bulk delete ----------------

def test_documents_bulk_delete_reports_deleted_and_not_found(client, signup):
    admin = signup()
    d1 = client.post("/api/documents", headers=admin, json={"title": "Doc 1", "file_url": "https://example.com/a.pdf"}).json()
    d2 = client.post("/api/documents", headers=admin, json={"title": "Doc 2", "file_url": "https://example.com/b.pdf"}).json()
    fake_id = "00000000-0000-0000-0000-000000000000"

    resp = client.post("/api/documents/bulk-delete", headers=admin, json={"ids": [d1["id"], d2["id"], fake_id]})
    body = resp.json()
    assert set(body["deleted"]) == {d1["id"], d2["id"]}
    assert body["not_found"] == [fake_id]

    remaining = client.get("/api/documents", headers=admin).json()
    assert remaining == []


def test_document_delete_requires_documents_delete_permission(client, signup):
    import uuid
    admin = signup()
    role = client.post("/api/core/roles", headers=admin, json={"name": "View Only Docs"}).json()
    client.post(f"/api/core/roles/{role['id']}/permissions", headers=admin, json={"module": "documents", "action": "view"})
    email = f"docviewer-{uuid.uuid4().hex[:8]}@test.com"
    client.post("/api/core/users", headers=admin, json={"name": "Viewer", "email": email, "password": "testpass123", "role_id": role["id"]})
    login = client.post("/api/auth/login", json={"email": email, "password": "testpass123"}).json()
    restricted = {"Authorization": f"Bearer {login['access_token']}"}

    resp = client.post("/api/documents/bulk-delete", headers=restricted, json={"ids": ["00000000-0000-0000-0000-000000000000"]})
    assert resp.status_code == 403


# ---------------- Employee CSV import/export ----------------

def test_employee_import_looks_up_department_by_name(client, signup):
    admin = signup()
    dept = client.post("/api/hr/departments", headers=admin, json={"name": "Engineering"}).json()

    csv_content = "name,designation,department_name,salary\nAlice,Engineer,Engineering,80000\n"
    resp = client.post(
        "/api/hr/employees/import", headers=admin,
        files={"file": ("employees.csv", io.BytesIO(csv_content.encode()), "text/csv")},
    )
    assert resp.json()["imported"] == 1

    employees = client.get("/api/hr/employees", headers=admin).json()
    assert employees[0]["department_id"] == dept["id"]


def test_employee_import_unmatched_department_does_not_fail_the_row(client, signup):
    """A real, deliberate design decision: an unrecognized department name leaves the employee unassigned, not rejected."""
    admin = signup()
    csv_content = "name,department_name\nBob,Nonexistent Department\n"
    resp = client.post(
        "/api/hr/employees/import", headers=admin,
        files={"file": ("employees.csv", io.BytesIO(csv_content.encode()), "text/csv")},
    )
    body = resp.json()
    assert body["imported"] == 1
    assert body["failed"] == 0

    employees = client.get("/api/hr/employees", headers=admin).json()
    assert employees[0]["department_id"] is None


def test_employee_import_rejects_invalid_salary_but_not_the_whole_file(client, signup):
    admin = signup()
    csv_content = "name,salary\nGood Employee,50000\nBad Employee,not-a-number\n"
    resp = client.post(
        "/api/hr/employees/import", headers=admin,
        files={"file": ("employees.csv", io.BytesIO(csv_content.encode()), "text/csv")},
    )
    body = resp.json()
    assert body["imported"] == 1
    assert body["failed"] == 1
    assert body["errors"][0]["row"] == 3


def test_employee_csv_export_contains_real_data(client, signup):
    admin = signup()
    client.post("/api/hr/employees", headers=admin, json={"name": "Export Test", "designation": "Rep", "salary": 45000})

    resp = client.get("/api/hr/employees/export", headers=admin)
    assert resp.status_code == 200
    assert "Export Test" in resp.text
    assert "45000" in resp.text
