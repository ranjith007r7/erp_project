"""v3_22: notification temporary archive (7 days), partial bad-condition goods receipt, client GST following the product."""
import json
import uuid
from datetime import datetime, timedelta

from conftest import PDF_BYTES, PNG_BYTES

W = "/api/workpage/works"
PO = "/api/procurement/purchase-orders"
N = "/api/notifications"


def _files(defect=False):
    f = [("invoice", ("i.pdf", PDF_BYTES, "application/pdf")), ("pod", ("p.png", PNG_BYTES, "image/png"))]
    if defect:
        f.append(("defect", ("d.png", PNG_BYTES, "image/png")))
    return f


def _po(client, h, qty=15, work_id=None, prod=None):
    prod = prod or client.post("/api/sales/products", headers=h, json={"name": f"Pump {uuid.uuid4().hex[:4]}", "unit_price": 1000}).json()
    vendor = client.post("/api/procurement/vendors", headers=h, json={"name": "Bharath Mounts", "email": "v@x.com"}).json()
    body = {"vendor_id": vendor["id"], "items": [{"product_id": prod["id"], "qty": qty, "unit_price": 500}]}
    if work_id:
        body["work_order_id"] = work_id
    po = client.post(PO, headers=h, json=body).json()
    assert client.post(f"{PO}/{po['id']}/approve", headers=h).status_code == 200
    return po, prod


def _stock(client, h, pid):
    rows = client.get("/api/inventory/stock-levels", headers=h).json()
    return sum(r.get("quantity", 0) for r in rows if str(r.get("product_id")) == str(pid))


# ------------------------------------------------------------------ notifications
def test_read_notification_moves_to_archive_and_old_ones_are_purged(client, signup):
    h = signup()
    po, _ = _po(client, h, qty=2)               # approving notifies the creator/admin
    client.post(f"{PO}/{po['id']}/receive-good", headers=h, files=_files())
    new = client.get(N, headers=h).json()
    assert new and all(not n["is_read"] for n in new)
    first = new[0]["id"]
    assert client.patch(f"{N}/{first}/read", headers=h).status_code == 200
    assert first not in [n["id"] for n in client.get(N, headers=h).json()]
    arch = client.get(f"{N}/archive", headers=h).json()
    assert [n["id"] for n in arch] == [first] and arch[0]["read_at"]
    # read-all moves everything
    client.post(f"{N}/read-all", headers=h)
    assert client.get(N, headers=h).json() == []
    assert len(client.get(f"{N}/archive", headers=h).json()) == len(new)
    # a message read 8 days ago is deleted for good on the next fetch; one read 6 days ago stays
    from app.core import database as dbm
    from app.models.notification import Notification
    db = dbm.SessionLocal()
    try:
        mine = [n['id'] for n in client.get(f'{N}/archive', headers=h).json()]
        rows = db.query(Notification).filter(Notification.id.in_(mine)).order_by(Notification.created_at).all()
        rows[0].read_at = datetime.utcnow() - timedelta(days=8)
        if len(rows) > 1:
            rows[1].read_at = datetime.utcnow() - timedelta(days=6)
        gone = rows[0].id
        db.commit()
    finally:
        db.close()
    ids = [n["id"] for n in client.get(f"{N}/archive", headers=h).json()]
    assert str(gone) not in ids and len(ids) == len(new) - 1


# ------------------------------------------------------------------ partial receipt
def test_partial_bad_receipt_stocks_the_good_units_and_replacement_completes_it(client, signup):
    h = signup()
    po, prod = _po(client, h, qty=15)
    item = po["items"][0]
    r = client.post(f"{PO}/{po['id']}/receive-bad", headers=h, files=_files(True),
                    data={"notes": "1 cracked", "lines": json.dumps([{"item_id": item["id"], "defective_qty": 1}])})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "defective"
    assert d["items"][0]["received_qty"] == 14 and d["items"][0]["outstanding_qty"] == 1
    assert d["receipts"][0]["lines"] == [{"product_name": prod["name"], "qty_good": 14, "qty_defective": 1}]
    assert _stock(client, h, prod["id"]) == 14
    # the defect notice names the returned unit and says the good ones were accepted
    rid = d["receipts"][0]["id"]
    mail = client.get(f"/api/procurement/receipts/{rid}/defect-preview", headers=h).json()
    assert "1 defective (14 accepted)" in mail["body"] and "ONLY the defective units" in mail["body"]
    # replacement arrives: the normal good receipt takes ONLY the outstanding unit
    g = client.post(f"{PO}/{po['id']}/receive-good", headers=h, files=_files())
    assert g.status_code == 200, g.text
    gd = g.json()
    assert gd["status"] == "received" and gd["items"][0]["received_qty"] == 15 and gd["items"][0]["outstanding_qty"] == 0
    assert _stock(client, h, prod["id"]) == 15
    assert [l["qty_good"] for l in gd["receipts"][-1]["lines"]] == [1] or any(l["qty_good"] == 1 for rc in gd["receipts"] for l in rc["lines"])
    assert client.post(f"{PO}/{po['id']}/receive-good", headers=h, files=_files()).status_code == 400   # nothing left


def test_partial_receipt_validation_and_legacy_all_bad(client, signup):
    h = signup()
    po, prod = _po(client, h, qty=5)
    iid = po["items"][0]["id"]
    def bad(lines):
        return client.post(f"{PO}/{po['id']}/receive-bad", headers=h, files=_files(True), data={"lines": json.dumps(lines)})
    assert bad([{"item_id": iid, "defective_qty": 6}]).status_code == 400      # more than outstanding
    assert bad([{"item_id": iid, "defective_qty": -1}]).status_code == 400
    assert bad([{"item_id": iid, "defective_qty": 0}]).status_code == 400      # nothing defective: use the good flow
    assert bad([{"item_id": str(uuid.uuid4()), "defective_qty": 1}]).status_code == 400
    assert _stock(client, h, prod["id"]) == 0
    # no `lines` = old behaviour: the whole consignment is defective, nothing enters stock
    r = client.post(f"{PO}/{po['id']}/receive-bad", headers=h, files=_files(True))
    assert r.status_code == 200 and r.json()["items"][0]["outstanding_qty"] == 5 and _stock(client, h, prod["id"]) == 0
    # second shipment also partly bad: 3 good now, 2 still owed
    r2 = client.post(f"{PO}/{po['id']}/receive-bad", headers=h, files=_files(True), data={"lines": json.dumps([{"item_id": iid, "defective_qty": 2}])})
    assert r2.status_code == 200 and r2.json()["items"][0]["received_qty"] == 3 and _stock(client, h, prod["id"]) == 3


def test_partial_receipt_on_a_job_po_keeps_the_work_waiting_until_replacement(client, signup):
    h = signup()
    prod = client.post("/api/sales/products", headers=h, json={"name": "Valve", "unit_price": 1000}).json()
    d = client.post("/api/hr/departments", headers=h, json={"name": "Ops"}).json()
    e = client.post("/api/hr/employees", headers=h, json={"name": "Anu", "department_id": d["id"]}).json()
    w = client.post(W, headers=h, json={"client_name": "Acme", "quotation_amount": 30000}).json()
    client.post(f"{W}/{w['id']}/allocate", headers=h, json={"department_id": d["id"], "employee_id": e["id"]})
    client.put(f"{W}/{w['id']}/items", headers=h, json={"items": [{"product_id": prod["id"], "qty": 15}]})
    client.post(f"{W}/{w['id']}/stock-short", headers=h, json={})
    po, _ = _po(client, h, qty=15, work_id=w["id"], prod=prod)
    iid = po["items"][0]["id"]
    client.post(f"{PO}/{po['id']}/receive-bad", headers=h, files=_files(True), data={"lines": json.dumps([{"item_id": iid, "defective_qty": 1}])})
    wd = client.get(f"{W}/{w['id']}", headers=h).json()
    assert wd["status"] == "waiting_new_po"
    ev = [x for x in wd["events"] if x["kind"] == "po_defective"][-1]
    assert "14" in ev["detail"] and "same purchase order" in ev["detail"]
    client.post(f"{PO}/{po['id']}/receive-good", headers=h, files=_files())
    assert client.get(f"{W}/{w['id']}", headers=h).json()["status"] == "po_received"
    assert _stock(client, h, prod["id"]) == 15


# ------------------------------------------------------------------ client GST follows the product
def test_work_gst_follows_a_lot_that_arrives_or_is_corrected_later(client, signup):
    h = signup()
    prod = client.post("/api/sales/products", headers=h, json={"name": "Inverter", "unit_price": 50000}).json()   # product master has 0% GST
    d = client.post("/api/hr/departments", headers=h, json={"name": "Ops"}).json()
    e = client.post("/api/hr/employees", headers=h, json={"name": "Anu", "department_id": d["id"]}).json()
    w = client.post(W, headers=h, json={"client_name": "Ferrari", "quotation_amount": 70000}).json()
    client.post(f"{W}/{w['id']}/allocate", headers=h, json={"department_id": d["id"], "employee_id": e["id"]})
    client.put(f"{W}/{w['id']}/items", headers=h, json={"items": [{"product_id": prod["id"], "qty": 1}]})
    assert float(client.get(f"{W}/{w['id']}", headers=h).json()["cgst_percent"]) == 0
    lot = client.post("/api/stockin/batches", headers=h, json={"product_id": prod["id"], "quantity": 5, "vendor_name": "Sunvolt", "vendor_amount": 38000,
                                                                  "mrp": 60000, "max_discount_percent": 10, "cgst_percent": 9, "sgst_percent": 9})
    assert lot.status_code == 201, lot.text
    d1 = client.get(f"{W}/{w['id']}", headers=h).json()
    assert float(d1["cgst_percent"]) == 9 and float(d1["sgst_percent"]) == 9           # arrived: no manual typing
    r = client.patch(f"/api/stockin/batches/{lot.json()['id']}", headers=h, json={"cgst_percent": 10, "sgst_percent": 10})
    assert r.status_code == 200, r.text
    d2 = client.get(f"{W}/{w['id']}", headers=h).json()
    assert float(d2["cgst_percent"]) == 10 and float(d2["sgst_percent"]) == 10          # corrected lot: the work follows
