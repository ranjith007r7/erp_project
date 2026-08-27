"""
Locks in this session's three real additions as permanent regression
tests: the audit log actually recording real entity_ids (the flush-
before-log bug found and fixed while building this), multi-tenancy
isolation on the audit log itself, and the two new notification
triggers (payment recorded, PO received) actually firing.
"""


def test_granting_a_permission_creates_a_real_audit_entry_with_a_real_entity_id(client, signup):
    admin = signup()
    role = client.post("/api/core/roles", headers=admin, json={"name": "Test Role"}).json()
    client.post(f"/api/core/roles/{role['id']}/permissions", headers=admin, json={"module": "sales", "action": "view"})

    entries = client.get("/api/core/audit-log", headers=admin).json()
    grant_entries = [e for e in entries if e["action"] == "grant_permission"]
    assert len(grant_entries) == 1
    # The actual regression this locks in: entity_id must be a REAL uuid,
    # not None - a Python-side UUID default only resolves at flush time,
    # and the first draft of this feature logged the ID before flushing.
    assert grant_entries[0]["entity_id"] is not None
    assert grant_entries[0]["user_name"] is not None


def test_audit_log_is_isolated_per_org(client, signup):
    admin_a = signup("Audit Org A")
    admin_b = signup("Audit Org B")

    # Plain role creation is deliberately NOT audit-logged (see roles.py's
    # own module docstring: an empty role with zero permissions is
    # harmless, grants nothing) - use grant_permission instead, which
    # IS wired in, to exercise a real logged action.
    role = client.post("/api/core/roles", headers=admin_a, json={"name": "Org A Role"}).json()
    client.post(f"/api/core/roles/{role['id']}/permissions", headers=admin_a, json={"module": "sales", "action": "view"})

    entries_a = client.get("/api/core/audit-log", headers=admin_a).json()
    entries_b = client.get("/api/core/audit-log", headers=admin_b).json()

    assert len(entries_a) >= 1
    assert len(entries_b) == 0


def test_audit_log_requires_core_view_permission(client, signup):
    import uuid

    admin = signup()
    role = client.post("/api/core/roles", headers=admin, json={"name": "No Access"}).json()
    email = f"restricted-{uuid.uuid4().hex[:8]}@test.com"
    client.post("/api/core/users", headers=admin, json={
        "name": "Restricted", "email": email, "password": "testpass123", "role_id": role["id"],
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "testpass123"}).json()
    restricted = {"Authorization": f"Bearer {login['access_token']}"}

    resp = client.get("/api/core/audit-log", headers=restricted)
    assert resp.status_code == 403


def _create_stocked_product(client, headers, qty=10):
    product = client.post("/api/sales/products", headers=headers, json={"name": "Widget", "unit_price": 1000}).json()
    vendor = client.post("/api/procurement/vendors", headers=headers, json={"name": "Vendor"}).json()
    po = client.post("/api/procurement/purchase-orders", headers=headers, json={
        "vendor_id": vendor["id"], "items": [{"product_id": product["id"], "qty": qty, "unit_price": 500}],
    }).json()
    return product, po


def test_receiving_a_purchase_order_notifies_and_logs(client, signup):
    admin = signup()
    product, po = _create_stocked_product(client, admin)

    before = client.get("/api/notifications/unread-count", headers=admin).json()["unread_count"]
    resp = client.post(f"/api/procurement/purchase-orders/{po['id']}/receive", headers=admin)
    assert resp.status_code == 200
    after = client.get("/api/notifications/unread-count", headers=admin).json()["unread_count"]
    assert after == before + 1

    entries = client.get("/api/core/audit-log", headers=admin).json()
    assert any(e["action"] == "receive_purchase_order" for e in entries)


def test_recording_a_payment_notifies_and_logs(client, signup):
    admin = signup()
    product, po = _create_stocked_product(client, admin)
    client.post(f"/api/procurement/purchase-orders/{po['id']}/receive", headers=admin)

    customer = client.post("/api/sales/customers", headers=admin, json={"name": "Customer"}).json()
    quotation = client.post("/api/sales/quotations", headers=admin, json={
        "customer_id": customer["id"], "items": [{"product_id": product["id"], "qty": 1, "unit_price": 1000}],
    }).json()
    order = client.post(f"/api/sales/quotations/{quotation['id']}/accept", headers=admin).json()
    invoice = client.post(f"/api/sales/orders/{order['id']}/invoice", headers=admin).json()

    before = client.get("/api/notifications/unread-count", headers=admin).json()["unread_count"]
    resp = client.post("/api/finance/payments", headers=admin, json={"invoice_id": invoice["id"], "amount": 1000})
    assert resp.status_code == 201
    after = client.get("/api/notifications/unread-count", headers=admin).json()["unread_count"]
    assert after == before + 1

    entries = client.get("/api/core/audit-log", headers=admin).json()
    assert any(e["action"] == "record_payment" for e in entries)
    assert any(e["action"] == "generate_invoice" for e in entries)
