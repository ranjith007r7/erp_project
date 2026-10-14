"""Workpage: statuses synced from Sales/Procurement, profit maths, history, payment-gated closing."""
import logging
import uuid
from decimal import Decimal

import pytest
from conftest import PNG_BYTES, PDF_BYTES, login_any

W = "/api/workpage/works"
PO = "/api/procurement/purchase-orders"


@pytest.fixture(autouse=True)
def _enable_email_logger():
    logging.getLogger("erp.email").disabled = False


def D(x):
    return Decimal(str(x))


def new_work(client, h, **kw):
    body = {"client_name": "Acme Textiles", "domain": "Manufacturing", "quotation_amount": 1000, "vendor_amount": 600, "discount_percent": 10}
    body.update(kw)
    r = client.post(W, headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def po_for(client, h, work_id, qty=5):
    product = client.post("/api/sales/products", headers=h, json={"name": f"Rod {uuid.uuid4().hex[:4]}", "unit_price": 100}).json()
    vendor = client.post("/api/procurement/vendors", headers=h, json={"name": "Bharath Steels"}).json()
    r = client.post(PO, headers=h, json={"vendor_id": vendor["id"], "work_order_id": work_id,
                                         "items": [{"product_id": product["id"], "qty": qty, "unit_price": 60}]})
    assert r.status_code == 201, r.text
    return r.json()


def files():
    return {"invoice": ("inv.pdf", PDF_BYTES, "application/pdf"), "pod": ("pod.png", PNG_BYTES, "image/png")}


def get(client, h, wid):
    return client.get(f"{W}/{wid}", headers=h).json()


def test_new_work_is_assigned_and_profit_is_quote_minus_discount_minus_vendor(client, signup):
    h = signup()
    w = new_work(client, h)
    assert w["status"] == "assigned" and w["work_number"] == "WK-0001"
    # 1000 - 10% (100) - 600 vendor = 300
    assert D(w["discount_amount"]) == 100 and D(w["net_payable"]) == 900 and D(w["profit"]) == 300
    assert w["events"][0]["kind"] == "created"
    assert new_work(client, h)["work_number"] == "WK-0002"
    lst = client.get(W, headers=h).json()
    assert lst["total"] == 2 and lst["counts"]["assigned"] == 2
    row = lst["works"][0]
    assert {"client_name", "domain", "status_label", "quotation_amount", "vendor_amount", "discount_percent", "profit", "handling_department"} <= set(row)


def test_allocate_sets_department_and_employee_and_checks_membership(client, signup):
    h = signup()
    d1 = client.post("/api/hr/departments", headers=h, json={"name": "Warehouse"}).json()
    d2 = client.post("/api/hr/departments", headers=h, json={"name": "Sales"}).json()
    e = client.post("/api/hr/employees", headers=h, json={"name": "Ravi", "department_id": d1["id"]}).json()
    w = new_work(client, h)
    bad = client.post(f"{W}/{w['id']}/allocate", headers=h, json={"department_id": d2["id"], "employee_id": e["id"]})
    assert bad.status_code == 400 and "does not belong" in bad.json()["detail"]
    ok = client.post(f"{W}/{w['id']}/allocate", headers=h, json={"department_id": d1["id"], "employee_id": e["id"]})
    assert ok.status_code == 200
    d = ok.json()
    assert d["status"] == "allocated" and d["handling_department"] == "Warehouse"
    assert d["allocated_employee"]["name"] == "Ravi" and d["allocated_employee"]["employee_code"]


def test_po_lifecycle_syncs_status_good_receipt(client, signup):
    h = signup()
    w = new_work(client, h)
    po = po_for(client, h, w["id"])
    d = get(client, h, w["id"])
    assert d["status"] == "po_raised" and d["purchase_orders"][0]["po_number"] == po["po_number"]
    assert po["work_order_id"] == w["id"]
    client.post(f"{PO}/{po['id']}/approve", headers=h)
    client.post(f"{PO}/{po['id']}/send-email", headers=h, json={"to_email": "v@x.com"})
    r = client.post(f"{PO}/{po['id']}/receive-good", headers=h, files=files())
    assert r.status_code == 200, r.text
    d = get(client, h, w["id"])
    assert d["status"] == "po_received"
    kinds = [e["kind"] for e in d["events"]]
    assert kinds[:1] == ["created"] and "po_raised" in kinds and "po_approved" in kinds and "po_sent" in kinds and "po_received" in kinds
    assert d["purchase_orders"][0]["assigned_to"] == "Test Admin"
    assert d["purchase_orders"][0]["receipts"][0]["condition"] == "good"


def test_defective_receipt_waits_for_new_po_then_replacement_marks_received(client, signup):
    h = signup()
    w = new_work(client, h)
    po1 = po_for(client, h, w["id"])
    client.post(f"{PO}/{po1['id']}/approve", headers=h)
    bad = client.post(f"{PO}/{po1['id']}/receive-bad", headers=h,
                      files=[("invoice", ("i.pdf", PDF_BYTES, "application/pdf")), ("pod", ("p.png", PNG_BYTES, "image/png")),
                             ("defect", ("d.png", PNG_BYTES, "image/png"))], data={"notes": "Bent rods"})
    assert bad.status_code == 200, bad.text
    d = get(client, h, w["id"])
    assert d["status"] == "waiting_new_po" and d["status_label"] == "Waiting for new PO"
    # the send-back (defect notice) is logged on the work automatically
    rid = bad.json()["receipts"][0]["id"]
    client.post(f"/api/procurement/receipts/{rid}/print-notice", headers=h)
    assert any(e["kind"] == "send_back" for e in get(client, h, w["id"])["events"])
    po2 = po_for(client, h, w["id"])
    assert get(client, h, w["id"])["status"] == "po_raised"
    client.post(f"{PO}/{po2['id']}/approve", headers=h)
    client.post(f"{PO}/{po2['id']}/receive-good", headers=h, files=files())
    assert get(client, h, w["id"])["status"] == "po_received"   # defective PO1 is superseded


def test_rejected_po_returns_work_to_assigned(client, signup):
    h = signup()
    w = new_work(client, h)
    po = po_for(client, h, w["id"])
    client.post(f"{PO}/{po['id']}/reject", headers=h)
    assert get(client, h, w["id"])["status"] == "assigned"


def to_po_received(client, h, w):
    po = po_for(client, h, w["id"])
    client.post(f"{PO}/{po['id']}/approve", headers=h)
    r = client.post(f"{PO}/{po['id']}/receive-good", headers=h, files=files())
    assert r.status_code == 200, r.text
    return po


def test_deliver_rules(client, signup):
    h = signup()
    d1 = client.post("/api/hr/departments", headers=h, json={"name": "Ops"}).json()
    e = client.post("/api/hr/employees", headers=h, json={"name": "Anu", "department_id": d1["id"]}).json()
    w = new_work(client, h)
    assert client.post(f"{W}/{w['id']}/deliver", headers=h, json={}).status_code == 400          # still assigned
    client.post(f"{W}/{w['id']}/allocate", headers=h, json={"department_id": d1["id"], "employee_id": e["id"]})
    r = client.post(f"{W}/{w['id']}/deliver", headers=h, json={})
    assert r.status_code == 400 and "Nothing to deliver" in r.json()["detail"]
    assert client.post(f"{W}/{w['id']}/deliver", headers=h, json={"from_stock": True}).status_code == 400   # stock is served via inventory
    to_po_received(client, h, w)
    r = client.post(f"{W}/{w['id']}/deliver", headers=h, json={"note": "Hand delivered"})
    assert r.status_code == 200 and r.json()["status"] == "delivered"


def test_cannot_deliver_while_waiting_for_po(client, signup):
    h = signup()
    w = new_work(client, h)
    po_for(client, h, w["id"])
    assert client.post(f"{W}/{w['id']}/deliver", headers=h, json={}).status_code == 400


def test_payments_partial_full_and_closing_gate(client, signup):
    h = signup()
    d1 = client.post("/api/hr/departments", headers=h, json={"name": "Ops"}).json()
    e = client.post("/api/hr/employees", headers=h, json={"name": "Anu", "department_id": d1["id"]}).json()
    w = new_work(client, h)   # net payable 900
    client.post(f"{W}/{w['id']}/allocate", headers=h, json={"department_id": d1["id"], "employee_id": e["id"]})
    to_po_received(client, h, w)
    assert client.post(f"{W}/{w['id']}/deliver", headers=h, json={}).status_code == 200
    # cannot close unpaid
    r = client.post(f"{W}/{w['id']}/close", headers=h)
    assert r.status_code == 400 and "900" in r.json()["detail"]
    p1 = client.post(f"{W}/{w['id']}/payments", headers=h, json={"amount": 400, "method": "cash"})
    assert p1.status_code == 201 and D(p1.json()["received_amount"]) == 400 and D(p1.json()["pending_amount"]) == 500
    assert client.post(f"{W}/{w['id']}/close", headers=h).status_code == 400
    # rules: reference needed, no duplicate ref, no over-payment, no zero
    assert client.post(f"{W}/{w['id']}/payments", headers=h, json={"amount": 100, "method": "gpay"}).status_code == 400
    assert client.post(f"{W}/{w['id']}/payments", headers=h, json={"amount": 501, "method": "cash"}).status_code == 400
    assert client.post(f"{W}/{w['id']}/payments", headers=h, json={"amount": 0, "method": "cash"}).status_code == 422
    p2 = client.post(f"{W}/{w['id']}/payments", headers=h, json={"amount": 500, "method": "gpay", "transaction_id": "UPI12345"})
    assert p2.status_code == 201 and D(p2.json()["pending_amount"]) == 0
    assert get(client, h, w["id"])["status"] == "closed"      # fully paid + delivered closes by itself
    other = new_work(client, h)
    dup = client.post(f"{W}/{other['id']}/payments", headers=h, json={"amount": 10, "method": "gpay", "transaction_id": "UPI12345"})
    assert dup.status_code == 400 and "already" in dup.json()["detail"]
    closed = get(client, h, w["id"])
    assert closed["status"] == "closed" and closed["closed_at"]
    assert client.post(f"{W}/{w['id']}/payments", headers=h, json={"amount": 1, "method": "cash"}).status_code == 400
    assert client.patch(f"{W}/{w['id']}", headers=h, json={"domain": "x"}).status_code == 400
    # money reached the books
    je = client.get("/api/finance/journal-entries", headers=h).json()
    assert sum(1 for j in je if (j["reference"] or "").startswith("WPMT-")) == 2


def test_edit_amounts_logged_and_cannot_drop_below_received(client, signup):
    h = signup()
    w = new_work(client, h)
    client.post(f"{W}/{w['id']}/payments", headers=h, json={"amount": 800, "method": "cash"})
    bad = client.patch(f"{W}/{w['id']}", headers=h, json={"quotation_amount": 500})
    assert bad.status_code == 400
    ok = client.patch(f"{W}/{w['id']}", headers=h, json={"vendor_amount": 650})
    assert ok.status_code == 200 and D(ok.json()["profit"]) == 250
    assert any(e["kind"] == "edited" for e in ok.json()["events"])
    assert client.patch(f"{W}/{w['id']}", headers=h, json={"discount_percent": 150}).status_code == 422


def test_accepting_a_quotation_opens_a_work_once(client, signup):
    h = signup()
    cust = client.post("/api/sales/customers", headers=h, json={"name": "Globex"}).json()
    prod = client.post("/api/sales/products", headers=h, json={"name": "Widget", "unit_price": 50}).json()
    q = client.post("/api/sales/quotations", headers=h, json={"customer_id": cust["id"], "items": [{"product_id": prod["id"], "qty": 4, "unit_price": 50}]}).json()
    assert client.post(f"/api/sales/quotations/{q['id']}/accept", headers=h).status_code == 201
    works = client.get(W, headers=h).json()["works"]
    assert len(works) == 1 and works[0]["client_name"] == "Globex" and D(works[0]["quotation_amount"]) == 200
    d = get(client, h, works[0]["id"])
    assert d["quotation"]["id"] == q["id"] and d["work_type"] == "sales_order" and "Sales order accepted" in d["events"][0]["title"]


def test_other_org_cannot_see_or_link_a_work(client, signup):
    a, b = signup(), signup()
    w = new_work(client, a)
    assert client.get(f"{W}/{w['id']}", headers=b).status_code == 404
    assert client.get(W, headers=b).json()["total"] == 0
    product = client.post("/api/sales/products", headers=b, json={"name": "P", "unit_price": 1}).json()
    vendor = client.post("/api/procurement/vendors", headers=b, json={"name": "V"}).json()
    r = client.post(PO, headers=b, json={"vendor_id": vendor["id"], "work_order_id": w["id"], "items": [{"product_id": product["id"], "qty": 1, "unit_price": 1}]})
    assert r.status_code == 400


def test_permissions_view_vs_edit_vs_close(client, signup):
    admin = signup()
    unique = uuid.uuid4().hex[:8]
    role = client.post("/api/core/roles", headers=admin, json={"name": f"Viewer {unique}"}).json()
    client.post(f"/api/core/roles/{role['id']}/permissions", headers=admin, json={"module": "workpage", "action": "view"})
    email = f"v-{unique}@test.com"
    client.post("/api/core/users", headers=admin, json={"name": "Vi", "email": email, "password": "pass12345", "role_id": role["id"]})
    v = {"Authorization": f"Bearer {login_any(client, email, 'pass12345').json()['access_token']}"}
    w = new_work(client, admin)
    assert client.get(W, headers=v).status_code == 200
    assert client.post(W, headers=v, json={"client_name": "x"}).status_code == 403
    assert client.post(f"{W}/{w['id']}/payments", headers=v, json={"amount": 1, "method": "cash"}).status_code == 403
    assert client.post(f"{W}/{w['id']}/close", headers=v).status_code == 403


def test_delete_only_untouched_assigned_work(client, signup):
    h = signup()
    w = new_work(client, h)
    po = po_for(client, h, w["id"])
    assert client.delete(f"{W}/{w['id']}", headers=h).status_code == 400
    w2 = new_work(client, h)
    assert client.delete(f"{W}/{w2['id']}", headers=h).status_code == 204
    assert client.get(f"{W}/{w2['id']}", headers=h).status_code == 404


def test_a_failing_hook_never_breaks_procurement(client, signup, monkeypatch):
    from app.services import workpages
    def boom(*a, **k):
        raise RuntimeError("sync broke")
    monkeypatch.setattr(workpages, "on_po_created", boom)
    h = signup()
    w = new_work(client, h)
    po = po_for(client, h, w["id"])          # still 201
    assert get(client, h, w["id"])["status"] == "assigned"


def test_reset_and_delete_organization_clear_works(client, signup):
    from app.core import database as dbm
    from app.models.workpage import WorkOrder, WorkEvent, WorkPayment
    from app.services import org_data
    h = signup()
    org_id = client.get("/api/auth/me", headers=h).json()["org_id"]
    w = new_work(client, h)
    client.post(f"{W}/{w['id']}/payments", headers=h, json={"amount": 100, "method": "cash"})
    po_for(client, h, w["id"])
    s = dbm.SessionLocal()
    try:
        assert s.query(WorkOrder).filter(WorkOrder.org_id == org_id).count() == 1
        org_data.reset_business_data(s, org_id)
        s.commit()
        assert s.query(WorkOrder).filter(WorkOrder.org_id == org_id).count() == 0
        assert s.query(WorkEvent).filter(WorkEvent.org_id == org_id).count() == 0
        assert s.query(WorkPayment).filter(WorkPayment.org_id == org_id).count() == 0
    finally:
        s.close()


def test_import_accepted_backfills_old_quotes(client, signup):
    h = signup()
    cust = client.post("/api/sales/customers", headers=h, json={"name": "Old Client"}).json()
    prod = client.post("/api/sales/products", headers=h, json={"name": f"Pipe {uuid.uuid4().hex[:4]}", "unit_price": 100}).json()
    q = client.post("/api/sales/quotations", headers=h, json={"customer_id": cust["id"], "items": [{"product_id": prod["id"], "qty": 2, "unit_price": 100}]}).json()
    assert client.post(f"/api/sales/quotations/{q['id']}/accept", headers=h).status_code == 201
    # simulate "accepted before the update": remove the work that the hook made
    works = client.get(W, headers=h).json()["works"]
    mine = [w for w in works if w["client_name"] == "Old Client"]
    assert len(mine) == 1
    assert client.delete(f"{W}/{mine[0]['id']}", headers=h).status_code == 204
    r = client.post("/api/workpage/import-accepted", headers=h)
    assert r.status_code == 200 and r.json()["created"] >= 1
    again = client.post("/api/workpage/import-accepted", headers=h).json()
    assert again["created"] == 0
    works = client.get(W, headers=h).json()["works"]
    assert any(w["client_name"] == "Old Client" and w["status"] == "assigned" for w in works)


def test_finance_reconciliation_matches_quoted_received_and_booked(client, signup):
    h = signup()
    w = new_work(client, h)    # net payable 900
    d1 = client.post("/api/hr/departments", headers=h, json={"name": "Ops"}).json()
    e = client.post("/api/hr/employees", headers=h, json={"name": "Anu", "department_id": d1["id"]}).json()
    client.post(f"{W}/{w['id']}/allocate", headers=h, json={"department_id": d1["id"], "employee_id": e["id"]})
    R = "/api/finance/work-reconciliation"
    row = lambda: next(r for r in client.get(R, headers=h).json()["works"] if r["work_id"] == w["id"])
    assert row()["state"] == "not_started" and D(row()["quoted_net"]) == 900
    to_po_received(client, h, w)
    client.post(f"{W}/{w['id']}/deliver", headers=h, json={})
    assert row()["state"] == "awaiting_payment"
    client.post(f"{W}/{w['id']}/payments", headers=h, json={"amount": 400, "method": "cash"})
    r = row()
    assert r["state"] == "part_paid" and D(r["received"]) == 400 and D(r["booked_in_finance"]) == 400 and D(r["difference"]) == 500
    assert client.post(f"{W}/{w['id']}/close", headers=h).status_code == 400            # quoted != received: cannot be Work done
    client.post(f"{W}/{w['id']}/payments", headers=h, json={"amount": 500, "method": "cash"})
    r = row()
    assert r["state"] == "matched" and D(r["received"]) == D(r["booked_in_finance"]) == D(r["quoted_net"]) == 900
    out = client.get(R, headers=h).json()
    assert out["matched"] == 1 and out["mismatch"] == 0


def test_reconciliation_advance_paid_work_is_not_a_mismatch(client, signup):
    h = signup()
    w = new_work(client, h)    # net payable 900
    assert client.post(f"{W}/{w['id']}/payments", headers=h, json={"amount": 900, "method": "cash"}).status_code == 201
    R = "/api/finance/work-reconciliation"
    out = client.get(R, headers=h).json()
    r = next(x for x in out["works"] if x["work_id"] == w["id"])
    assert r["state"] == "paid_awaiting_delivery" and out["mismatch"] == 0 and out["open"] == 1


# ---------------------------------------------------------------- bug-report fixes (11 Oct)
def _stock(client, h, product_id):
    rows = client.get("/api/inventory/stock-levels", headers=h).json()
    return sum(r["quantity"] for r in rows if r["product_id"] == product_id)


def _po_work(client, h, buy=3, need=1, list_items=True):
    """A work whose goods are bought on a PO (bought `buy`, the work needs `need`), received, ready to deliver."""
    d1 = client.post("/api/hr/departments", headers=h, json={"name": "Ops"}).json()
    e = client.post("/api/hr/employees", headers=h, json={"name": "Anu", "department_id": d1["id"]}).json()
    w = new_work(client, h)
    client.post(f"{W}/{w['id']}/allocate", headers=h, json={"department_id": d1["id"], "employee_id": e["id"]})
    prod = client.post("/api/sales/products", headers=h, json={"name": f"Kit {uuid.uuid4().hex[:4]}", "unit_price": 100}).json()
    if list_items:
        assert client.put(f"{W}/{w['id']}/items", headers=h, json={"items": [{"product_id": prod["id"], "qty": need}]}).status_code == 200
        assert client.post(f"{W}/{w['id']}/stock-short", headers=h, json={}).status_code == 200
    vendor = client.post("/api/procurement/vendors", headers=h, json={"name": "Bharath Mounts"}).json()
    linked = min(buy, need) if list_items else buy        # a PO for a work buys what the work needs; extra stock is its own PO
    for qty, wid in [(linked, w["id"]), (buy - linked, None)]:
        if not qty:
            continue
        po = client.post(PO, headers=h, json={"vendor_id": vendor["id"], **({"work_order_id": wid} if wid else {}),
                                              "items": [{"product_id": prod["id"], "qty": qty, "unit_price": 60}]})
        assert po.status_code == 201, po.text
        po = po.json()
        client.post(f"{PO}/{po['id']}/approve", headers=h)
        assert client.post(f"{PO}/{po['id']}/receive-good", headers=h, files=files()).status_code == 200
    return w, prod


def test_po_for_a_work_cannot_order_more_than_the_work_needs(client, signup):
    h = signup()
    d1 = client.post("/api/hr/departments", headers=h, json={"name": "Ops"}).json()
    e = client.post("/api/hr/employees", headers=h, json={"name": "Anu", "department_id": d1["id"]}).json()
    w = new_work(client, h)
    client.post(f"{W}/{w['id']}/allocate", headers=h, json={"department_id": d1["id"], "employee_id": e["id"]})
    prod = client.post("/api/sales/products", headers=h, json={"name": "Kit", "unit_price": 100}).json()
    other = client.post("/api/sales/products", headers=h, json={"name": "Cable", "unit_price": 10}).json()
    client.put(f"{W}/{w['id']}/items", headers=h, json={"items": [{"product_id": prod["id"], "qty": 3}]})
    client.post(f"{W}/{w['id']}/stock-short", headers=h, json={})
    vendor = client.post("/api/procurement/vendors", headers=h, json={"name": "V"}).json()
    body = lambda pid, q, wid=w["id"]: {"vendor_id": vendor["id"], "work_order_id": wid, "items": [{"product_id": pid, "qty": q, "unit_price": 2500}]}
    r = client.post(PO, headers=h, json=body(prod["id"], 5))
    assert r.status_code == 400 and "needs 3" in r.json()["detail"] and "Stock for future" in r.json()["detail"]
    assert client.post(PO, headers=h, json=body(other["id"], 1)).status_code == 400          # not on the work's list
    ow = client.get(f"{W.replace('/works', '')}/open-works", headers=h).json()
    assert ow[0]["needs"][0]["needed"] == 3 and ow[0]["needs"][0]["remaining"] == 3
    # exactly what is needed: accepted, and the work's vendor amount follows by itself (3 x 2500)
    assert client.post(PO, headers=h, json=body(prod["id"], 3)).status_code == 201
    assert float(get(client, h, w["id"])["vendor_amount"]) == 7500
    assert client.post(PO, headers=h, json=body(prod["id"], 1)).status_code == 400            # already covered
    # extra stock for the future is a PO that is not tied to a work
    assert client.post(PO, headers=h, json=body(prod["id"], 5, None) | {"work_order_id": None}).status_code == 201
    assert float(get(client, h, w["id"])["vendor_amount"]) == 7500


def test_delivered_po_work_exposes_a_bill_summary_of_what_it_used(client, signup):
    h = signup()
    w, prod = _po_work(client, h, buy=3, need=2)
    assert client.post(f"{W}/{w['id']}/deliver", headers=h, json={}).status_code == 200
    d = get(client, h, w["id"])
    assert [(i["qty"], float(i["cost_rate"])) for i in d["purchased_items"]] == [(2, 60.0)]


def test_po_fed_work_takes_its_quantity_out_of_inventory_on_delivery(client, signup):
    h = signup()
    w, prod = _po_work(client, h, buy=3, need=1)
    assert _stock(client, h, prod["id"]) == 3                      # received into Inventory
    assert client.post(f"{W}/{w['id']}/deliver", headers=h, json={}).status_code == 200
    assert _stock(client, h, prod["id"]) == 2                      # bought 3, the work used 1
    assert any(e["kind"] == "stock_issued" for e in get(client, h, w["id"])["events"])
    # the leftover units are real stock for the next work: a second PO-less take sees 2, not 3
    assert client.get(f"{W}/{w['id']}/stock-check", headers=h).status_code == 200


def test_quantity_can_be_edited_after_the_po_arrives_and_delivery_uses_it(client, signup):
    h = signup()
    w, prod = _po_work(client, h, buy=3, need=1)
    # wrong quantity typed: fix it without a new quotation
    r = client.put(f"{W}/{w['id']}/items", headers=h, json={"items": [{"product_id": prod["id"], "qty": 3}]})
    assert r.status_code == 200 and get(client, h, w["id"])["items"][0]["qty"] == 3
    assert client.post(f"{W}/{w['id']}/deliver", headers=h, json={}).status_code == 200
    assert _stock(client, h, prod["id"]) == 0
    # once delivered the list is locked
    assert client.put(f"{W}/{w['id']}/items", headers=h, json={"items": [{"product_id": prod["id"], "qty": 1}]}).status_code == 400


def test_po_work_without_item_list_uses_the_po_quantities(client, signup):
    h = signup()
    w, prod = _po_work(client, h, buy=2, need=1, list_items=False)
    assert client.post(f"{W}/{w['id']}/deliver", headers=h, json={}).status_code == 200
    assert _stock(client, h, prod["id"]) == 0


def test_delivery_is_refused_when_the_stock_is_no_longer_there(client, signup):
    h = signup()
    w, prod = _po_work(client, h, buy=1, need=1)
    # someone raises the quantity beyond what is in Inventory
    client.put(f"{W}/{w['id']}/items", headers=h, json={"items": [{"product_id": prod["id"], "qty": 5}]})
    r = client.post(f"{W}/{w['id']}/deliver", headers=h, json={})
    assert r.status_code == 400 and "only 1 is in Inventory" in r.json()["detail"]
    assert get(client, h, w["id"])["status"] == "po_received" and _stock(client, h, prod["id"]) == 1


def test_client_mobile_must_be_exactly_ten_digits(client, signup):
    h = signup()
    for bad in ["988409884002202", "12345", "98840 9884A", "98765432101"]:
        assert client.post("/api/crm/leads", headers=h, json={"name": "A", "phone": bad}).status_code == 422, bad
        assert client.post(W, headers=h, json={"client_name": "A", "client_mobile": bad}).status_code == 422, bad
    ok = client.post("/api/crm/leads", headers=h, json={"name": "A", "phone": "+91 98765-43210"})
    assert ok.status_code == 201 and ok.json()["phone"] == "9876543210"
    w = client.post(W, headers=h, json={"client_name": "A", "client_mobile": "98765 43210"})
    assert w.status_code == 201 and w.json()["client_mobile"] == "9876543210"
    assert client.patch(f"{W}/{w.json()['id']}", headers=h, json={"client_mobile": "1234567"}).status_code == 422


def test_po_for_a_work_orders_only_the_shortfall_and_vendor_cost_is_the_real_cost(client, signup):
    """Hold 5 (cost 2500), the work needs 6: only 1 may be ordered; vendor amount = 5 x 2500 + 1 x 4000, before and after delivery."""
    h = signup()
    prod = client.post("/api/sales/products", headers=h, json={"name": "Kit", "unit_price": 100}).json()
    client.post("/api/stockin/batches", headers=h, json={"product_id": prod["id"], "quantity": 5, "vendor_name": "Old", "vendor_amount": 2500, "mrp": 4000, "max_discount_percent": 0})
    d1 = client.post("/api/hr/departments", headers=h, json={"name": "Ops"}).json()
    e = client.post("/api/hr/employees", headers=h, json={"name": "Anu", "department_id": d1["id"]}).json()
    w = new_work(client, h)
    client.post(f"{W}/{w['id']}/allocate", headers=h, json={"department_id": d1["id"], "employee_id": e["id"]})
    client.put(f"{W}/{w['id']}/items", headers=h, json={"items": [{"product_id": prod["id"], "qty": 6}]})
    assert client.post(f"{W}/{w['id']}/stock-short", headers=h, json={}).status_code == 200
    need = client.get("/api/workpage/open-works", headers=h).json()[0]["needs"][0]
    assert (need["needed"], need["in_stock"], need["remaining"]) == (6, 5, 1)
    vendor = client.post("/api/procurement/vendors", headers=h, json={"name": "Bharath"}).json()
    body = lambda q: {"vendor_id": vendor["id"], "work_order_id": w["id"], "items": [{"product_id": prod["id"], "qty": q, "unit_price": 4000}]}
    r = client.post(PO, headers=h, json=body(6))
    assert r.status_code == 400 and "5 already in stock" in r.json()["detail"] and "at most 1" in r.json()["detail"]
    po = client.post(PO, headers=h, json=body(1)).json()
    assert float(get(client, h, w["id"])["vendor_amount"]) == 16500          # 5 x 2500 from stock + 1 x 4000 on order
    client.post(f"{PO}/{po['id']}/approve", headers=h)
    assert client.post(f"{PO}/{po['id']}/receive-good", headers=h, files=files()).status_code == 200
    assert float(get(client, h, w["id"])["vendor_amount"]) == 16500
    # the new lot's cost was keyed wrong (4000, really 3000): correcting the lot flows into the work
    lot = [b for b in client.get("/api/stockin/batches", headers=h).json() if float(b["vendor_amount"]) == 4000][0]
    assert client.patch(f"/api/stockin/batches/{lot['id']}", headers=h, json={"vendor_amount": 3000}).status_code == 200
    assert float(get(client, h, w["id"])["vendor_amount"]) == 15500
    lots = client.get("/api/stockin/batches", headers=h).json()
    assert "cost 4000.00 -> 3000.00" in [b for b in lots if b["id"] == lot["id"]][0]["note"]       # trail stays on the lot
    assert client.post(f"{W}/{w['id']}/deliver", headers=h, json={}).status_code == 200
    d = get(client, h, w["id"])
    assert float(d["vendor_amount"]) == 15500 and sum(i["qty"] for i in d["purchased_items"]) == 6
    assert _stock(client, h, prod["id"]) == 0


def test_mrp_message_shows_where_the_ceiling_comes_from():
    from app.services import pricing
    msg = pricing.violations(36000, 10, [(5, 4000, 0), (1, 6000, 10)])[0]
    assert "26000.00 = 5 x 4000.00 + 1 x 6000.00" in msg and "lot's MRP" in msg
