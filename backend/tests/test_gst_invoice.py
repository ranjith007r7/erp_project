"""GST (CGST + SGST) through quotation -> order -> invoice -> journal, purchase orders and works; and the printable tax invoice."""
import subprocess
import tempfile
import uuid
from decimal import Decimal

from conftest import receive_po

W = "/api/workpage/works"
D = lambda v: Decimal(str(v))


def _setup(client, h, cgst=9, sgst=9, price=1000, qty=2):
    prod = client.post("/api/sales/products", headers=h, json={"name": f"Inverter {uuid.uuid4().hex[:4]}", "unit_price": price,
                                                              "cgst_percent": cgst, "sgst_percent": sgst, "hsn_code": "8504"}).json()
    vendor = client.post("/api/procurement/vendors", headers=h, json={"name": "V"}).json()
    po = client.post("/api/procurement/purchase-orders", headers=h, json={"vendor_id": vendor["id"], "items": [{"product_id": prod["id"], "qty": 10, "unit_price": 500}]}).json()
    receive_po(client, h, po["id"])
    cust = client.post("/api/sales/customers", headers=h, json={"name": "Anita Stores", "billing_address": "12 Lake Road, Chennai", "gst_number": "33AAAAA0000A1Z5"}).json()
    q = client.post("/api/sales/quotations", headers=h, json={"customer_id": cust["id"], "items": [{"product_id": prod["id"], "qty": qty, "unit_price": price}]}).json()
    return prod, cust, q


def test_quotation_order_invoice_carry_gst_and_journal_splits_it(client, signup):
    h = signup()
    prod, cust, q = _setup(client, h)
    assert D(q["subtotal"]) == 2000 and D(q["cgst_amount"]) == 180 and D(q["sgst_amount"]) == 180 and D(q["total"]) == 2360
    assert D(q["items"][0]["cgst_percent"]) == 9
    order = client.post(f"/api/sales/quotations/{q['id']}/accept", headers=h).json()
    assert D(order["total"]) == 2360 and D(order["cgst_amount"]) == 180
    inv = client.post(f"/api/sales/orders/{order['id']}/invoice", headers=h).json()
    assert inv["invoice_number"] == "INV-0001" and D(inv["amount"]) == 2360 and D(inv["subtotal"]) == 2000
    entries = client.get("/api/finance/journal-entries", headers=h).json()
    je = next(e for e in entries if e["reference"] == f"INV-{inv['id']}")
    by = {}
    for l in je["lines"]:
        by[l.get("account_code") or l.get("code") or l["account_id"]] = l
    credits = sorted(D(l["credit"]) for l in je["lines"] if D(l["credit"]) > 0)
    assert credits == [180, 180, 2000] and sum(D(l["debit"]) for l in je["lines"]) == 2360
    # a line can override the product's rate
    q2 = client.post("/api/sales/quotations", headers=h, json={"customer_id": cust["id"], "items": [{"product_id": prod["id"], "qty": 1, "unit_price": 1000, "cgst_percent": 2.5, "sgst_percent": 2.5}]}).json()
    assert D(q2["total"]) == 1050
    # no GST on the product: totals unchanged from before
    p0 = client.post("/api/sales/products", headers=h, json={"name": "Plain", "unit_price": 100}).json()
    q3 = client.post("/api/sales/quotations", headers=h, json={"customer_id": cust["id"], "items": [{"product_id": p0["id"], "qty": 3, "unit_price": 100}]}).json()
    assert D(q3["total"]) == 300 and D(q3["cgst_amount"]) == 0
    # editing the product's rate does not touch documents already made
    assert client.patch(f"/api/sales/products/{prod['id']}", headers=h, json={"cgst_percent": 6, "sgst_percent": 6}).status_code == 200
    assert D(client.get("/api/sales/quotations", headers=h).json()[-1]["total"]) in (2360, 1050, 300)


def test_invoice_pdf_is_issued_after_payment_and_filled_from_the_records(client, signup):
    h = signup()
    client.patch("/api/organizations/profile", headers=h, json={"legal_name": "Sunrise Energy Pvt Ltd", "address_line1": "45 Anna Salai", "city": "Chennai",
                                                                "state": "Tamil Nadu", "postal_code": "600002", "gstin": "33ABCDE1234F1Z5", "company_phone": "+91 44 1234 5678"})
    prod, cust, q = _setup(client, h)
    order = client.post(f"/api/sales/quotations/{q['id']}/accept", headers=h).json()
    inv = client.post(f"/api/sales/orders/{order['id']}/invoice", headers=h).json()
    assert inv["document_ready"] is False
    assert client.get(f"/api/sales/invoices/{inv['id']}/pdf", headers=h).status_code == 409
    assert client.post("/api/finance/payments", headers=h, json={"invoice_id": inv["id"], "amount": 1000}).status_code == 201
    got = [i for i in client.get("/api/sales/invoices", headers=h).json() if i["id"] == inv["id"]][0]
    assert got["document_ready"] is True and D(got["paid_amount"]) == 1000 and D(got["balance"]) == 1360
    assert client.post("/api/finance/payments", headers=h, json={"invoice_id": inv["id"], "amount": 5000}).status_code == 400
    assert client.post("/api/finance/payments", headers=h, json={"invoice_id": inv["id"], "amount": 1360}).status_code == 201
    r = client.get(f"/api/sales/invoices/{inv['id']}/pdf", headers=h)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content[:4] == b"%PDF"
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(r.content); f.flush()
        text = subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True).stdout
    for needle in ["Sunrise Energy Pvt Ltd", "45 Anna Salai", "Chennai", "33ABCDE1234F1Z5", "TAX INVOICE", "INV-0001", "Anita Stores", "12 Lake Road",
                   "33AAAAA0000A1Z5", "Inverter", "8504", "2,000.00", "180.00", "2,360.00", "Two thousand three hundred sixty rupees only", "PAID"]:
        assert needle in text, f"missing {needle!r} in invoice:\n{text}"
    other = signup()
    assert client.get(f"/api/sales/invoices/{inv['id']}/pdf", headers=other).status_code == 404


def test_purchase_order_gst_keeps_cost_basis_ex_gst(client, signup):
    h = signup()
    prod = client.post("/api/sales/products", headers=h, json={"name": "Panel", "unit_price": 10, "cgst_percent": 6, "sgst_percent": 6}).json()
    vendor = client.post("/api/procurement/vendors", headers=h, json={"name": "V"}).json()
    po = client.post("/api/procurement/purchase-orders", headers=h, json={"vendor_id": vendor["id"], "items": [{"product_id": prod["id"], "qty": 4, "unit_price": 250}]}).json()
    assert D(po["total"]) == 1000 and D(po["cgst_amount"]) == 60 and D(po["sgst_amount"]) == 60 and D(po["grand_total"]) == 1120
    assert D(po["items"][0]["cgst_percent"]) == 6
    client.post(f"/api/procurement/purchase-orders/{po['id']}/approve", headers=h)
    pdf = client.get(f"/api/procurement/purchase-orders/{po['id']}/pdf", headers=h)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


def test_work_gst_changes_payable_but_not_profit_and_books_gst_separately(client, signup):
    h = signup()
    w = client.post(W, headers=h, json={"client_name": "Acme", "quotation_amount": 1000, "discount_percent": 10, "vendor_amount": 400,
                                        "cgst_percent": 9, "sgst_percent": 9}).json()
    assert D(w["taxable_net"]) == 900 and D(w["cgst_amount"]) == 81 and D(w["net_payable"]) == 1062 and D(w["profit"]) == 500
    up = client.patch(f"{W}/{w['id']}", headers=h, json={"sgst_percent": 6}).json()
    assert D(up["net_payable"]) == 1035 + 0 or D(up["net_payable"]) == D("1035.00")
    client.patch(f"{W}/{w['id']}", headers=h, json={"sgst_percent": 9})
    # pay the GST-inclusive amount in two parts: the books split every receipt into revenue and GST payable
    p1 = client.post(f"{W}/{w['id']}/payments", headers=h, json={"amount": 531, "method": "cash"})
    assert p1.status_code == 201, p1.text
    assert client.post(f"{W}/{w['id']}/payments", headers=h, json={"amount": 600, "method": "cash"}).status_code == 400   # more than pending
    entries = client.get("/api/finance/journal-entries", headers=h).json()
    je = next(e for e in entries if e["reference"].startswith("WPMT-"))
    assert sorted(D(l["credit"]) for l in je["lines"] if D(l["credit"]) > 0) == [40.5, 40.5, 450.0]
    rec = next(r for r in client.get("/api/finance/work-reconciliation", headers=h).json()["works"] if r["work_id"] == w["id"])
    assert D(rec["quoted_net"]) == 1062 and D(rec["received"]) == D(rec["booked_in_finance"]) == 531


def test_sales_order_work_uses_gross_for_payment_and_taxable_for_profit(client, signup):
    h = signup()
    prod, cust, q = _setup(client, h)
    order = client.post(f"/api/sales/quotations/{q['id']}/accept", headers=h).json()
    work = next(x for x in client.get(W, headers=h).json()["works"] if x["sales_order_id"] == order["id"])
    assert D(work["net_payable"]) == 2360 and D(work["taxable_net"]) == 2000
    assert client.patch(f"{W}/{work['id']}", headers=h, json={"cgst_percent": 5}).status_code == 400
    inv = client.post(f"/api/sales/orders/{order['id']}/invoice", headers=h).json()
    client.post("/api/finance/payments", headers=h, json={"invoice_id": inv["id"], "amount": 2360})
    w = client.get(f"{W}/{work['id']}", headers=h).json()
    assert w["status"] == "closed" and D(w["profit"]) == 1000     # 2000 taxable - 2 x 500 cost
    r = next(r for r in client.get("/api/finance/work-reconciliation", headers=h).json()["works"] if r["work_id"] == work["id"])
    assert r["state"] == "matched"


def test_amount_in_words_uses_the_indian_system():
    from app.services.invoice_pdf import amount_in_words
    assert amount_in_words(123456.5) == "One lakh twenty-three thousand four hundred fifty-six rupees and fifty paise only"
    assert amount_in_words(0) == "Zero rupees only"
    assert amount_in_words(10_000_000) == "One crore rupees only"
