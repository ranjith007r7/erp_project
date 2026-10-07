"""Payment modes (cash / card / gpay), mandatory transaction IDs, and readable journal numbers."""
import uuid

from test_procurement_workflow import make_user  # reuse the role+user helper


def _invoice(client, headers, amount=1000):
    product = client.post("/api/sales/products", headers=headers, json={"name": "Item", "unit_price": amount, "sku": uuid.uuid4().hex[:6]}).json()
    vendor = client.post("/api/procurement/vendors", headers=headers, json={"name": "V"}).json()
    po = client.post("/api/procurement/purchase-orders", headers=headers, json={
        "vendor_id": vendor["id"], "items": [{"product_id": product["id"], "qty": 5, "unit_price": 10}]}).json()
    from conftest import receive_po
    receive_po(client, headers, po["id"])  # stock must exist before it can be invoiced
    customer = client.post("/api/sales/customers", headers=headers, json={"name": "Cust"}).json()
    q = client.post("/api/sales/quotations", headers=headers, json={
        "customer_id": customer["id"], "items": [{"product_id": product["id"], "qty": 1, "unit_price": amount}]}).json()
    order = client.post(f"/api/sales/quotations/{q['id']}/accept", headers=headers).json()
    inv = client.post(f"/api/sales/orders/{order['id']}/invoice", headers=headers)
    assert inv.status_code == 201, inv.text
    return inv.json()


def pay(client, headers, inv, **kw):
    return client.post("/api/finance/payments", headers=headers, json={"invoice_id": inv["id"], "amount": inv["amount"], **kw})


def test_cash_needs_no_transaction_id(client, signup):
    h = signup()
    inv = _invoice(client, h)
    r = pay(client, h, inv, method="cash", transaction_id="ignored-for-cash")
    assert r.status_code == 201, r.text
    assert r.json()["method"] == "cash" and r.json()["transaction_id"] is None


def test_default_method_is_cash(client, signup):
    h = signup()
    r = pay(client, h, _invoice(client, h))
    assert r.status_code == 201 and r.json()["method"] == "cash"


def test_card_and_gpay_require_a_transaction_id_and_record_nothing_without_it(client, signup):
    h = signup()
    for method, label in (("card", "card"), ("gpay", "GPay")):
        inv = _invoice(client, h)
        r = pay(client, h, inv, method=method)
        assert r.status_code == 400 and label in r.json()["detail"] and "transaction ID" in r.json()["detail"]
        r = pay(client, h, inv, method=method, transaction_id="   ")
        assert r.status_code == 400
        r = pay(client, h, inv, method=method, transaction_id="ab")
        assert r.status_code == 400
        # nothing was recorded: invoice still unpaid, no payment, no journal entry for it
        assert [i for i in client.get("/api/sales/invoices", headers=h).json() if i["id"] == inv["id"]][0]["status"] != "paid"
        assert pay(client, h, inv, method=method, transaction_id=f"UPI-{method}-123456").status_code == 201


def test_payment_with_txn_is_stored_listed_and_journalled_with_a_readable_number(client, signup):
    h = signup()
    inv = _invoice(client, h)
    r = pay(client, h, inv, method="gpay", transaction_id="T2610071234")
    assert r.status_code == 201 and r.json()["transaction_id"] == "T2610071234" and r.json()["method"] == "gpay"
    listed = client.get("/api/finance/payments", headers=h).json()
    assert listed[0]["transaction_id"] == "T2610071234" and listed[0]["method"] == "gpay"
    entries = client.get("/api/finance/journal-entries", headers=h).json()
    pmt = [e for e in entries if e["reference"].startswith("PMT-")][0]
    assert "GPay" in pmt["description"] and "T2610071234" in pmt["description"]
    numbers = [e["entry_number"] for e in entries]
    assert all(n and n.startswith("JE-") for n in numbers) and len(set(numbers)) == len(numbers)


def test_journal_numbers_run_in_order_per_org(client, signup):
    a, b = signup(), signup()
    inv = _invoice(client, a)
    pay(client, a, inv)
    nums_a = sorted(e["entry_number"] for e in client.get("/api/finance/journal-entries", headers=a).json())
    assert nums_a == ["JE-0001", "JE-0002"]
    _invoice(client, b)
    assert [e["entry_number"] for e in client.get("/api/finance/journal-entries", headers=b).json()] == ["JE-0001"]


def test_same_transaction_id_cannot_pay_two_invoices(client, signup):
    h = signup()
    i1, i2 = _invoice(client, h), _invoice(client, h)
    assert pay(client, h, i1, method="card", transaction_id="AUTH-998877").status_code == 201
    r = pay(client, h, i2, method="card", transaction_id="AUTH-998877")
    assert r.status_code == 400 and "already recorded" in r.json()["detail"]


def test_same_transaction_id_is_allowed_in_a_different_org(client, signup):
    a, b = signup(), signup()
    assert pay(client, a, _invoice(client, a), method="gpay", transaction_id="SHARED-0001").status_code == 201
    assert pay(client, b, _invoice(client, b), method="gpay", transaction_id="SHARED-0001").status_code == 201


def test_unknown_method_rejected_and_permissions_enforced(client, signup):
    h = signup()
    inv = _invoice(client, h)
    assert pay(client, h, inv, method="bitcoin").status_code == 422
    viewer = make_user(client, h, [("finance", "view")])
    assert pay(client, viewer, inv, method="cash").status_code == 403
    assert client.get("/api/finance/payments", headers=viewer).status_code == 200


def test_payments_list_is_org_scoped(client, signup):
    a, b = signup(), signup()
    pay(client, a, _invoice(client, a))
    assert client.get("/api/finance/payments", headers=b).json() == []
