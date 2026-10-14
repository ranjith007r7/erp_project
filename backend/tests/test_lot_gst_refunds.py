"""v3_13: lot GST slab (MSP split), GST-inclusive price limits, the work tax invoice, and Finance refunds after a cancellation."""
import subprocess
import tempfile
import uuid
from decimal import Decimal

from conftest import login_any

W = "/api/workpage/works"
REC = "/api/finance/work-reconciliation"
D = lambda v: Decimal(str(v))


def _text(pdf: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(pdf); f.flush()
        return subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True).stdout


def _product(client, h, price=50000, cgst=10, sgst=10):
    return client.post("/api/sales/products", headers=h, json={"name": f"Inverter {uuid.uuid4().hex[:4]}", "unit_price": price,
                                                              "cgst_percent": cgst, "sgst_percent": sgst}).json()


def _lot(client, h, prod, qty=10, **kw):
    body = {"product_id": prod["id"], "quantity": qty, "vendor_name": "SunVolt", "vendor_amount": 40000, "mrp": 60000, "max_discount_percent": 10}
    body.update(kw)
    r = client.post("/api/stockin/batches", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _project_work(client, h, prod, quote=50000, disc=0, qty=1):
    d = client.post("/api/hr/departments", headers=h, json={"name": f"Ops{uuid.uuid4().hex[:4]}"}).json()
    e = client.post("/api/hr/employees", headers=h, json={"name": "Anu", "department_id": d["id"]}).json()
    w = client.post(W, headers=h, json={"client_name": "Acme Traders", "quotation_amount": quote, "discount_percent": disc}).json()
    client.post(f"{W}/{w['id']}/allocate", headers=h, json={"department_id": d["id"], "employee_id": e["id"]})
    r = client.put(f"{W}/{w['id']}/items", headers=h, json={"items": [{"product_id": prod["id"], "qty": qty}]})
    assert r.status_code == 200, r.text
    return w


def _get(client, h, wid):
    return client.get(f"{W}/{wid}", headers=h).json()


def _user(client, admin, perms):
    u = uuid.uuid4().hex[:8]
    role = client.post("/api/core/roles", headers=admin, json={"name": f"Fin {u}"}).json()
    for m, a in perms:
        assert client.post(f"/api/core/roles/{role['id']}/permissions", headers=admin, json={"module": m, "action": a}).status_code == 201
    email = f"fin-{u}@test.com"
    client.post("/api/core/users", headers=admin, json={"name": "Fin", "email": email, "password": "pass12345", "role_id": role["id"]})
    return {"Authorization": f"Bearer {login_any(client, email, 'pass12345').json()['access_token']}"}


def test_lot_splits_mrp_into_msp_plus_gst_and_vendor_base_into_total_paid(client, signup):
    h = signup()
    prod = _product(client, h)
    lot = _lot(client, h, prod)
    assert D(lot["cgst_percent"]) == 10 and D(lot["sgst_percent"]) == 10          # defaulted from the product
    assert D(lot["msp"]) == 50000 and D(lot["mrp_cgst"]) == 5000 and D(lot["mrp_sgst"]) == 5000
    assert D(lot["lowest_selling_price"]) == 54000 and D(lot["lowest_selling_price_excl_gst"]) == 45000
    assert D(lot["vendor_amount"]) == 40000 and D(lot["vendor_cgst"]) == 4000 and D(lot["vendor_total_paid"]) == 48000
    other = _lot(client, h, prod, cgst_percent=2.5, sgst_percent=2.5, mrp=1050)
    assert D(other["msp"]) == 1000 and D(other["mrp_cgst"]) == 25


def test_price_limits_use_gst_inclusive_figures_and_work_adopts_rate_from_lots(client, signup):
    h = signup()
    prod = _product(client, h)
    _lot(client, h, prod)
    w = _project_work(client, h, prod, quote=50000)
    tk = client.post(f"{W}/{w['id']}/take-from-inventory", headers=h)
    assert tk.status_code == 200, tk.text
    got = _get(client, h, w["id"])
    assert D(got["cgst_percent"]) == 10 and D(got["sgst_percent"]) == 10 and D(got["net_payable"]) == 60000      # 50,000 + 20% = MRP: allowed
    assert not got.get("pricing_violations")
    # a typed rate is refused while the work is lot-backed
    assert client.patch(f"{W}/{w['id']}", headers=h, json={"cgst_percent": 5}).status_code == 400
    # below the floor: 44,000 + 20% = 52,800 < 54,000
    r = client.patch(f"{W}/{w['id']}", headers=h, json={"quotation_amount": 44000})
    assert r.status_code == 400 and "54,000" in r.text.replace("54000.00", "54,000"), r.text
    # above the ceiling: 51,000 + 20% = 61,200 > 60,000
    assert client.patch(f"{W}/{w['id']}", headers=h, json={"quotation_amount": 51000}).status_code == 400
    # exactly the floor passes: 45,000 + 20% = 54,000
    assert client.patch(f"{W}/{w['id']}", headers=h, json={"quotation_amount": 45000}).status_code == 200


def test_work_tax_invoice_has_discount_payments_and_no_vendor_prices(client, signup):
    h = signup()
    client.patch("/api/organizations/profile", headers=h, json={"legal_name": "Sunrise Energy Pvt Ltd", "address_line1": "45 Anna Salai", "city": "Chennai", "gstin": "33ABCDE1234F1Z5"})
    prod = _product(client, h)
    _lot(client, h, prod)
    w = _project_work(client, h, prod, quote=50000, disc=5)         # 47,500 taxable -> 57,000 payable (floor is 54,000)
    client.post(f"{W}/{w['id']}/take-from-inventory", headers=h)
    assert _get(client, h, w["id"])["invoice_ready"] is False
    assert client.get(f"{W}/{w['id']}/invoice-pdf", headers=h).status_code == 409           # nothing paid yet
    assert client.post(f"{W}/{w['id']}/payments", headers=h, json={"amount": 30000, "method": "gpay", "transaction_id": "UPI778899"}).status_code == 201
    assert client.post(f"{W}/{w['id']}/payments", headers=h, json={"amount": 27000, "method": "card", "transaction_id": "CARD445566"}).status_code == 201
    assert _get(client, h, w["id"])["invoice_ready"] is True
    r = client.get(f"{W}/{w['id']}/invoice-pdf", headers=h)
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    t = _text(r.content)
    for needle in ["Sunrise Energy Pvt Ltd", "TAX INVOICE", "INV-0001", "Acme Traders", "UPI778899", "CARD445566", "47,500.00", "57,000.00", "5"]:
        assert needle in t, f"missing {needle!r}:\n{t}"
    assert "40,000" not in t and "SunVolt" not in t and "48,000" not in t      # vendor prices never appear
    # the number is stable on a second download and shared with Sales invoices
    assert "INV-0001" in _text(client.get(f"{W}/{w['id']}/invoice-pdf", headers=h).content)


def test_project_work_refund_partial_with_charge_syncs_reconciliation_and_books(client, signup):
    admin = signup()
    prod = _product(client, admin)
    _lot(client, admin, prod)
    w = _project_work(client, admin, prod, quote=50000)
    client.post(f"{W}/{w['id']}/take-from-inventory", headers=admin)
    assert client.post(f"{W}/{w['id']}/payments", headers=admin, json={"amount": 40000, "method": "cash"}).status_code == 201
    assert client.post(f"{W}/{w['id']}/cancel-request", headers=admin, json={"reason": "Customer cancelled the order"}).status_code == 200
    assert client.post(f"{W}/{w['id']}/cancel-decision", headers=admin, json={"approve": True}).status_code == 200

    rows = client.get("/api/finance/refunds", headers=admin).json()
    assert len(rows) == 1 and rows[0]["status"] == "pending" and D(rows[0]["received_amount"]) == 40000 and rows[0]["refund_number"] == "RF-0001"
    rid = rows[0]["id"]
    rec = next(r for r in client.get(REC, headers=admin).json()["works"] if r["work_id"] == w["id"])
    assert rec["state"] == "cancelled_refund_due"

    # a finance user without the refund permission can see but not complete
    viewer = _user(client, admin, [("finance", "view")])
    assert len(client.get("/api/finance/refunds", headers=viewer).json()) == 1
    assert client.post(f"/api/finance/refunds/{rid}/complete", headers=viewer, json={"charge_percent": 10, "method": "cash"}).status_code == 403
    clerk = _user(client, admin, [("finance", "view"), ("finance", "refund")])

    bad = lambda body: client.post(f"/api/finance/refunds/{rid}/complete", headers=clerk, json=body)
    assert bad({"charge_percent": 10, "method": "gpay"}).status_code == 400                          # no transaction id
    assert bad({"charge_percent": 10, "method": "gpay", "transaction_id": "x"}).status_code == 400    # malformed id
    assert bad({"charge_percent": 150, "method": "cash"}).status_code == 422
    assert bad({"charge_percent": 10, "method": "barter"}).status_code == 400
    ok = bad({"charge_percent": 10, "method": "gpay", "transaction_id": "GPAY99887766", "note": "Cancelled by customer"})
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["status"] == "completed" and D(body["charge_amount"]) == 4000 and D(body["refund_amount"]) == 36000 and body["transaction_id"] == "GPAY99887766"
    assert bad({"charge_percent": 0, "method": "cash"}).status_code == 400                             # already completed

    rec = next(r for r in client.get(REC, headers=admin).json()["works"] if r["work_id"] == w["id"])
    assert rec["state"] == "cancelled_refunded" and D(rec["refunded"]) == 36000 and D(rec["kept"]) == 4000
    assert "GPAY99887766" in rec["note"]

    # the refund entry balances: Cash out 36,000, cancellation income 4,000
    je = next(e for e in client.get("/api/finance/journal-entries", headers=admin).json() if e["reference"].startswith("RFND-"))
    assert sum(D(l["debit"]) for l in je["lines"]) == sum(D(l["credit"]) for l in je["lines"]) == 40000
    # a second org sees nothing of it
    other = signup()
    assert client.get("/api/finance/refunds", headers=other).json() == []
    # the same transaction id cannot be reused on another refund
    prod2 = _product(client, admin)
    _lot(client, admin, prod2)
    w2 = _project_work(client, admin, prod2, quote=50000)
    client.post(f"{W}/{w2['id']}/take-from-inventory", headers=admin)
    client.post(f"{W}/{w2['id']}/payments", headers=admin, json={"amount": 1000, "method": "cash"})
    client.post(f"{W}/{w2['id']}/cancel-request", headers=admin, json={"reason": "Customer cancelled the order"})
    client.post(f"{W}/{w2['id']}/cancel-decision", headers=admin, json={"approve": True})
    pend = [r for r in client.get("/api/finance/refunds?status=pending", headers=admin).json()]
    assert len(pend) == 1
    assert client.post(f"/api/finance/refunds/{pend[0]['id']}/complete", headers=clerk, json={"charge_percent": 0, "method": "gpay", "transaction_id": "GPAY99887766"}).status_code == 400
    full = client.post(f"/api/finance/refunds/{pend[0]['id']}/complete", headers=clerk, json={"charge_percent": 0, "method": "cash"})
    assert full.status_code == 200 and D(full.json()["refund_amount"]) == 1000 and D(full.json()["charge_amount"]) == 0


def test_cancelled_sales_order_after_invoice_gets_credit_note_stock_back_and_refund(client, signup):
    admin = signup()
    prod = _product(client, admin, price=1000, cgst=9, sgst=9)
    _lot(client, admin, prod, qty=10, vendor_amount=500, mrp=1180, max_discount_percent=50, cgst_percent=9, sgst_percent=9)
    cust = client.post("/api/sales/customers", headers=admin, json={"name": "Anita"}).json()
    q = client.post("/api/sales/quotations", headers=admin, json={"customer_id": cust["id"], "items": [{"product_id": prod["id"], "qty": 3, "unit_price": 1000}]}).json()
    order = client.post(f"/api/sales/quotations/{q['id']}/accept", headers=admin).json()
    work = next(x for x in client.get(W, headers=admin).json()["works"] if x["sales_order_id"] == order["id"])
    stock = lambda: sum(r["quantity"] for r in client.get("/api/inventory/stock-levels", headers=admin).json() if r["product_id"] == prod["id"])
    before = stock()
    inv = client.post(f"/api/sales/orders/{order['id']}/invoice", headers=admin).json()
    assert stock() == before - 3
    assert client.post("/api/finance/payments", headers=admin, json={"invoice_id": inv["id"], "amount": 1000}).status_code == 201
    assert client.post(f"{W}/{work['id']}/cancel-request", headers=admin, json={"reason": "Customer cancelled the order"}).status_code == 200
    assert client.post(f"{W}/{work['id']}/cancel-decision", headers=admin, json={"approve": True}).status_code == 200
    assert stock() == before                                                      # the three units are back
    lots = client.get("/api/stockin/batches", headers=admin).json()
    assert sum(b["quantity_remaining"] for b in lots if b["product_id"] == prod["id"]) == 10
    # credit note: the invoice is cancelled and nothing more can be paid against it
    invs = {i["id"]: i for i in client.get("/api/sales/invoices", headers=admin).json()}
    assert invs[inv["id"]]["status"] == "cancelled"
    assert client.post("/api/finance/payments", headers=admin, json={"invoice_id": inv["id"], "amount": 100}).status_code == 400
    cn = next(e for e in client.get("/api/finance/journal-entries", headers=admin).json() if e["reference"] == f"CN-{inv['id']}")
    assert sum(D(l["debit"]) for l in cn["lines"]) == sum(D(l["credit"]) for l in cn["lines"]) == D(inv["amount"])
    refunds = client.get("/api/finance/refunds", headers=admin).json()
    assert len(refunds) == 1 and refunds[0]["kind"] == "sales_invoice" and D(refunds[0]["received_amount"]) == 1000
    done = client.post(f"/api/finance/refunds/{refunds[0]['id']}/complete", headers=admin, json={"charge_percent": 20, "method": "bank_transfer", "transaction_id": "NEFT12345678"})
    assert done.status_code == 200 and D(done.json()["refund_amount"]) == 800 and D(done.json()["charge_amount"]) == 200
    rec = next(r for r in client.get(REC, headers=admin).json()["works"] if r["work_id"] == work["id"])
    assert rec["state"] == "cancelled_refunded" and D(rec["kept"]) == 200
    # a closed (fully paid) work still cannot be cancelled
    assert client.post(f"{W}/{work['id']}/cancel-request", headers=admin, json={"reason": "Customer cancelled the order"}).status_code == 400


def test_editing_a_lot_can_change_its_gst_slab(client, signup):
    h = signup()
    prod = _product(client, h)
    lot = _lot(client, h, prod)
    r = client.patch(f"/api/stockin/batches/{lot['id']}", headers=h, json={"cgst_percent": 9, "sgst_percent": 9, "mrp": 59000})
    assert r.status_code == 200, r.text
    row = r.json()
    assert D(row["cgst_percent"]) == 9 and D(row["msp"]) == 50000 and D(row["mrp_cgst"]) == 4500 and D(row["vendor_total_paid"]) == 47200
    assert "CGST %" in row["note"]
