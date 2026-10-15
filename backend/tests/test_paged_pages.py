"""Stock movements page (15 per page, who/which job/profit) and journal-entry paging."""
import uuid
from decimal import Decimal

from conftest import receive_po
from test_gst_credit import _product, _work, W
from test_rbac_permissions import create_restricted_user


def _received_for_job(client, h, prod, work_id, qty=5):
    vendor = client.post("/api/procurement/vendors", headers=h, json={"name": "SunVolt"}).json()
    body = {"vendor_id": vendor["id"], "items": [{"product_id": prod["id"], "qty": qty, "unit_price": 40000, "cgst_percent": 10, "sgst_percent": 10}]}
    if work_id:
        body["work_order_id"] = work_id
    po = client.post("/api/procurement/purchase-orders", headers=h, json=body)
    assert po.status_code == 201, po.text
    receive_po(client, h, po.json()["id"])


def test_movements_page_shows_client_employee_profit_and_po_job(client, signup):
    h = signup()
    prod = _product(client, h)
    stocked = _product(client, h)
    _received_for_job(client, h, stocked, None)                       # plain stock (no job)
    w = _work(client, h, stocked)
    assert client.post(f"{W}/{w['id']}/take-from-inventory", headers=h).status_code == 200
    w2 = _work(client, h, prod)
    _received_for_job(client, h, prod, w2["id"], qty=1)               # bought for a specific job
    w = {**w, "job": w2}
    r = client.get("/api/inventory/movements/page", headers=h)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["page_size"] == 15 and j["total"] >= 2
    by = {m["ref_type"]: {d["label"]: d["value"] for d in m["details"]} | {"_qty": m["qty"]} for m in j["items"]}
    out = by["work_order"]
    assert out["Client"] == "Acme" and "Anu" in out["Handled by"] and out["Profit on this deal"].startswith("₹") and out["Work"] == w["work_number"]
    pos = [{d["label"]: d["value"] for d in m["details"]} for m in j["items"] if m["ref_type"] == "purchase_order"]
    assert any(x["Against job"] == "Stock for future (no job)" for x in pos)
    po = next(x for x in pos if "Against job" in x and w2["work_number"] in x["Against job"])
    assert po["Ordered by"] != "-" and po["Vendor"] == "SunVolt"
    # filters
    only_out = client.get("/api/inventory/movements/page?direction=out", headers=h).json()
    assert only_out["items"] and all(m["ref_type"] == "work_order" for m in only_out["items"])
    only_in = client.get("/api/inventory/movements/page?direction=in", headers=h).json()
    assert all(m["ref_type"] == "purchase_order" for m in only_in["items"])
    assert client.get(f"/api/inventory/movements/page?product_id={prod['id']}", headers=h).json()["total"] == 1


def test_movements_pagination_hidden_profit_and_isolation(client, signup):
    h = signup()
    prod = _product(client, h)
    for _ in range(17):
        client.post("/api/stockin/batches", headers=h, json={"product_id": prod["id"], "quantity": 1, "vendor_name": "V", "vendor_amount": 100})
    p1 = client.get("/api/inventory/movements/page?page=1", headers=h).json()
    p2 = client.get("/api/inventory/movements/page?page=2", headers=h).json()
    assert p1["total"] == 17 and len(p1["items"]) == 15 and len(p2["items"]) == 2 and p1["total_pages"] == 2
    assert not ({m["id"] for m in p1["items"]} & {m["id"] for m in p2["items"]})
    assert client.get("/api/inventory/movements/page?page_size=500", headers=h).json()["page_size"] == 100
    # profit only for people who may view works
    w = _work(client, h, prod)
    client.post(f"{W}/{w['id']}/take-from-inventory", headers=h)
    viewer = create_restricted_user(client, h, "inventory", "view")
    jv = client.get("/api/inventory/movements/page", headers=viewer).json()
    labels = {d["label"] for m in jv["items"] for d in m["details"]}
    assert "Client" in labels and "Profit on this deal" not in labels
    # another tenant sees nothing
    assert client.get("/api/inventory/movements/page", headers=signup()).json()["total"] == 0


def test_journal_entries_page(client, signup):
    h = signup()
    prod = _product(client, h)
    w = _work(client, h, prod)
    _received_for_job(client, h, prod, w["id"], qty=1)
    client.post(f"{W}/{w['id']}/take-from-inventory", headers=h)
    client.post(f"{W}/{w['id']}/payments", headers=h, json={"amount": 1000, "method": "cash"})
    j = client.get("/api/finance/journal-entries/page?page_size=1", headers=h).json()
    assert j["page_size"] == 1 and j["total"] >= 1 and len(j["items"]) == 1 and j["items"][0]["lines"]
    first = j["items"][0]
    q = client.get("/api/finance/journal-entries/page", headers=h, params={"q": first["entry_number"] or first["description"][:6]}).json()
    assert q["total"] >= 1
    assert client.get("/api/finance/journal-entries/page", headers=h, params={"q": "zzz-nope-" + uuid.uuid4().hex}).json()["total"] == 0
    assert client.get("/api/finance/journal-entries/page", headers=signup()).json()["total"] == 0
