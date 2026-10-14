"""GST credit (input tax), product master MRP inherited by PO lots, work GST auto-filled from items, profit with and without GST."""
import uuid
from decimal import Decimal

from conftest import receive_po

W = "/api/workpage/works"
D = lambda v: Decimal(str(v))


def _product(client, h, **kw):
    body = {"name": f"Inverter {uuid.uuid4().hex[:4]}", "unit_price": 50000, "cgst_percent": 10, "sgst_percent": 10, "mrp": 60000, "max_discount_percent": 10}
    body.update(kw)
    r = client.post("/api/sales/products", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _received_lot(client, h, prod, unit_price=40000, qty=5):
    vendor = client.post("/api/procurement/vendors", headers=h, json={"name": "SunVolt"}).json()
    po = client.post("/api/procurement/purchase-orders", headers=h, json={"vendor_id": vendor["id"], "items": [
        {"product_id": prod["id"], "qty": qty, "unit_price": unit_price, "cgst_percent": 10, "sgst_percent": 10}]}).json()
    receive_po(client, h, po["id"])
    return next(b for b in client.get("/api/stockin/batches", headers=h).json() if b["product_id"] == prod["id"])


def _work(client, h, prod, quote=50000):
    d = client.post("/api/hr/departments", headers=h, json={"name": f"Ops{uuid.uuid4().hex[:4]}"}).json()
    e = client.post("/api/hr/employees", headers=h, json={"name": "Anu", "department_id": d["id"]}).json()
    w = client.post(W, headers=h, json={"client_name": "Acme", "quotation_amount": quote}).json()
    client.post(f"{W}/{w['id']}/allocate", headers=h, json={"department_id": d["id"], "employee_id": e["id"]})
    assert client.put(f"{W}/{w['id']}/items", headers=h, json={"items": [{"product_id": prod["id"], "qty": 1}]}).status_code == 200
    return w


def test_po_lot_inherits_product_mrp_discount_and_gst(client, signup):
    h = signup()
    prod = _product(client, h)
    lot = _received_lot(client, h, prod)
    assert D(lot["mrp"]) == 60000 and D(lot["max_discount_percent"]) == 10 and D(lot["msp"]) == 50000
    assert D(lot["lowest_selling_price"]) == 54000 and D(lot["cgst_percent"]) == 10 and lot["itc_eligible"] is True
    assert "no MRP" not in (lot["note"] or "")
    # a product with no MRP falls back to list price + GST (58,333.33 excl -> 70,000 incl.) and the lot still says it
    bare = _product(client, h, mrp=None, max_discount_percent=0, unit_price=1000)
    lot2 = _received_lot(client, h, bare, unit_price=500)
    assert D(lot2["mrp"]) == 1200
    # Stock Intake: MRP / discount left out take the product's
    r = client.post("/api/stockin/batches", headers=h, json={"product_id": prod["id"], "quantity": 2, "vendor_name": "V", "vendor_amount": 40000})
    assert r.status_code == 201 and D(r.json()["mrp"]) == 60000 and D(r.json()["max_discount_percent"]) == 10


def test_work_gst_and_vendor_amount_fill_in_when_items_are_listed(client, signup):
    h = signup()
    prod = _product(client, h)
    _received_lot(client, h, prod)
    w = _work(client, h, prod)
    got = client.get(f"{W}/{w['id']}", headers=h).json()
    assert D(got["cgst_percent"]) == 10 and D(got["sgst_percent"]) == 10 and D(got["vendor_amount"]) == 40000
    assert D(got["net_payable"]) == 60000
    assert any(e["kind"] == "autofill" for e in got["events"])
    # product with GST but no stock at all: the product's rate is used
    prod2 = _product(client, h, cgst_percent=6, sgst_percent=6)
    w2 = _work(client, h, prod2)
    assert D(client.get(f"{W}/{w2['id']}", headers=h).json()["cgst_percent"]) == 6


def _take_and_pay(client, h, w, amount=60000):
    assert client.post(f"{W}/{w['id']}/take-from-inventory", headers=h).status_code == 200
    assert client.post(f"{W}/{w['id']}/payments", headers=h, json={"amount": amount, "method": "cash"}).status_code == 201
    return client.get(f"{W}/{w['id']}", headers=h).json()


def test_profit_with_and_without_gst_when_credit_is_claimable(client, signup):
    h = signup()
    prod = _product(client, h)
    _received_lot(client, h, prod)
    got = _take_and_pay(client, h, _work(client, h, prod))
    assert D(got["profit_excl_gst"]) == 10000 and D(got["actual_profit"]) == 10000
    assert D(got["gst_collected"]) == 10000 and D(got["gst_credit"]) == 8000 and D(got["gst_net_payable"]) == 2000 and D(got["gst_blocked"]) == 0
    assert D(got["cash_margin_incl_gst"]) == 12000 and D(got["cash_after_gst_settlement"]) == 10000


def test_blocked_credit_reduces_actual_profit(client, signup):
    h = signup()
    prod = _product(client, h)
    lot = _received_lot(client, h, prod)
    assert client.patch(f"/api/stockin/batches/{lot['id']}", headers=h, json={"itc_eligible": False}).status_code == 200
    got = _take_and_pay(client, h, _work(client, h, prod))
    assert D(got["gst_credit"]) == 0 and D(got["gst_blocked"]) == 8000 and D(got["gst_net_payable"]) == 10000
    assert D(got["profit_excl_gst"]) == 10000 and D(got["actual_profit"]) == 2000 and D(got["cash_after_gst_settlement"]) == 2000


def test_finance_gst_summary_nets_collected_against_credit(client, signup):
    h = signup()
    prod = _product(client, h)
    _received_lot(client, h, prod)                       # 5 x 40,000 = 200,000 -> 40,000 input GST
    _take_and_pay(client, h, _work(client, h, prod))     # 10,000 collected
    s = client.get("/api/finance/gst-summary", headers=h).json()
    t = s["totals"]
    assert D(t["output_gst"]) == 10000 and D(t["input_credit"]) == 40000 and D(t["net_payable"]) == -30000     # negative = credit carried forward
    assert len(s["months"]) == 1 and s["ledger"][0]["po_number"] and D(s["ledger"][0]["total_gst"]) == 40000 and s["ledger"][0]["eligible"] is True
    other = signup()
    assert client.get("/api/finance/gst-summary", headers=other).json()["totals"]["output_gst"] in (0, "0.00", 0.0)


def test_vendor_gst_is_shown_before_stock_is_taken_as_an_estimate(client, signup):
    h = signup()
    # no stock, no PO: the vendor amount typed on the work gets the work's own slab (25,000 + 20% = 30,000)
    w = client.post(W, headers=h, json={"client_name": "Acme", "quotation_amount": 40000, "vendor_amount": 25000, "cgst_percent": 10, "sgst_percent": 10}).json()
    got = client.get(f"{W}/{w['id']}", headers=h).json()
    assert D(got["vendor_gst"]) == 5000 and D(got["vendor_total_paid"]) == 30000 and got["vendor_gst_estimated"] is True
    assert D(got["gst_credit"]) == 5000 and D(got["gst_net_payable"]) == 3000 and D(got["actual_profit"]) == 15000
    # once stock is taken the figure comes from the lots and is no longer an estimate
    prod = _product(client, h)
    _received_lot(client, h, prod)
    w2 = _work(client, h, prod)
    assert client.get(f"{W}/{w2['id']}", headers=h).json()["vendor_gst_estimated"] is True
    assert D(client.get(f"{W}/{w2['id']}", headers=h).json()["vendor_total_paid"]) == 48000
    client.post(f"{W}/{w2['id']}/take-from-inventory", headers=h)
    assert client.get(f"{W}/{w2['id']}", headers=h).json()["vendor_gst_estimated"] is False
