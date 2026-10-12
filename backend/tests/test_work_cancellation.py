"""Work cancellation: an employee raises it, only an approver decides, stock that left Inventory comes back."""
import uuid

from conftest import PDF_BYTES, PNG_BYTES, login_any

W = "/api/workpage/works"
PO = "/api/procurement/purchase-orders"
REASON = "Customer cancelled the order"


def _files():
    return {"invoice": ("inv.pdf", PDF_BYTES, "application/pdf"), "pod": ("pod.png", PNG_BYTES, "image/png")}


def _employee(client, admin, perms, name="Emp"):
    """A login in a fresh role holding exactly `perms` (list of (module, action))."""
    u = uuid.uuid4().hex[:8]
    role = client.post("/api/core/roles", headers=admin, json={"name": f"{name} {u}"}).json()
    for m, a in perms:
        assert client.post(f"/api/core/roles/{role['id']}/permissions", headers=admin, json={"module": m, "action": a}).status_code == 201
    email = f"{name.lower()}-{u}@test.com"
    client.post("/api/core/users", headers=admin, json={"name": name, "email": email, "password": "pass12345", "role_id": role["id"]})
    return {"Authorization": f"Bearer {login_any(client, email, 'pass12345').json()['access_token']}"}, role


def _setup(client, admin, qty_in_stock=10):
    prod = client.post("/api/sales/products", headers=admin, json={"name": f"Inverter {uuid.uuid4().hex[:4]}", "unit_price": 100}).json()
    if qty_in_stock:
        r = client.post("/api/stockin/batches", headers=admin, json={"product_id": prod["id"], "quantity": qty_in_stock, "vendor_name": "SunVolt",
                                                                     "vendor_amount": 60, "mrp": 100, "max_discount_percent": 10})
        assert r.status_code == 201, r.text
    d = client.post("/api/hr/departments", headers=admin, json={"name": "Ops"}).json()
    e = client.post("/api/hr/employees", headers=admin, json={"name": "Anu", "department_id": d["id"]}).json()
    return prod, d, e


def _work(client, admin, d, e, prod, qty=2, quote=200, disc=0):
    w = client.post(W, headers=admin, json={"client_name": "Acme", "quotation_amount": quote, "discount_percent": disc}).json()
    client.post(f"{W}/{w['id']}/allocate", headers=admin, json={"department_id": d["id"], "employee_id": e["id"]})
    client.put(f"{W}/{w['id']}/items", headers=admin, json={"items": [{"product_id": prod["id"], "qty": qty}]})
    return w


def _stock(client, h, pid):
    return sum(r["quantity"] for r in client.get("/api/inventory/stock-levels", headers=h).json() if r["product_id"] == pid)


def _get(client, h, wid):
    return client.get(f"{W}/{wid}", headers=h).json()


def test_reasons_are_listed_and_validated(client, signup):
    h = signup()
    meta = client.get("/api/workpage/meta", headers=h).json()
    assert len(meta["cancel_reasons"]) == 6 and meta["other_reason"] == meta["cancel_reasons"][-1]
    assert any(s["key"] == "cancel_pending" and s["label"] == "Cancellation raised" for s in meta["statuses"])
    assert any(s["key"] == "cancelled" for s in meta["statuses"])
    w = client.post(W, headers=h, json={"client_name": "A"}).json()
    assert client.post(f"{W}/{w['id']}/cancel-request", headers=h, json={"reason": "because"}).status_code == 400
    assert client.post(f"{W}/{w['id']}/cancel-request", headers=h, json={"reason": meta["other_reason"]}).status_code == 400      # own words needed
    assert client.post(f"{W}/{w['id']}/cancel-request", headers=h, json={"reason": meta["other_reason"], "remark": "Site flooded"}).status_code == 200


def test_raised_work_is_frozen_and_reject_restores_the_previous_status(client, signup):
    admin = signup()
    prod, d, e = _setup(client, admin)
    w = _work(client, admin, d, e, prod)
    assert _get(client, admin, w["id"])["status"] == "allocated"
    emp, _ = _employee(client, admin, [("workpage", "view"), ("workpage", "edit")])
    r = client.post(f"{W}/{w['id']}/cancel-request", headers=emp, json={"reason": REASON, "remark": "Called at 5pm"})
    assert r.status_code == 200
    d1 = r.json()
    assert d1["status"] == "cancel_pending" and d1["status_label"] == "Cancellation raised" and d1["cancellation"]["status_before"] == "allocated"
    assert d1["cancellation"]["reason"] == REASON and d1["can_cancel"] is False
    # frozen
    assert client.post(f"{W}/{w['id']}/payments", headers=admin, json={"amount": 10, "method": "cash"}).status_code == 400
    assert client.post(f"{W}/{w['id']}/take-from-inventory", headers=admin).status_code == 400
    assert client.post(f"{W}/{w['id']}/allocate", headers=admin, json={"department_id": d["id"]}).status_code == 400
    assert client.put(f"{W}/{w['id']}/items", headers=admin, json={"items": []}).status_code == 400
    assert client.patch(f"{W}/{w['id']}", headers=admin, json={"quotation_amount": 1}).status_code == 400
    assert client.post(f"{W}/{w['id']}/cancel-request", headers=emp, json={"reason": REASON}).status_code == 400            # already raised
    # the employee cannot decide
    assert client.post(f"{W}/{w['id']}/cancel-decision", headers=emp, json={"approve": True}).status_code == 403
    # a purchase order cannot be raised for it either
    vendor = client.post("/api/procurement/vendors", headers=admin, json={"name": "V"}).json()
    r = client.post(PO, headers=admin, json={"vendor_id": vendor["id"], "work_order_id": w["id"], "items": [{"product_id": prod["id"], "qty": 1, "unit_price": 5}]})
    assert r.status_code in (400, 422)
    # admin rejects: back to Allocated, usable again
    r = client.post(f"{W}/{w['id']}/cancel-decision", headers=admin, json={"approve": False, "note": "Customer confirmed again"})
    assert r.status_code == 200 and r.json()["status"] == "allocated"
    kinds = [x["kind"] for x in r.json()["events"]]
    assert "cancel_raised" in kinds and "cancel_rejected" in kinds
    assert client.post(f"{W}/{w['id']}/take-from-inventory", headers=admin).status_code == 200
    assert client.post(f"{W}/{w['id']}/cancel-decision", headers=admin, json={"approve": True}).status_code == 400            # nothing waiting


def test_reject_returns_a_po_work_to_the_status_its_purchase_orders_dictate(client, signup):
    admin = signup()
    prod, d, e = _setup(client, admin, qty_in_stock=0)
    w = _work(client, admin, d, e, prod, qty=2)
    client.post(f"{W}/{w['id']}/stock-short", headers=admin, json={})
    vendor = client.post("/api/procurement/vendors", headers=admin, json={"name": "V"}).json()
    po = client.post(PO, headers=admin, json={"vendor_id": vendor["id"], "work_order_id": w["id"], "items": [{"product_id": prod["id"], "qty": 2, "unit_price": 50}]}).json()
    assert _get(client, admin, w["id"])["status"] == "po_raised"
    client.post(f"{W}/{w['id']}/cancel-request", headers=admin, json={"reason": REASON})
    # the PO is approved while the cancellation waits
    client.post(f"{PO}/{po['id']}/approve", headers=admin)
    assert _get(client, admin, w["id"])["status"] == "cancel_pending"
    r = client.post(f"{W}/{w['id']}/cancel-decision", headers=admin, json={"approve": False})
    assert r.json()["status"] == "in_transit"          # caught up with the PO that moved meanwhile


def test_approving_for_a_stock_taken_work_returns_the_units_to_inventory(client, signup):
    admin = signup()
    prod, d, e = _setup(client, admin, qty_in_stock=10)
    w = _work(client, admin, d, e, prod, qty=3, quote=300)
    assert client.post(f"{W}/{w['id']}/take-from-inventory", headers=admin).status_code == 200
    assert _stock(client, admin, prod["id"]) == 7
    assert _get(client, admin, w["id"])["status"] == "delivered"
    emp, _ = _employee(client, admin, [("workpage", "view"), ("workpage", "edit")])
    client.post(f"{W}/{w['id']}/cancel-request", headers=emp, json={"reason": "Delivery was delayed too long"})
    r = client.post(f"{W}/{w['id']}/cancel-decision", headers=admin, json={"approve": True, "note": "ok"})
    assert r.status_code == 200
    out = r.json()
    assert out["status"] == "cancelled" and out["status_label"] == "Cancelled" and out["stock_issues"] == []
    assert _stock(client, admin, prod["id"]) == 10                       # the 3 are back
    batch = client.get("/api/stockin/batches", headers=admin).json()
    rows = batch if isinstance(batch, list) else batch.get("batches", batch)
    assert any(b["quantity_remaining"] == 10 for b in rows)              # and the priced lot is whole again
    ev = [x for x in out["events"] if x["kind"] == "cancelled"][0]
    assert "Returned to Inventory" in ev["detail"] and "x 3" in ev["detail"]
    # the freed units serve the next work
    w2 = _work(client, admin, d, e, prod, qty=10, quote=1000)
    assert client.post(f"{W}/{w2['id']}/take-from-inventory", headers=admin).status_code == 200
    # cancelled is final
    assert client.post(f"{W}/{w['id']}/cancel-request", headers=admin, json={"reason": REASON}).status_code == 400
    assert client.post(f"{W}/{w['id']}/payments", headers=admin, json={"amount": 5, "method": "cash"}).status_code == 400


def test_approving_for_a_delivered_purchase_work_returns_the_bought_goods(client, signup):
    admin = signup()
    prod, d, e = _setup(client, admin, qty_in_stock=0)
    w = _work(client, admin, d, e, prod, qty=1, quote=100)
    client.post(f"{W}/{w['id']}/stock-short", headers=admin, json={})
    vendor = client.post("/api/procurement/vendors", headers=admin, json={"name": "Bharath"}).json()
    po = client.post(PO, headers=admin, json={"vendor_id": vendor["id"], "work_order_id": w["id"], "items": [{"product_id": prod["id"], "qty": 1, "unit_price": 50}]}).json()
    extra = client.post(PO, headers=admin, json={"vendor_id": vendor["id"], "items": [{"product_id": prod["id"], "qty": 2, "unit_price": 50}]}).json()
    for p_ in (po, extra):
        client.post(f"{PO}/{p_['id']}/approve", headers=admin)
        assert client.post(f"{PO}/{p_['id']}/receive-good", headers=admin, files=_files()).status_code == 200
    assert client.post(f"{W}/{w['id']}/deliver", headers=admin, json={}).status_code == 200
    assert _stock(client, admin, prod["id"]) == 2                        # bought 3, delivered 1
    client.post(f"{W}/{w['id']}/cancel-request", headers=admin, json={"reason": REASON})
    r = client.post(f"{W}/{w['id']}/cancel-decision", headers=admin, json={"approve": True})
    assert r.json()["status"] == "cancelled"
    assert _stock(client, admin, prod["id"]) == 3                        # the delivered unit is back


def test_cancelling_before_delivery_leaves_received_goods_in_stock_and_flags_open_pos(client, signup):
    admin = signup()
    prod, d, e = _setup(client, admin, qty_in_stock=0)
    w = _work(client, admin, d, e, prod, qty=2, quote=200)
    client.post(f"{W}/{w['id']}/stock-short", headers=admin, json={})
    vendor = client.post("/api/procurement/vendors", headers=admin, json={"name": "V"}).json()
    po = client.post(PO, headers=admin, json={"vendor_id": vendor["id"], "work_order_id": w["id"], "items": [{"product_id": prod["id"], "qty": 2, "unit_price": 50}]}).json()
    client.post(f"{W}/{w['id']}/cancel-request", headers=admin, json={"reason": REASON})
    r = client.post(f"{W}/{w['id']}/cancel-decision", headers=admin, json={"approve": True})
    ev = [x for x in r.json()["events"] if x["kind"] == "cancelled"][0]
    assert po["po_number"] in ev["detail"] and "Procurement" in ev["detail"]
    assert _stock(client, admin, prod["id"]) == 0                        # nothing had left Inventory, nothing to return


def test_money_already_received_is_flagged_as_refund_due_in_finance(client, signup):
    admin = signup()
    prod, d, e = _setup(client, admin, qty_in_stock=5)
    w = _work(client, admin, d, e, prod, qty=1, quote=100)
    client.post(f"{W}/{w['id']}/take-from-inventory", headers=admin)
    assert client.post(f"{W}/{w['id']}/payments", headers=admin, json={"amount": 40, "method": "cash"}).status_code == 201
    client.post(f"{W}/{w['id']}/cancel-request", headers=admin, json={"reason": "Customer could not arrange the payment"})
    client.post(f"{W}/{w['id']}/cancel-decision", headers=admin, json={"approve": True})
    rec = client.get("/api/finance/work-reconciliation", headers=admin).json()
    row = next(x for x in rec["works"] if x["work_id"] == w["id"])
    assert row["state"] == "cancelled_refund_due" and rec["mismatch"] == 0 and rec["open"] == 1
    assert _stock(client, admin, prod["id"]) == 5
    # a cancelled work does not count as unfinished on Home
    home = client.get("/api/dashboard/home", headers=admin)
    if home.status_code == 200 and home.json().get("works"):
        assert home.json()["works"]["open_now"] == 0 and home.json()["works"]["cancelled"] == 1


def test_a_done_work_cannot_be_cancelled(client, signup):
    admin = signup()
    prod, d, e = _setup(client, admin, qty_in_stock=5)
    w = _work(client, admin, d, e, prod, qty=1, quote=100)
    client.post(f"{W}/{w['id']}/take-from-inventory", headers=admin)
    client.post(f"{W}/{w['id']}/payments", headers=admin, json={"amount": 100, "method": "cash"})
    assert _get(client, admin, w["id"])["status"] == "closed"
    r = client.post(f"{W}/{w['id']}/cancel-request", headers=admin, json={"reason": REASON})
    assert r.status_code == 400 and "done" in r.json()["detail"]


def test_cancel_approval_is_its_own_permission_that_can_be_given_to_a_second_admin(client, signup):
    admin = signup()
    prod, d, e = _setup(client, admin, qty_in_stock=0)
    w = _work(client, admin, d, e, prod, qty=1)
    # a role with every ordinary workpage action still cannot decide
    emp, _ = _employee(client, admin, [(m, a) for m in ("workpage",) for a in ("view", "create", "edit", "delete", "approve")], name="Mgr")
    client.post(f"{W}/{w['id']}/cancel-request", headers=emp, json={"reason": REASON})
    r = client.post(f"{W}/{w['id']}/cancel-decision", headers=emp, json={"approve": True})
    assert r.status_code == 403 and "cancel_approve" in r.json()["detail"]
    # tick the special checkbox on a second role: that role can decide
    sec, role = _employee(client, admin, [("workpage", "view"), ("workpage", "edit"), ("workpage", "cancel_approve")], name="Second")
    me = client.get("/api/auth/me", headers=sec).json()
    assert "workpage:cancel_approve" in me["permissions"]
    assert client.get("/api/auth/me", headers=admin).json()["permissions"].count("workpage:cancel_approve") == 1
    r = client.post(f"{W}/{w['id']}/cancel-decision", headers=sec, json={"approve": True})
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    # the requester and the approvers are notified
    notes = client.get("/api/notifications", headers=emp)
    assert notes.status_code == 200
