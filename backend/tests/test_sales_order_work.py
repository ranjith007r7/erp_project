"""A Sales-accepted quotation opens a 'Sales order' work that follows the Sales invoice and the Finance payment."""
import uuid

W = "/api/workpage/works"
REC = "/api/finance/work-reconciliation"


def _sale(client, admin, qty=3, price=100):
    prod = client.post("/api/sales/products", headers=admin, json={"name": f"Panel {uuid.uuid4().hex[:4]}", "unit_price": price}).json()
    r = client.post("/api/stockin/batches", headers=admin, json={"product_id": prod["id"], "quantity": 10, "vendor_name": "SunVolt",
                                                                 "vendor_amount": 60, "mrp": 200, "max_discount_percent": 50})
    assert r.status_code == 201, r.text
    cust = client.post("/api/sales/customers", headers=admin, json={"name": "Anita"}).json()
    q = client.post("/api/sales/quotations", headers=admin, json={"customer_id": cust["id"], "items": [{"product_id": prod["id"], "qty": qty, "unit_price": price}]}).json()
    order = client.post(f"/api/sales/quotations/{q['id']}/accept", headers=admin).json()
    works = client.get(W, headers=admin).json()["works"]
    work = next(w for w in works if w["sales_order_id"] == order["id"])
    return order, work


def _rec(client, admin, wid):
    return next(r for r in client.get(REC, headers=admin).json()["works"] if r["work_id"] == wid)


def test_direct_sale_is_its_own_type_and_follows_invoice_and_payment(client, signup):
    admin = signup()
    order, work = _sale(client, admin)
    assert work["work_type"] == "sales_order" and work["status"] == "assigned"
    assert _rec(client, admin, work["id"])["state"] == "not_started"

    inv = client.post(f"/api/sales/orders/{order['id']}/invoice", headers=admin).json()
    w = client.get(f"{W}/{work['id']}", headers=admin).json()
    assert w["status"] == "delivered" and w["sales_invoice"]["id"] == inv["id"]
    assert float(w["vendor_amount"]) == 180.0 and float(w["profit"]) == 120.0
    assert _rec(client, admin, work["id"])["state"] == "awaiting_payment"

    # nothing can be typed in on the work: money and delivery belong to Sales / Finance
    assert client.post(f"{W}/{work['id']}/payments", headers=admin, json={"amount": 10, "method": "cash"}).status_code == 400
    assert client.post(f"{W}/{work['id']}/take-from-inventory", headers=admin).status_code == 400

    # part payment: still delivered, invoice still unpaid; overpayment refused
    assert client.post("/api/finance/payments", headers=admin, json={"invoice_id": inv["id"], "amount": 100}).status_code == 201
    w = client.get(f"{W}/{work['id']}", headers=admin).json()
    assert w["status"] == "delivered" and float(w["received_amount"]) == 100.0 and float(w["pending_amount"]) == 200.0
    assert _rec(client, admin, work["id"])["state"] == "part_paid"
    assert client.post("/api/finance/payments", headers=admin, json={"invoice_id": inv["id"], "amount": 500}).status_code == 400

    assert client.post("/api/finance/payments", headers=admin, json={"invoice_id": inv["id"], "amount": 200}).status_code == 201
    w = client.get(f"{W}/{work['id']}", headers=admin).json()
    assert w["status"] == "closed"
    r = _rec(client, admin, work["id"])
    assert r["state"] == "matched" and float(r["received"]) == float(r["booked_in_finance"]) == 300.0 and r["work_type"] == "sales_order"
    assert any(i["kind"] == "closed" for i in w["events"])


def test_direct_sale_can_still_be_cancelled_before_it_is_invoiced(client, signup):
    admin = signup()
    order, work = _sale(client, admin)
    assert client.post(f"{W}/{work['id']}/cancel-request", headers=admin, json={"reason": "Customer cancelled the order"}).status_code == 200
    assert client.post(f"{W}/{work['id']}/cancel-decision", headers=admin, json={"approve": True}).status_code == 200
    assert _rec(client, admin, work["id"])["state"] == "cancelled"


def test_crm_work_stays_a_normal_project_work(client, signup):
    admin = signup()
    w = client.post(W, headers=admin, json={"client_name": "Acme", "quotation_amount": 100}).json()
    assert w["work_type"] == "project"
