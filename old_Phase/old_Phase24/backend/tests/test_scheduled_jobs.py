"""
Locks in the scheduled-job endpoints as permanent regression tests -
both the auth gate (these run with no logged-in user, so the usual
JWT-based tests don't apply) and the actual business logic, especially
the "never mutate Invoice.status" decision, since that's the one most
likely to silently regress if someone "cleans up" this code later
without knowing why it was written this way.
"""
from datetime import date, timedelta


def test_scheduled_job_rejects_missing_secret(client):
    resp = client.post("/api/internal/jobs/overdue-invoices")
    assert resp.status_code == 401


def test_scheduled_job_rejects_wrong_secret(client):
    resp = client.post("/api/internal/jobs/overdue-invoices", headers={"X-Cron-Secret": "wrong"})
    assert resp.status_code == 401


def create_overdue_invoice(client, headers, days_overdue=5):
    """Real product -> real stock -> real quotation -> real invoice, then backdate due_date directly."""
    product = client.post("/api/sales/products", headers=headers, json={"name": "Widget", "unit_price": 1000}).json()
    vendor = client.post("/api/procurement/vendors", headers=headers, json={"name": "Vendor"}).json()
    po = client.post("/api/procurement/purchase-orders", headers=headers, json={
        "vendor_id": vendor["id"], "items": [{"product_id": product["id"], "qty": 10, "unit_price": 100}],
    }).json()
    client.post(f"/api/procurement/purchase-orders/{po['id']}/receive", headers=headers)

    customer = client.post("/api/sales/customers", headers=headers, json={"name": "Customer"}).json()
    quotation = client.post("/api/sales/quotations", headers=headers, json={
        "customer_id": customer["id"], "items": [{"product_id": product["id"], "qty": 2, "unit_price": 1000}],
    }).json()
    order = client.post(f"/api/sales/quotations/{quotation['id']}/accept", headers=headers).json()
    invoice = client.post(f"/api/sales/orders/{order['id']}/invoice", headers=headers).json()

    from app.core.database import SessionLocal
    from app.models.sales import Invoice

    db = SessionLocal()
    try:
        inv = db.query(Invoice).filter(Invoice.id == invoice["id"]).first()
        inv.due_date = date.today() - timedelta(days=days_overdue)
        db.commit()
    finally:
        db.close()

    return invoice


def test_overdue_invoice_job_notifies_admin_without_mutating_invoice_status(client, signup, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "CRON_SECRET", "test_secret_for_jobs")

    admin = signup()
    invoice = create_overdue_invoice(client, admin)

    before_count = client.get("/api/notifications/unread-count", headers=admin).json()["unread_count"]

    resp = client.post("/api/internal/jobs/overdue-invoices", headers={"X-Cron-Secret": "test_secret_for_jobs"})
    assert resp.status_code == 200
    assert resp.json()["total_overdue_invoices"] >= 1

    after_count = client.get("/api/notifications/unread-count", headers=admin).json()["unread_count"]
    assert after_count == before_count + 1

    # The core invariant: status must still be "unpaid", never overwritten
    # to "overdue" - both Dashboard and Finance report filter strictly on
    # "unpaid" to build their counts (see the route's own docstring).
    from app.core.database import SessionLocal
    from app.models.sales import Invoice

    db = SessionLocal()
    try:
        inv = db.query(Invoice).filter(Invoice.id == invoice["id"]).first()
        assert inv.status == "unpaid", "the job must never mutate invoice status"
    finally:
        db.close()


def test_overdue_invoice_job_does_not_flag_invoices_not_yet_due(client, signup, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "CRON_SECRET", "test_secret_for_jobs")

    admin = signup()
    # due_date in the FUTURE - not overdue.
    product = client.post("/api/sales/products", headers=admin, json={"name": "Widget", "unit_price": 1000}).json()
    vendor = client.post("/api/procurement/vendors", headers=admin, json={"name": "Vendor"}).json()
    po = client.post("/api/procurement/purchase-orders", headers=admin, json={
        "vendor_id": vendor["id"], "items": [{"product_id": product["id"], "qty": 10, "unit_price": 100}],
    }).json()
    client.post(f"/api/procurement/purchase-orders/{po['id']}/receive", headers=admin)
    customer = client.post("/api/sales/customers", headers=admin, json={"name": "Customer"}).json()
    quotation = client.post("/api/sales/quotations", headers=admin, json={
        "customer_id": customer["id"], "items": [{"product_id": product["id"], "qty": 1, "unit_price": 1000}],
    }).json()
    order = client.post(f"/api/sales/quotations/{quotation['id']}/accept", headers=admin).json()
    client.post(f"/api/sales/orders/{order['id']}/invoice", headers=admin)
    # Not backdated - default due_date (if any) is not in the past.

    before_count = client.get("/api/notifications/unread-count", headers=admin).json()["unread_count"]
    client.post("/api/internal/jobs/overdue-invoices", headers={"X-Cron-Secret": "test_secret_for_jobs"})
    after_count = client.get("/api/notifications/unread-count", headers=admin).json()["unread_count"]

    assert after_count == before_count, "an invoice that isn't actually overdue must not trigger a notification"


def test_weekly_digest_job_runs_successfully(client, signup, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "CRON_SECRET", "test_secret_for_jobs")

    admin = signup()
    resp = client.post("/api/internal/jobs/weekly-digest", headers={"X-Cron-Secret": "test_secret_for_jobs"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["orgs_processed"] >= 1
    assert body["digests_sent"] >= 1
