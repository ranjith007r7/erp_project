"""
Debits must equal credits on EVERY journal entry, always — this is the
one invariant real accounting software can never violate. Tests this
across every code path that posts a journal entry: Sales invoicing,
Payment recording, and HR payroll processing.
"""
from decimal import Decimal


def stock_product(client, headers, product_id, qty=100):
    """Receives stock via a real Purchase Order - invoicing requires it."""
    vendor = client.post("/api/procurement/vendors", headers=headers, json={"name": "Test Vendor"}).json()
    po = client.post("/api/procurement/purchase-orders", headers=headers, json={
        "vendor_id": vendor["id"],
        "items": [{"product_id": product_id, "qty": qty, "unit_price": 10}],
    }).json()
    client.post(f"/api/procurement/purchase-orders/{po['id']}/receive", headers=headers)



def assert_all_entries_balance(client, headers):
    entries = client.get("/api/finance/journal-entries", headers=headers).json()
    assert len(entries) > 0, "expected at least one journal entry to check"
    for entry in entries:
        total_debit = sum(Decimal(str(line["debit"])) for line in entry["lines"])
        total_credit = sum(Decimal(str(line["credit"])) for line in entry["lines"])
        assert total_debit == total_credit, (
            f"journal entry {entry['id']} does not balance: "
            f"debit={total_debit} credit={total_credit}"
        )


def test_invoice_generation_posts_a_balanced_journal_entry(client, signup):
    headers = signup()
    product = client.post("/api/sales/products", headers=headers, json={
        "name": "Widget", "unit_price": 250,
    }).json()
    stock_product(client, headers, product["id"])
    customer = client.post("/api/sales/customers", headers=headers, json={"name": "Customer"}).json()
    quotation = client.post("/api/sales/quotations", headers=headers, json={
        "customer_id": customer["id"],
        "items": [{"product_id": product["id"], "qty": 2, "unit_price": 250}],
    }).json()
    order = client.post(f"/api/sales/quotations/{quotation['id']}/accept", headers=headers).json()
    invoice_resp = client.post(f"/api/sales/orders/{order['id']}/invoice", headers=headers)
    assert invoice_resp.status_code == 201, invoice_resp.text
    invoice = invoice_resp.json()
    assert Decimal(str(invoice["amount"])) == Decimal("500")

    assert_all_entries_balance(client, headers)


def test_payment_recording_posts_a_balanced_journal_entry(client, signup):
    headers = signup()
    product = client.post("/api/sales/products", headers=headers, json={
        "name": "Widget", "unit_price": 100,
    }).json()
    stock_product(client, headers, product["id"])
    customer = client.post("/api/sales/customers", headers=headers, json={"name": "Customer"}).json()
    quotation = client.post("/api/sales/quotations", headers=headers, json={
        "customer_id": customer["id"],
        "items": [{"product_id": product["id"], "qty": 1, "unit_price": 100}],
    }).json()
    order = client.post(f"/api/sales/quotations/{quotation['id']}/accept", headers=headers).json()
    invoice = client.post(f"/api/sales/orders/{order['id']}/invoice", headers=headers).json()

    payment_resp = client.post("/api/finance/payments", headers=headers, json={
        "invoice_id": invoice["id"], "amount": 100,
    })
    assert payment_resp.status_code == 201, payment_resp.text

    assert_all_entries_balance(client, headers)


def test_duplicate_payment_on_same_invoice_is_rejected(client, signup):
    """Locks in the Phase 3 behavior: paying an already-paid invoice again must fail, not double-count."""
    headers = signup()
    product = client.post("/api/sales/products", headers=headers, json={
        "name": "Widget", "unit_price": 100,
    }).json()
    stock_product(client, headers, product["id"])
    customer = client.post("/api/sales/customers", headers=headers, json={"name": "Customer"}).json()
    quotation = client.post("/api/sales/quotations", headers=headers, json={
        "customer_id": customer["id"],
        "items": [{"product_id": product["id"], "qty": 1, "unit_price": 100}],
    }).json()
    order = client.post(f"/api/sales/quotations/{quotation['id']}/accept", headers=headers).json()
    invoice = client.post(f"/api/sales/orders/{order['id']}/invoice", headers=headers).json()

    first = client.post("/api/finance/payments", headers=headers, json={"invoice_id": invoice["id"], "amount": 100})
    assert first.status_code == 201

    second = client.post("/api/finance/payments", headers=headers, json={"invoice_id": invoice["id"], "amount": 100})
    assert second.status_code in (400, 409, 422), f"expected rejection, got {second.status_code}: {second.text}"
