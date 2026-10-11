"""CRM -> Work (Assigned) -> stock check -> inventory or purchase -> delivered -> paid -> done; Stock Intake; pricing rules."""
import io
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from conftest import PNG_BYTES, PDF_BYTES, login_any

W = "/api/workpage/works"
PO = "/api/procurement/purchase-orders"
HOME = "/api/dashboard/home"
SI = "/api/stockin"


def D(x):
    return Decimal(str(x))


def iso(d):
    return d.isoformat()


def user_with(client, admin, perms, name="Emp"):
    unique = uuid.uuid4().hex[:8]
    role = client.post("/api/core/roles", headers=admin, json={"name": f"R {unique}"}).json()
    for m, a in perms:
        client.post(f"/api/core/roles/{role['id']}/permissions", headers=admin, json={"module": m, "action": a})
    email = f"u-{unique}@test.com"
    client.post("/api/core/users", headers=admin, json={"name": name, "email": email, "password": "pass12345", "role_id": role["id"]})
    return {"Authorization": f"Bearer {login_any(client, email, 'pass12345').json()['access_token']}"}


def product(client, h, name=None, price=200):
    return client.post("/api/sales/products", headers=h, json={"name": name or f"Desk {uuid.uuid4().hex[:5]}", "unit_price": price, "sku": uuid.uuid4().hex[:6].upper()}).json()


def batch(client, h, pid, qty=10, cost=100, mrp=200, disc=10, inward=None, expiry=None, vendor="Bharat Timber", **kw):
    body = {"product_id": pid, "quantity": qty, "vendor_name": vendor, "vendor_amount": cost, "mrp": mrp, "max_discount_percent": disc,
            "inward_date": iso(inward or date.today())}
    if expiry:
        body["expiry_date"] = iso(expiry)
    body.update(kw)
    return client.post(f"{SI}/batches", headers=h, json=body)


def stock_of(client, h, pid):
    rows = client.get("/api/inventory/stock-levels", headers=h).json()
    return sum(r["quantity"] for r in rows if r["product_id"] == pid)


def crm_work(client, h, amount=1000, name="Konnect Coworking", mobile="+91 98765 43210"):
    lead = client.post("/api/crm/leads", headers=h, json={"name": "Anjali", "company_name": name, "phone": mobile,
                                                           "estimated_amount": amount, "industry": "Coworking"})
    assert lead.status_code == 201, lead.text
    r = client.post(f"/api/crm/leads/{lead.json()['id']}/convert", headers=h, json={"opportunity_name": f"{name} fitout", "opportunity_value": amount})
    assert r.status_code == 201, r.text
    assert r.json()["work_id"] and r.json()["work_number"]
    return client.get(f"{W}/{r.json()['work_id']}", headers=h).json()


def team(client, h):
    dept = client.post("/api/hr/departments", headers=h, json={"name": f"Stores {uuid.uuid4().hex[:4]}"}).json()
    emp = client.post("/api/hr/employees", headers=h, json={"name": "Ravi", "department_id": dept["id"]}).json()
    return dept, emp


def allocate(client, h, wid, dept, emp):
    r = client.post(f"{W}/{wid}/allocate", headers=h, json={"department_id": dept["id"], "employee_id": emp["id"]})
    assert r.status_code == 200, r.text
    return r.json()


def home(client, h, period="today"):
    return client.get(f"{HOME}?period={period}", headers=h).json()


# ------------------------------------------------------------------ CRM
def test_lead_mobile_is_validated_and_stored(client, signup):
    h = signup()
    bad = client.post("/api/crm/leads", headers=h, json={"name": "A", "phone": "abc"})
    assert bad.status_code == 422
    short = client.post("/api/crm/leads", headers=h, json={"name": "A", "phone": "12345"})
    assert short.status_code == 422
    ok = client.post("/api/crm/leads", headers=h, json={"name": "A", "phone": "+91 98765-43210", "estimated_amount": 2500.5})
    assert ok.status_code == 201 and ok.json()["phone"] == "+91 98765-43210" and D(ok.json()["estimated_amount"]) == D("2500.50")
    edit = client.patch(f"/api/crm/leads/{ok.json()['id']}", headers=h, json={"phone": "9876543210", "estimated_amount": 3000})
    assert edit.status_code == 200 and edit.json()["phone"] == "9876543210"
    csvp = "name,company_name,phone,estimated_amount\nRaj,Raj Co,9876501234,1500\nBad,Bad Co,12,10\n"
    imp = client.post("/api/crm/leads/import", headers=h, files={"file": ("l.csv", csvp.encode(), "text/csv")}).json()
    assert imp["imported"] == 1 and imp["failed"] == 1 and "mobile" in imp["errors"][0]["reason"]


def test_converting_a_quotation_opens_an_assigned_work_with_the_amount(client, signup):
    h = signup()
    w = crm_work(client, h, amount=174995)
    assert w["status"] == "assigned" and w["client_name"] == "Konnect Coworking" and w["client_mobile"] == "+91 98765 43210"
    assert D(w["quotation_amount"]) == D("174995") and w["domain"] == "Coworking" and w["lead_id"]
    assert w["handling_department"] is None                       # a manager allocates it
    assert w["events"][0]["title"].startswith("Quotation converted")
    leads = client.get("/api/crm/leads", headers=h).json()
    assert leads[0]["status"] == "converted" and leads[0]["converted_at"]
    # converting twice is refused and never makes a second work
    again = client.post(f"/api/crm/leads/{leads[0]['id']}/convert", headers=h, json={"opportunity_name": "x"})
    assert again.status_code == 400
    assert client.get(W, headers=h).json()["total"] == 1


def test_home_quotations_received_split_follows_conversion(client, signup):
    h = signup()
    l1 = client.post("/api/crm/leads", headers=h, json={"name": "A", "company_name": "Alpha", "phone": "9876500001", "estimated_amount": 1000}).json()
    client.post("/api/crm/leads", headers=h, json={"name": "B", "company_name": "Beta", "phone": "9876500002", "estimated_amount": 500})
    q = home(client, h)["quotations"]
    assert (q["received"], q["converted"], q["not_converted"]) == (2, 0, 2)
    assert {r["company_name"] for r in q["not_converted_list"]} == {"Alpha", "Beta"} and q["not_converted_value"] == 1500
    client.post(f"/api/crm/leads/{l1['id']}/convert", headers=h, json={"opportunity_name": "Alpha job", "opportunity_value": 1000})
    for period in ("today", "week", "month"):
        q = home(client, h, period)["quotations"]
        assert (q["received"], q["converted"], q["not_converted"]) == (2, 1, 1), period
    q = home(client, h)["quotations"]
    assert q["converted_list"][0]["company_name"] == "Alpha" and q["converted_value"] == 1000
    # a lead marked lost still counts as not converted
    client.patch(f"/api/crm/leads/{client.get('/api/crm/leads', headers=h).json()[0]['id']}/status", headers=h, json={"status": "lost"})
    assert home(client, h)["quotations"]["not_converted"] == 1


def test_sales_accept_attaches_to_the_existing_crm_work(client, signup):
    """A quotation raised in Sales from a CRM opportunity must not open a second work."""
    h = signup()
    w = crm_work(client, h, amount=1000)
    opp = client.get("/api/crm/opportunities", headers=h).json()[0]
    cust = client.post("/api/sales/customers", headers=h, json={"name": "Konnect"}).json()
    p = product(client, h)
    from app.core.database import SessionLocal
    from app.models.sales import Quotation, QuotationItem
    db = SessionLocal()
    try:
        qn = Quotation(org_id=cust["org_id"] if "org_id" in cust else None)
    finally:
        db.close()
    # create through the API, then link to the opportunity directly (the Sales form has no opportunity picker yet)
    q = client.post("/api/sales/quotations", headers=h, json={"customer_id": cust["id"], "items": [{"product_id": p["id"], "qty": 1, "unit_price": 200}]}).json()
    db = SessionLocal()
    try:
        row = db.query(Quotation).filter(Quotation.id == q["id"]).first()
        row.opportunity_id = opp["id"]
        db.commit()
    finally:
        db.close()
    assert client.post(f"/api/sales/quotations/{q['id']}/accept", headers=h).status_code == 201
    works = client.get(W, headers=h).json()
    assert works["total"] == 1
    d = client.get(f"{W}/{w['id']}", headers=h).json()
    assert d["quotation"]["id"] == q["id"] and D(d["quotation_amount"]) == 1000     # amount left as agreed
    assert any(e["kind"] == "quotation_linked" for e in d["events"])


# ------------------------------------------------------------------ Stock Intake
def test_stock_intake_is_for_managers_and_admin_only(client, signup):
    h = signup()
    p = product(client, h)
    emp = user_with(client, h, [("workpage", "view"), ("workpage", "edit"), ("inventory", "view")])
    assert client.get(f"{SI}/batches", headers=emp).status_code == 403
    assert batch(client, emp, p["id"]).status_code == 403
    mgr = user_with(client, h, [("stockin", "view"), ("stockin", "create")])
    assert batch(client, mgr, p["id"]).status_code == 201
    assert client.delete(f"{SI}/batches/{client.get(f'{SI}/batches', headers=mgr).json()[0]['id']}", headers=mgr).status_code == 403
    assert batch(client, h, p["id"]).status_code == 201          # admin always may


def test_standard_manager_roles_get_stock_intake_and_executives_do_not(client, signup):
    h = signup()
    tree = client.get("/api/core/roles/tree", headers=h).json()
    roles = {r["title"]: r["role_id"] for d in tree["departments"] for r in d["positions"] if r.get("role_id")}
    def has(title):
        perms = client.get(f"/api/core/roles/{roles[title]}/permissions", headers=h).json()
        return any(x["module"] == "stockin" and x["action"] == "create" for x in perms)
    assert has("Warehouse Manager") and has("Managing Director")
    assert not has("Store Keeper") and not has("Sales Executive")


def test_intake_validation_rules(client, signup):
    h = signup()
    p = product(client, h)
    today = date.today()
    ok_body = {"product_id": p["id"], "quantity": 5, "vendor_name": "V", "vendor_amount": 100, "mrp": 200, "max_discount_percent": 10, "inward_date": iso(today)}
    for missing in ("vendor_amount", "mrp", "max_discount_percent", "vendor_name", "quantity"):
        b = dict(ok_body); b.pop(missing)
        assert client.post(f"{SI}/batches", headers=h, json=b).status_code == 422, missing
    assert client.post(f"{SI}/batches", headers=h, json={**ok_body, "max_discount_percent": 101}).status_code == 422
    assert client.post(f"{SI}/batches", headers=h, json={**ok_body, "mrp": 0}).status_code == 422
    assert client.post(f"{SI}/batches", headers=h, json={**ok_body, "inward_date": iso(today + timedelta(days=2))}).status_code == 400
    assert client.post(f"{SI}/batches", headers=h, json={**ok_body, "expiry_date": iso(today - timedelta(days=1))}).status_code == 400
    assert client.post(f"{SI}/batches", headers=h, json={**ok_body, "manufacture_month": (today + timedelta(days=70)).strftime("%Y-%m")}).status_code == 400
    assert client.post(f"{SI}/batches", headers=h, json={**ok_body, "manufacture_month": "2026-13"}).status_code in (400, 422)
    good = client.post(f"{SI}/batches", headers=h, json={**ok_body, "manufacture_month": (today - timedelta(days=40)).strftime("%Y-%m"), "expiry_date": iso(today + timedelta(days=365))})
    assert good.status_code == 201, good.text
    g = good.json()
    assert g["manufacture_month"].endswith("-01") and D(g["lowest_selling_price"]) == 180 and g["quantity_remaining"] == 5


def test_intake_adds_to_inventory_and_priced_existing_does_not(client, signup):
    h = signup()
    p = product(client, h)
    assert batch(client, h, p["id"], qty=8).status_code == 201
    assert stock_of(client, h, p["id"]) == 8
    mv = client.get("/api/inventory/movements", headers=h).json()
    assert any(m["movement_type"] == "in" and m["qty"] == 8 and m["ref_type"] == "stock_intake" for m in mv)
    s = [r for r in client.get(f"{SI}/summary", headers=h).json()["products"] if r["product_id"] == p["id"]][0]
    assert (s["on_hand"], s["priced"], s["unpriced"]) == (8, 8, 0)
    # stock that arrived through the old way (no rates) is counted but unpriced ...
    from app.services.inventory import receive_stock
    from app.core.database import SessionLocal
    from app.models.user import User
    db = SessionLocal()
    try:
        org = db.query(User).filter(User.email.like("admin-%")).order_by(User.created_at.desc()).first().org_id
        receive_stock(db, str(org), product_id=str(p["id"]), qty=5, ref_type="legacy", ref_id=str(uuid.uuid4()))
        db.commit()
    finally:
        db.close()
    s = [r for r in client.get(f"{SI}/summary", headers=h).json()["products"] if r["product_id"] == p["id"]][0]
    assert (s["on_hand"], s["unpriced"]) == (13, 5)
    # ... and can be priced without counting it twice
    over = batch(client, h, p["id"], qty=6, already_in_inventory=True)
    assert over.status_code == 400 and "5 unit" in over.json()["detail"]
    ok = batch(client, h, p["id"], qty=5, already_in_inventory=True)
    assert ok.status_code == 201 and stock_of(client, h, p["id"]) == 13
    s = [r for r in client.get(f"{SI}/summary", headers=h).json()["products"] if r["product_id"] == p["id"]][0]
    assert s["unpriced"] == 0 and s["priced"] == 13


def test_csv_import_saves_good_rows_and_reports_bad_ones(client, signup):
    h = signup()
    p = product(client, h, name="Standing Desk")
    today = date.today()
    head = "sku,product_name,quantity,vendor_name,vendor_amount,mrp,max_discount_percent,date_of_inward,month_of_manufacture,expiry_date,already_in_inventory\n"
    rows = (f"{p['sku']},,4,Bharat,22000,34999,10,{iso(today)},{today.strftime('%Y-%m')},,no\n"
            f",Standing Desk,3,Bharat,21000,34999,12,{today.strftime('%d/%m/%Y')},,{iso(today + timedelta(days=100))},no\n"
            ",Ghost Product,3,Bharat,1,2,3,,,,no\n"
            f"{p['sku']},,2,Bharat,,34999,10,{iso(today)},,,no\n")
    r = client.post(f"{SI}/import", headers=h, files={"file": ("s.csv", (head + rows).encode(), "text/csv")})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["imported"] == 2 and out["failed"] == 2
    assert {e["row"] for e in out["errors"]} == {4, 5}
    assert stock_of(client, h, p["id"]) == 7
    assert client.get(f"{SI}/import-template", headers=h).status_code == 200
    assert client.post(f"{SI}/import", headers=h, files={"file": ("s.csv", b"a,b\n1,2\n", "text/csv")}).status_code == 400


def test_delete_undoes_an_untouched_batch_only(client, signup):
    h = signup()
    p = product(client, h)
    b = batch(client, h, p["id"], qty=4).json()
    assert stock_of(client, h, p["id"]) == 4
    assert client.delete(f"{SI}/batches/{b['id']}", headers=h).status_code == 204
    assert stock_of(client, h, p["id"]) == 0
    b2 = batch(client, h, p["id"], qty=4).json()
    ed = client.patch(f"{SI}/batches/{b2['id']}", headers=h, json={"mrp": 250, "max_discount_percent": 5})
    assert ed.status_code == 200 and D(ed.json()["mrp"]) == 250 and D(ed.json()["lowest_selling_price"]) == D("237.5")
    assert client.patch(f"{SI}/batches/{b2['id']}", headers=h, json={"max_discount_percent": 150}).status_code == 422
    assert client.patch(f"{SI}/batches/{b2['id']}", headers=h, json={"expiry_date": iso(date.today() - timedelta(days=30))}).status_code == 400


def test_po_receipt_creates_a_batch_and_invoicing_uses_it_up(client, signup):
    h = signup()
    p = product(client, h, price=500)
    vendor = client.post("/api/procurement/vendors", headers=h, json={"name": "Bharath Steels"}).json()
    po = client.post(PO, headers=h, json={"vendor_id": vendor["id"], "items": [{"product_id": p["id"], "qty": 6, "unit_price": 300}]}).json()
    client.post(f"{PO}/{po['id']}/approve", headers=h)
    r = client.post(f"{PO}/{po['id']}/receive-good", headers=h, files={"invoice": ("i.pdf", PDF_BYTES, "application/pdf"), "pod": ("p.png", PNG_BYTES, "image/png")})
    assert r.status_code == 200, r.text
    bs = client.get(f"{SI}/batches?product_id={p['id']}", headers=h).json()
    assert len(bs) == 1 and bs[0]["source"] == "purchase_order" and bs[0]["vendor_name"] == "Bharath Steels"
    assert D(bs[0]["vendor_amount"]) == 300 and D(bs[0]["mrp"]) == 500 and D(bs[0]["max_discount_percent"]) == 0
    assert client.delete(f"{SI}/batches/{bs[0]['id']}", headers=h).status_code == 400
    # a Sales invoice takes 2 out of the total AND out of the priced lot
    cust = client.post("/api/sales/customers", headers=h, json={"name": "C"}).json()
    q = client.post("/api/sales/quotations", headers=h, json={"customer_id": cust["id"], "items": [{"product_id": p["id"], "qty": 2, "unit_price": 500}]}).json()
    order = client.post(f"/api/sales/quotations/{q['id']}/accept", headers=h).json()
    inv = client.post(f"/api/sales/orders/{order['id']}/invoice", headers=h)
    assert inv.status_code == 201, inv.text
    assert stock_of(client, h, p["id"]) == 4
    assert client.get(f"{SI}/batches?product_id={p['id']}", headers=h).json()[0]["quantity_remaining"] == 4


# ------------------------------------------------------------------ the new work cycle
def test_stock_in_inventory_serves_the_work_at_once_then_payment_closes_it(client, signup):
    h = signup()
    p = product(client, h, name="Standing Desk")
    today = date.today()
    batch(client, h, p["id"], qty=3, cost=90, mrp=200, disc=10, expiry=today + timedelta(days=30), vendor="Bharat A")
    batch(client, h, p["id"], qty=10, cost=100, mrp=200, disc=10, expiry=today + timedelta(days=90), vendor="Bharat B")
    batch(client, h, p["id"], qty=100, cost=1, mrp=200, disc=10, inward=today - timedelta(days=10), expiry=today - timedelta(days=1), vendor="Old Stock")
    assert stock_of(client, h, p["id"]) == 113
    w = crm_work(client, h, amount=1000)
    dept, emp = team(client, h)
    # nothing can be taken before the work is allocated
    assert client.put(f"{W}/{w['id']}/items", headers=h, json={"items": [{"product_id": p["id"], "qty": 5}]}).status_code == 200
    early = client.post(f"{W}/{w['id']}/take-from-inventory", headers=h)
    assert early.status_code == 400 and "Allocate" in early.json()["detail"]
    allocate(client, h, w["id"], dept, emp)
    chk = client.get(f"{W}/{w['id']}/stock-check", headers=h).json()
    assert chk["all_available"] and chk["can_issue"] and chk["items"][0]["available"] == 13         # expired lot not offered
    assert [b["take"] for b in chk["items"][0]["batches"]] == [3, 2]                                # first expiry first
    done = client.post(f"{W}/{w['id']}/take-from-inventory", headers=h)
    assert done.status_code == 200, done.text
    d = done.json()
    assert d["status"] == "delivered" and d["delivered_on"] == iso(today)
    assert D(d["vendor_amount"]) == 3 * 90 + 2 * 100                                               # rates from the batches
    assert D(d["profit"]) == 1000 - 470
    assert [i["qty"] for i in d["stock_issues"]] == [3, 2] and d["pending_reason"].startswith("Delivered. Waiting for the customer's payment")
    kinds = [e["kind"] for e in d["events"]]
    assert "stock_issued" in kinds and "delivered" in kinds
    assert stock_of(client, h, p["id"]) == 108
    rem = {b["vendor_name"]: b["quantity_remaining"] for b in client.get(f"{SI}/batches?product_id={p['id']}", headers=h).json()}
    assert rem == {"Bharat A": 0, "Bharat B": 8, "Old Stock": 100}
    # taking it twice is refused
    assert client.post(f"{W}/{w['id']}/take-from-inventory", headers=h).status_code == 400
    # part payment keeps it open; full payment closes it by itself ("work done")
    p1 = client.post(f"{W}/{w['id']}/payments", headers=h, json={"amount": 400, "method": "cash"}).json()
    assert p1["status"] == "delivered" and D(p1["pending_amount"]) == 600
    p2 = client.post(f"{W}/{w['id']}/payments", headers=h, json={"amount": 600, "method": "gpay", "transaction_id": "GPAY1001"}).json()
    assert p2["status"] == "closed" and p2["status_label"] == "Work done" and p2["closed_at"]
    assert any(e["kind"] == "closed" for e in p2["events"])
    hm = home(client, h)
    assert hm["completed"]["count"] == 1 and hm["works"]["done"] == 1 and hm["works"]["total"] == 1
    assert hm["income"]["total"] == 1000


def test_short_stock_waits_with_a_reason_then_follows_the_purchase_order(client, signup):
    h = signup()
    p = product(client, h, name="Chair")
    batch(client, h, p["id"], qty=2, cost=100, mrp=200, disc=10)
    w = crm_work(client, h, amount=1000)
    dept, emp = team(client, h)
    allocate(client, h, w["id"], dept, emp)
    client.put(f"{W}/{w['id']}/items", headers=h, json={"items": [{"product_id": p["id"], "qty": 5}]})
    chk = client.get(f"{W}/{w['id']}/stock-check", headers=h).json()
    assert not chk["all_available"] and chk["items"][0]["short_by"] == 3 and not chk["can_issue"]
    refuse = client.post(f"{W}/{w['id']}/take-from-inventory", headers=h)
    assert refuse.status_code == 400 and "Not enough stock" in refuse.json()["detail"]
    s = client.post(f"{W}/{w['id']}/stock-short", headers=h, json={})
    assert s.status_code == 200 and s.json()["status"] == "po_not_raised"
    assert "need 5, only 2" in s.json()["pending_reason"] and "not raised" in s.json()["pending_reason"]
    # Home: pending, split as 'Stock short'
    hm = home(client, h)["works"]
    assert hm["pending"]["total"] == 1 and {r["key"]: r["count"] for r in hm["pending"]["breakdown"]}["po_not_raised"] == 1
    # the purchase order drives the status from here
    vendor = client.post("/api/procurement/vendors", headers=h, json={"name": "Bharath"}).json()
    po = client.post(PO, headers=h, json={"vendor_id": vendor["id"], "work_order_id": w["id"], "items": [{"product_id": p["id"], "qty": 3, "unit_price": 90}]}).json()
    st = lambda: client.get(f"{W}/{w['id']}", headers=h).json()
    assert st()["status"] == "po_raised"
    client.post(f"{PO}/{po['id']}/approve", headers=h)
    assert st()["status"] == "in_transit" and "on the way" in st()["pending_reason"]
    r = client.post(f"{PO}/{po['id']}/receive-good", headers=h, files={"invoice": ("i.pdf", PDF_BYTES, "application/pdf"), "pod": ("p.png", PNG_BYTES, "image/png")})
    assert r.status_code == 200
    assert st()["status"] == "po_received"
    dv = client.post(f"{W}/{w['id']}/deliver", headers=h, json={"note": "Courier"})
    assert dv.status_code == 200 and dv.json()["status"] == "delivered"
    client.post(f"{W}/{w['id']}/payments", headers=h, json={"amount": 1000, "method": "cash"})
    assert st()["status"] == "closed"
    # deliver-from-stock tick is gone: stock is served only through the inventory action
    w2 = crm_work(client, h, name="Second", amount=500)
    assert client.post(f"{W}/{w2['id']}/deliver", headers=h, json={"from_stock": True}).status_code == 400


def test_defective_goods_show_waiting_for_new_po_and_a_rejected_po_goes_back(client, signup):
    h = signup()
    p = product(client, h)
    w = crm_work(client, h)
    dept, emp = team(client, h)
    allocate(client, h, w["id"], dept, emp)
    vendor = client.post("/api/procurement/vendors", headers=h, json={"name": "V"}).json()
    mk = lambda: client.post(PO, headers=h, json={"vendor_id": vendor["id"], "work_order_id": w["id"], "items": [{"product_id": p["id"], "qty": 1, "unit_price": 50}]}).json()
    st = lambda: client.get(f"{W}/{w['id']}", headers=h).json()["status"]
    po1 = mk()
    client.post(f"{PO}/{po1['id']}/reject", headers=h)
    assert st() == "allocated"
    po2 = mk()
    client.post(f"{PO}/{po2['id']}/approve", headers=h)
    assert st() == "in_transit"
    bad = client.post(f"{PO}/{po2['id']}/receive-bad", headers=h,
                      files=[("invoice", ("i.pdf", PDF_BYTES, "application/pdf")), ("pod", ("p.png", PNG_BYTES, "image/png")), ("defect", ("d.png", PNG_BYTES, "image/png"))], data={"notes": "Cracked"})
    assert bad.status_code == 200 and st() == "waiting_new_po"
    po3 = mk()
    assert st() == "po_raised"
    client.post(f"{PO}/{po3['id']}/approve", headers=h)
    client.post(f"{PO}/{po3['id']}/receive-good", headers=h, files={"invoice": ("i.pdf", PDF_BYTES, "application/pdf"), "pod": ("p.png", PNG_BYTES, "image/png")})
    assert st() == "po_received"


def test_pricing_rule_blocks_billing_above_mrp_or_below_max_discount(client, signup):
    h = signup()
    p = product(client, h)
    batch(client, h, p["id"], qty=10, cost=100, mrp=200, disc=10)       # 5 units: MRP total 1000, floor 900
    dept, emp = team(client, h)

    # quotation above MRP total -> cannot take stock
    over = crm_work(client, h, amount=1200, name="Over MRP")
    allocate(client, h, over["id"], dept, emp)
    client.put(f"{W}/{over['id']}/items", headers=h, json={"items": [{"product_id": p["id"], "qty": 5}]})
    chk = client.get(f"{W}/{over['id']}/stock-check", headers=h).json()
    assert not chk["can_issue"] and "above the MRP" in chk["pricing"]["violations"][0]
    r = client.post(f"{W}/{over['id']}/take-from-inventory", headers=h)
    assert r.status_code == 400 and "above the MRP" in r.json()["detail"]
    assert stock_of(client, h, p["id"]) == 10                                                  # nothing moved
    # fix the amount, but a 15% discount takes it to 850 < 900
    assert client.patch(f"{W}/{over['id']}", headers=h, json={"quotation_amount": 1000, "discount_percent": 15}).status_code == 200
    r = client.post(f"{W}/{over['id']}/take-from-inventory", headers=h)
    assert r.status_code == 400 and "below the lowest allowed price" in r.json()["detail"]
    assert client.patch(f"{W}/{over['id']}", headers=h, json={"discount_percent": 10}).status_code == 200
    ok = client.post(f"{W}/{over['id']}/take-from-inventory", headers=h)
    assert ok.status_code == 200 and D(ok.json()["net_payable"]) == 900
    assert D(ok.json()["pricing"]["limits"]["floor"]) == 900 and ok.json()["pricing"]["violations"] == []

    # after stock is taken the same rule guards edits and payments
    bad = client.patch(f"{W}/{over['id']}", headers=h, json={"discount_percent": 11})
    assert bad.status_code == 400 and "Finance check" in bad.json()["detail"]
    assert client.patch(f"{W}/{over['id']}", headers=h, json={"vendor_amount": 1}).status_code == 400   # cost comes from the batches
    assert D(client.get(f"{W}/{over['id']}", headers=h).json()["discount_percent"]) == 10
    # Finance sees it, compliant
    fc = client.get("/api/finance/pricing-check", headers=h).json()
    assert fc["checked"] == 1 and fc["violations"] == 0 and D(fc["works"][0]["effective_discount_percent"]) == 10


def test_finance_flags_and_blocks_a_bill_that_breaks_the_rule(client, signup):
    """A batch's max discount lowered AFTER stock was issued does not rewrite history, but a changed bill is caught at payment."""
    h = signup()
    p = product(client, h)
    batch(client, h, p["id"], qty=5, cost=100, mrp=200, disc=10)
    dept, emp = team(client, h)
    w = crm_work(client, h, amount=1000)
    allocate(client, h, w["id"], dept, emp)
    client.put(f"{W}/{w['id']}/items", headers=h, json={"items": [{"product_id": p["id"], "qty": 5}]})
    assert client.post(f"{W}/{w['id']}/take-from-inventory", headers=h).status_code == 200
    # simulate a bill that slipped past (direct data change), then try to take money
    from app.core.database import SessionLocal
    from app.models.workpage import WorkOrder
    db = SessionLocal()
    try:
        row = db.query(WorkOrder).filter(WorkOrder.id == w["id"]).first()
        row.discount_percent = Decimal("30")
        db.commit()
    finally:
        db.close()
    pay = client.post(f"{W}/{w['id']}/payments", headers=h, json={"amount": 100, "method": "cash"})
    assert pay.status_code == 400 and "Finance check" in pay.json()["detail"]
    fc = client.get("/api/finance/pricing-check", headers=h).json()
    assert fc["violations"] == 1 and fc["works"][0]["ok"] is False


def test_home_works_split_adds_up_and_follows_every_status(client, signup):
    h = signup()
    p = product(client, h)
    batch(client, h, p["id"], qty=20, cost=100, mrp=200, disc=10)
    dept, emp = team(client, h)
    w1 = crm_work(client, h, name="One", amount=1000)                       # stays assigned
    w2 = crm_work(client, h, name="Two", amount=1000)                       # allocated
    allocate(client, h, w2["id"], dept, emp)
    w3 = crm_work(client, h, name="Three", amount=1000)                     # served from stock -> delivered
    allocate(client, h, w3["id"], dept, emp)
    client.put(f"{W}/{w3['id']}/items", headers=h, json={"items": [{"product_id": p["id"], "qty": 5}]})
    client.post(f"{W}/{w3['id']}/take-from-inventory", headers=h)
    w4 = crm_work(client, h, name="Four", amount=1000)                      # closed
    allocate(client, h, w4["id"], dept, emp)
    client.put(f"{W}/{w4['id']}/items", headers=h, json={"items": [{"product_id": p["id"], "qty": 5}]})
    client.post(f"{W}/{w4['id']}/take-from-inventory", headers=h)
    client.post(f"{W}/{w4['id']}/payments", headers=h, json={"amount": 1000, "method": "cash"})
    w5 = crm_work(client, h, name="Five", amount=1000)                      # stock short
    allocate(client, h, w5["id"], dept, emp)
    client.put(f"{W}/{w5['id']}/items", headers=h, json={"items": [{"product_id": p["id"], "qty": 500}]})
    client.post(f"{W}/{w5['id']}/stock-short", headers=h, json={})
    for period in ("today", "week", "month"):
        wk = home(client, h, period)["works"]
        by = {r["key"]: r["count"] for r in wk["pending"]["breakdown"]}
        assert wk["total"] == 5 and wk["assigned"] == 1 and wk["allocated"] == 1 and wk["done"] == 1, period
        assert wk["pending"]["total"] == 2 and by["delivered"] == 1 and by["po_not_raised"] == 1, period
        assert wk["assigned"] + wk["allocated"] + wk["pending"]["total"] + wk["done"] == wk["total"], period
        assert wk["open_now"] == 4
    # the list page and Home agree on every status
    counts = client.get(W, headers=h).json()["counts"]
    assert counts["assigned"] == 1 and counts["allocated"] == 1 and counts["delivered"] == 1 and counts["closed"] == 1 and counts["po_not_raised"] == 1
    # the bulk / manual entry still works and lands as Assigned
    r = client.post(f"{W}/import", headers=h, files={"file": ("w.csv", b"client_name,client_mobile,domain,quotation_amount\nField Co,9876500009,Retail,2500\n,1,2,3\n", "text/csv")})
    assert r.status_code == 200 and r.json()["imported"] == 1 and r.json()["failed"] == 1
    assert home(client, h)["works"]["assigned"] == 2
