"""Correcting the prices of a received purchase order: audited, permissioned, and carried to lots and works."""
import uuid

from conftest import PDF_BYTES, PNG_BYTES, login_any

W = "/api/workpage/works"
PO = "/api/procurement/purchase-orders"


def _files():
    return {"invoice": ("inv.pdf", PDF_BYTES, "application/pdf"), "pod": ("pod.png", PNG_BYTES, "image/png")}


def _received_po_for_work(client, h, qty=3, price=4000, with_work=True):
    prod = client.post("/api/sales/products", headers=h, json={"name": f"Kit {uuid.uuid4().hex[:4]}", "unit_price": 6000}).json()
    d = client.post("/api/hr/departments", headers=h, json={"name": "Ops"}).json()
    e = client.post("/api/hr/employees", headers=h, json={"name": "Anu", "department_id": d["id"]}).json()
    vendor = client.post("/api/procurement/vendors", headers=h, json={"name": "Bharath"}).json()
    w = None
    if with_work:
        w = client.post(W, headers=h, json={"client_name": "Acme", "quotation_amount": 12000}).json()
        client.post(f"{W}/{w['id']}/allocate", headers=h, json={"department_id": d["id"], "employee_id": e["id"]})
        client.put(f"{W}/{w['id']}/items", headers=h, json={"items": [{"product_id": prod["id"], "qty": qty}]})
        client.post(f"{W}/{w['id']}/stock-short", headers=h, json={})
    body = {"vendor_id": vendor["id"], "items": [{"product_id": prod["id"], "qty": qty, "unit_price": price}]}
    if w:
        body["work_order_id"] = w["id"]
    po = client.post(PO, headers=h, json=body).json()
    client.post(f"{PO}/{po['id']}/approve", headers=h)
    assert client.post(f"{PO}/{po['id']}/receive-good", headers=h, files=_files()).status_code == 200
    return po, prod, w


def _fix(client, h, po, price, reason="keyed 4000, vendor invoice says 2500"):
    po = client.get(PO, headers=h).json()[0] if False else [p for p in client.get(PO, headers=h).json() if p["id"] == po["id"]][0]
    return client.post(f"{PO}/{po['id']}/correct-prices", headers=h, json={"reason": reason, "items": [{"item_id": po["items"][0]["id"], "unit_price": price}]})


def _lots(client, h, pid):
    return [b for b in client.get("/api/stockin/batches", headers=h).json() if b["product_id"] == pid]


def test_correction_reaches_po_lot_and_work_and_keeps_the_original(client, signup):
    h = signup()
    po, prod, w = _received_po_for_work(client, h)
    assert float(client.get(f"{W}/{w['id']}", headers=h).json()["vendor_amount"]) == 12000
    r = _fix(client, h, po, 2500)
    assert r.status_code == 200, r.text
    out = r.json()
    assert float(out["total"]) == 7500 and float(out["items"][0]["unit_price"]) == 2500
    c = out["corrections"][0]
    assert (float(c["old_price"]), float(c["new_price"])) == (4000, 2500) and "vendor invoice" in c["reason"] and c["corrected_by_name"]
    assert float(_lots(client, h, prod["id"])[0]["vendor_amount"]) == 2500
    assert "PO price corrected" in _lots(client, h, prod["id"])[0]["note"]
    d = client.get(f"{W}/{w['id']}", headers=h).json()
    assert float(d["vendor_amount"]) == 7500
    assert any(e["kind"] == "po_price_corrected" and "4000" in e["detail"] and "2500" in e["detail"] for e in d["events"])


def test_correction_after_delivery_fixes_issue_cost_and_profit(client, signup):
    h = signup()
    po, prod, w = _received_po_for_work(client, h)
    assert client.post(f"{W}/{w['id']}/deliver", headers=h, json={}).status_code == 200
    d = client.get(f"{W}/{w['id']}", headers=h).json()
    assert float(d["vendor_amount"]) == 12000 and float(d["purchased_items"][0]["cost_rate"]) == 4000
    assert _fix(client, h, po, 2500).status_code == 200
    d = client.get(f"{W}/{w['id']}", headers=h).json()
    assert float(d["vendor_amount"]) == 7500 and float(d["purchased_items"][0]["cost_rate"]) == 2500
    assert float(d["profit"]) == 12000 - 7500


def test_correction_rules(client, signup):
    h = signup()
    po, prod, w = _received_po_for_work(client, h)
    item = po["items"][0]["id"]
    url = f"{PO}/{po['id']}/correct-prices"
    assert client.post(url, headers=h, json={"reason": "", "items": [{"item_id": item, "unit_price": 1}]}).status_code == 422       # reason mandatory
    assert client.post(url, headers=h, json={"reason": "same", "items": [{"item_id": item, "unit_price": 4000}]}).status_code == 400   # nothing changed
    assert client.post(url, headers=h, json={"reason": "bad", "items": [{"item_id": str(uuid.uuid4()), "unit_price": 1}]}).status_code == 400
    # a PO that has not been received cannot be corrected
    vendor = client.post("/api/procurement/vendors", headers=h, json={"name": "V2"}).json()
    p2 = client.post(PO, headers=h, json={"vendor_id": vendor["id"], "items": [{"product_id": prod["id"], "qty": 1, "unit_price": 10}]}).json()
    r = client.post(f"{PO}/{p2['id']}/correct-prices", headers=h, json={"reason": "typo", "items": [{"item_id": p2["items"][0]["id"], "unit_price": 5}]})
    assert r.status_code == 400 and "received" in r.json()["detail"]


def test_stock_for_future_po_can_be_corrected_too(client, signup):
    h = signup()
    po, prod, _ = _received_po_for_work(client, h, with_work=False)
    assert _fix(client, h, po, 2500).status_code == 200
    assert float(_lots(client, h, prod["id"])[0]["vendor_amount"]) == 2500


def test_correct_price_is_its_own_permission(client, signup):
    admin = signup()
    po, prod, w = _received_po_for_work(client, admin)
    u = uuid.uuid4().hex[:8]

    def login_with(perms):
        role = client.post("/api/core/roles", headers=admin, json={"name": f"Buyer {uuid.uuid4().hex[:5]}"}).json()
        for m, a in perms:
            assert client.post(f"/api/core/roles/{role['id']}/permissions", headers=admin, json={"module": m, "action": a}).status_code == 201
        email = f"b-{uuid.uuid4().hex[:8]}@test.com"
        client.post("/api/core/users", headers=admin, json={"name": "Buyer", "email": email, "password": "pass12345", "role_id": role["id"]})
        return {"Authorization": f"Bearer {login_any(client, email, 'pass12345').json()['access_token']}"}

    plain = login_with([("procurement", a) for a in ("view", "create", "edit", "delete", "approve")])
    body = {"reason": "keyed wrong", "items": [{"item_id": po["items"][0]["id"], "unit_price": 2500}]}
    assert client.post(f"{PO}/{po['id']}/correct-prices", headers=plain, json=body).status_code == 403      # all procurement actions, still no
    ticked = login_with([("procurement", "view"), ("procurement", "correct_price")])
    assert client.post(f"{PO}/{po['id']}/correct-prices", headers=ticked, json=body).status_code == 200
    me = client.get("/api/auth/me", headers=admin).json()
    assert "procurement:correct_price" in me["permissions"]


def test_waiting_work_vendor_amount_follows_a_corrected_older_lot(client, signup):
    """Hold 5 older units bought at 4000, work needs 8, PO for 3 at 2500: 5x4000 + 3x2500 = 27500. The older PO's price
    is then corrected to 2500: the waiting work must show 8 x 2500 = 20000 without anyone editing it."""
    h = signup()
    old_po, prod, _ = _received_po_for_work(client, h, qty=5, price=4000, with_work=False)
    d = client.post("/api/hr/departments", headers=h, json={"name": "Ops2"}).json()
    e = client.post("/api/hr/employees", headers=h, json={"name": "Raj", "department_id": d["id"]}).json()
    w = client.post(W, headers=h, json={"client_name": "Lakeview", "quotation_amount": 32000}).json()
    client.post(f"{W}/{w['id']}/allocate", headers=h, json={"department_id": d["id"], "employee_id": e["id"]})
    client.put(f"{W}/{w['id']}/items", headers=h, json={"items": [{"product_id": prod["id"], "qty": 8}]})
    assert client.post(f"{W}/{w['id']}/stock-short", headers=h, json={}).status_code == 200
    vendor = client.post("/api/procurement/vendors", headers=h, json={"name": "V"}).json()
    po = client.post(PO, headers=h, json={"vendor_id": vendor["id"], "work_order_id": w["id"],
                                          "items": [{"product_id": prod["id"], "qty": 3, "unit_price": 2500}]}).json()
    client.post(f"{PO}/{po['id']}/approve", headers=h)
    assert client.post(f"{PO}/{po['id']}/receive-good", headers=h, files=_files()).status_code == 200
    assert float(client.get(f"{W}/{w['id']}", headers=h).json()["vendor_amount"]) == 27500
    assert _fix(client, h, old_po, 2500).status_code == 200
    assert float(client.get(f"{W}/{w['id']}", headers=h).json()["vendor_amount"]) == 20000
    # delivery keeps it: 8 units x 2500
    assert client.post(f"{W}/{w['id']}/deliver", headers=h, json={}).status_code == 200
    assert float(client.get(f"{W}/{w['id']}", headers=h).json()["vendor_amount"]) == 20000
