"""
Locks in the document upload/download feature as permanent regression
tests. R2 itself isn't reachable with real credentials in this test
environment (same category boundary as Resend for email - see
test_resend_verification.py's fallback pattern), so these focus on
everything provable without a real upload actually completing: request
validation (runs before storage.py is ever touched), the existing
paste-a-URL flow staying untouched, and the multi-tenancy boundary on
downloads, which 404s from the org_id filter before storage.py is
reached at all.
"""
import io


def test_existing_json_document_creation_is_unaffected(client, signup):
    """The original flow (paste a URL) must work exactly as before - this feature was additive, not a replacement."""
    admin = signup()
    resp = client.post("/api/documents", headers=admin, json={
        "title": "External Link Doc", "file_url": "https://example.com/file.pdf",
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["file_url"] == "https://example.com/file.pdf"
    assert body["storage_key"] is None


def test_upload_without_r2_configured_returns_clean_503_not_a_crash(client, signup):
    admin = signup()
    resp = client.post(
        "/api/documents/upload",
        headers=admin,
        data={"title": "Test Doc"},
        files={"file": ("test.pdf", io.BytesIO(b"fake pdf content"), "application/pdf")},
    )
    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"].lower()


def test_upload_rejects_disallowed_file_type_before_touching_storage(client, signup, monkeypatch):
    from app.core.config import settings
    # Configure R2 (fake values) to prove the type check runs BEFORE any
    # real storage call would be attempted - if this test reached
    # storage.py's upload_file(), it would hang or fail on network I/O
    # rather than returning cleanly, so a fast, clean 400 here proves
    # the ordering is correct.
    monkeypatch.setattr(settings, "R2_ACCOUNT_ID", "fake")
    monkeypatch.setattr(settings, "R2_ACCESS_KEY_ID", "fake")
    monkeypatch.setattr(settings, "R2_SECRET_ACCESS_KEY", "fake")
    monkeypatch.setattr(settings, "R2_BUCKET_NAME", "fake")

    admin = signup()
    resp = client.post(
        "/api/documents/upload",
        headers=admin,
        data={"title": "Bad File"},
        files={"file": ("virus.exe", io.BytesIO(b"fake exe content"), "application/x-msdownload")},
    )
    assert resp.status_code == 400
    assert "not allowed" in resp.json()["detail"].lower()


def test_upload_rejects_oversized_file_before_touching_storage(client, signup, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "R2_ACCOUNT_ID", "fake")
    monkeypatch.setattr(settings, "R2_ACCESS_KEY_ID", "fake")
    monkeypatch.setattr(settings, "R2_SECRET_ACCESS_KEY", "fake")
    monkeypatch.setattr(settings, "R2_BUCKET_NAME", "fake")
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)  # tighten the limit so the test file is fast to build

    admin = signup()
    oversized_content = b"x" * (2 * 1024 * 1024)  # 2MB against a 1MB limit
    resp = client.post(
        "/api/documents/upload",
        headers=admin,
        data={"title": "Big File"},
        files={"file": ("big.pdf", io.BytesIO(oversized_content), "application/pdf")},
    )
    assert resp.status_code == 400
    assert "exceeds" in resp.json()["detail"].lower()


def test_upload_requires_documents_create_permission(client, signup):
    """Same RBAC gate as the existing JSON document-creation route."""
    import uuid

    admin = signup()
    role = client.post("/api/core/roles", headers=admin, json={"name": "No Docs Access"}).json()
    email = f"restricted-{uuid.uuid4().hex[:8]}@test.com"
    client.post("/api/core/users", headers=admin, json={
        "name": "Restricted", "email": email, "password": "testpass123", "role_id": role["id"],
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "testpass123"}).json()
    restricted = {"Authorization": f"Bearer {login['access_token']}"}

    resp = client.post(
        "/api/documents/upload",
        headers=restricted,
        data={"title": "Should Fail"},
        files={"file": ("test.pdf", io.BytesIO(b"content"), "application/pdf")},
    )
    assert resp.status_code == 403


def test_org_b_cannot_download_org_as_document(client, signup):
    """
    The real access-control boundary: this 404s from the org_id filter
    in the query itself, before storage.py or any real R2 call is ever
    reached - so this is fully testable without real credentials, and
    is the actual security-relevant check, not the storage key's
    org-scoped prefix (which is just human-readable organization).
    """
    from app.core.database import SessionLocal
    from app.models.documents import Document
    import uuid as uuid_module

    admin_a = signup("Doc Org A")
    admin_b = signup("Doc Org B")

    me_a = client.get("/api/auth/me", headers=admin_a).json()

    db = SessionLocal()
    try:
        doc = Document(
            id=uuid_module.uuid4(), org_id=me_a["org_id"], title="Org A Secret Doc",
            storage_key=f"{me_a['org_id']}/fake-key.pdf",
        )
        db.add(doc)
        db.commit()
        doc_id = str(doc.id)
    finally:
        db.close()

    resp_b = client.get(f"/api/documents/{doc_id}/download", headers=admin_b)
    assert resp_b.status_code == 404

    # Org A itself gets PAST the org check (proven by reaching the
    # storage-config error instead of a 404) - confirms the block above
    # was genuinely about org ownership, not a broken route.
    resp_a = client.get(f"/api/documents/{doc_id}/download", headers=admin_a)
    assert resp_a.status_code in (503, 502), "Org A should pass the ownership check and reach the storage layer"
