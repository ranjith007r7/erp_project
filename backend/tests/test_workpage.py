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


def test_deliver_rules(client, signup):
    h = signup()
    d1 = client.post("/api/hr/departments", headers=h, json={"name": "Ops"}).json()
    e = client.post("/api/hr/employees", headers=h, json={"name": "Anu", "department_id": d1["id"]}).json()
    w = new_work(client, h)
    assert client.post(f"{W}/{w['id']}/deliver", headers=h, json={}).status_code == 400          # still assigned
    client.post(f"{W}/{w['id']}/allocate", headers=h, json={"department_id": d1["id"], "employee_id": e["id"]})
    r = client.post(f"{W}/{w['id']}/deliver", headers=h, json={})
    assert r.status_code == 400 and "from stock" in r.json()["detail"]
    r = client.post(f"{W}/{w['id']}/deliver", headers=h, json={"from_stock": True, "note": "Hand delivered"})
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
    client.post(f"{W}/{w['id']}/deliver", headers=h, json={"from_stock": True})
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
    assert p2.status_code == 201 and D(p2.json()["pending_amount"]) == 0 and p2.json()["can_close"] is True
    other = new_work(client, h)
    dup = client.post(f"{W}/{other['id']}/payments", headers=h, json={"amount": 10, "method": "gpay", "transaction_id": "UPI12345"})
    assert dup.status_code == 400 and "already" in dup.json()["detail"]
    closed = client.post(f"{W}/{w['id']}/close", headers=h)
    assert closed.status_code == 200 and closed.json()["status"] == "closed" and closed.json()["closed_at"]
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
    assert d["quotation"]["id"] == q["id"] and "moved to the purchase team" in d["events"][0]["title"]


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
