"""v3_23: Warranty registration (auto-created at delivery, filled, approved, card PDF) and Claims (6 mandatory documents,
admin-only decision, zero-value replacement work, vendor notice)."""
import subprocess
import tempfile
import uuid
from datetime import date, timedelta

from conftest import PDF_BYTES, PNG_BYTES, login_any

W = "/api/workpage/works"
WR = "/api/warranty"
CL = "/api/claims"


def _text(pdf: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(pdf); f.flush()
        return subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True).stdout


def _user(client, admin, perms):
    u = uuid.uuid4().hex[:8]
    role = client.post("/api/core/roles", headers=admin, json={"name": f"R {u}"}).json()
    for m, a in perms:
        assert client.post(f"/api/core/roles/{role['id']}/permissions", headers=admin, json={"module": m, "action": a}).status_code == 201
    email = f"u-{u}@test.com"
    client.post("/api/core/users", headers=admin, json={"name": "Staff", "email": email, "password": "pass12345", "role_id": role["id"]})
    return {"Authorization": f"Bearer {login_any(client, email, 'pass12345').json()['access_token']}"}


def _delivered(client, h, qty=2, product_months=60):
    prod = client.post("/api/sales/products", headers=h, json={
        "name": f"Inverter {uuid.uuid4().hex[:4]}", "unit_price": 50000, "sku": "INV-5K", "cgst_percent": 9, "sgst_percent": 9,
        "mrp": 70800, "warranty_months": product_months, "warranty_terms": "Manufacturing defects only; excludes surge."}).json()
    assert prod["warranty_months"] == product_months
    vendor = client.post("/api/procurement/vendors", headers=h, json={"name": "Sunvolt Distributors", "email": "v@sunvolt.test"}).json()
    lot = client.post("/api/stockin/batches", headers=h, json={
        "product_id": prod["id"], "quantity": qty + 1, "vendor_name": "Sunvolt Distributors", "vendor_amount": 38000, "mrp": 70800,
        "max_discount_percent": 10, "manufacture_month": "2026-08", "expiry_date": "2031-08-31", "vendor_warranty_months": 24})
    assert lot.status_code == 201, lot.text
    d = client.post("/api/hr/departments", headers=h, json={"name": f"Ops{uuid.uuid4().hex[:3]}"}).json()
    e = client.post("/api/hr/employees", headers=h, json={"name": "Anu", "department_id": d["id"]}).json()
    w = client.post(W, headers=h, json={"client_name": "Ferrari", "quotation_amount": 60000 * qty}).json()
    client.post(f"{W}/{w['id']}/allocate", headers=h, json={"department_id": d["id"], "employee_id": e["id"]})
    assert client.put(f"{W}/{w['id']}/items", headers=h, json={"items": [{"product_id": prod["id"], "qty": qty}]}).status_code == 200
    r = client.post(f"{W}/{w['id']}/take-from-inventory", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "delivered"
    return prod, w


def _fill(client, h, rec, serial_prefix="SN-"):
    units = [{"id": u["id"], "serial_number": f"{serial_prefix}{uuid.uuid4().hex[:6]}"} for u in rec["units"]]
    r = client.patch(f"{WR}/{rec['id']}", headers=h, json={"warranty_months": 60, "units": units})
    assert r.status_code == 200, r.text
    return r.json()


def test_delivery_creates_warranty_with_prefilled_units(client, signup):
    h = signup()
    prod, w = _delivered(client, h, qty=2)
    rows = client.get(f"{WR}?work_id={w['id']}", headers=h).json()
    assert len(rows) == 1 and rows[0]["status"] == "pending_details" and rows[0]["qty"] == 2
    rec = client.get(f"{WR}/{rows[0]['id']}", headers=h).json()
    assert rec["work_number"] == w["work_number"] and rec["client_name"] == "Ferrari"
    assert rec["start_date"] == date.today().isoformat() and rec["end_date"] is None
    assert float(rec["amount"]) == 120000.0                        # whole taxable value (single product line)
    assert rec["warranty_months"] == 60 and "surge" in rec["warranty_terms"]   # product default, still changeable
    assert [u["model_number"] for u in rec["units"]] == ["INV-5K", "INV-5K"]
    assert all(u["manufacture_month"] == "2026-08-01" and u["expiry_date"] == "2031-08-31" and u["prefilled_from_stock"] for u in rec["units"])
    assert [p["months"] for p in rec["periods"]] == [1, 3, 6, 12, 24, 36, 60, 120]
    # delivering again (idempotent hook) never duplicates
    assert len(client.get(f"{WR}?work_id={w['id']}", headers=h).json()) == 1


def test_fill_submit_approve_and_card(client, signup):
    h = signup()
    prod, w = _delivered(client, h, qty=2)
    rec = client.get(f"{WR}?work_id={w['id']}", headers=h).json()[0]
    rid = rec["id"]
    full = client.get(f"{WR}/{rid}", headers=h).json()
    # cannot submit with serial numbers missing
    r = client.post(f"{WR}/{rid}/submit", headers=h)
    assert r.status_code == 400 and "serial number" in r.json()["detail"]
    # period must come from the dropdown values; start date is not editable (ignored field)
    assert client.patch(f"{WR}/{rid}", headers=h, json={"warranty_months": 7}).status_code == 400
    ok = client.patch(f"{WR}/{rid}", headers=h, json={"warranty_months": 60, "start_date": "2020-01-01",
                      "units": [{"id": full["units"][0]["id"], "serial_number": "SN-A1"}, {"id": full["units"][1]["id"], "serial_number": "SN-A1"}]})
    assert ok.status_code == 400 and "same serial" in ok.json()["detail"]
    ok = _fill(client, h, full)
    assert ok["start_date"] == date.today().isoformat()
    # a user who can fill but not approve
    staff = _user(client, h, [("warranty", "view"), ("warranty", "edit")])
    assert client.post(f"{WR}/{rid}/approve", headers=staff).status_code == 403
    assert client.post(f"{WR}/{rid}/submit", headers=staff).status_code == 200
    assert client.get(f"{WR}/{rid}/card-pdf", headers=h).status_code == 409           # no card until approved
    assert client.patch(f"{WR}/{rid}", headers=h, json={"warranty_terms": "x"}).status_code == 400   # locked while waiting
    # sent back with a reason, then fixed and resubmitted
    assert client.post(f"{WR}/{rid}/reject", headers=h, json={"reason": "Serial of unit 2 looks wrong"}).status_code == 200
    back = client.get(f"{WR}/{rid}", headers=h).json()
    assert back["status"] == "pending_details" and "Serial" in back["rejection_reason"]
    assert client.post(f"{WR}/{rid}/submit", headers=h).status_code == 200
    ap = client.post(f"{WR}/{rid}/approve", headers=h)
    assert ap.status_code == 200, ap.text
    d = ap.json()
    start = date.today()
    expect_end = date(start.year + 5, start.month, min(start.day, 28)) if start.day > 28 else date(start.year + 5, start.month, start.day)
    assert d["status"] == "active" and d["card_number"] == "WC-0001"
    assert d["end_date"] == (expect_end - timedelta(days=1)).isoformat()
    pdf = client.get(f"{WR}/{rid}/card-pdf", headers=h)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    t = _text(pdf.content)
    assert "WARRANTY CARD" in t and "WC-0001" in t and "Ferrari" in t and "INV-5K" in t and "5 years" in t
    assert all(u["serial_number"] in t for u in d["units"]) and "excludes surge" in t
    assert client.post(f"{WR}/{rid}/approve", headers=h).status_code == 400            # already active


def test_no_warranty_and_cancelled_work(client, signup):
    h = signup()
    prod, w = _delivered(client, h, qty=1, product_months=12)
    rid = client.get(f"{WR}?work_id={w['id']}", headers=h).json()[0]["id"]
    assert client.post(f"{WR}/{rid}/no-warranty", headers=h, json={"reason": "x"}).status_code == 422
    r = client.post(f"{WR}/{rid}/no-warranty", headers=h, json={"reason": "Consumable item, sold as is"})
    assert r.status_code == 200 and r.json()["status"] == "no_warranty" and r.json()["state"] == "No warranty"
    assert client.post(f"{WR}/{rid}/submit", headers=h).status_code == 400
    # a delivered work that is cancelled takes its warranties with it
    prod2, w2 = _delivered(client, h, qty=1)
    rid2 = client.get(f"{WR}?work_id={w2['id']}", headers=h).json()[0]["id"]
    assert client.post(f"{W}/{w2['id']}/cancel-request", headers=h, json={"reason": "Customer cancelled the order"}).status_code == 200
    assert client.post(f"{W}/{w2['id']}/cancel-decision", headers=h, json={"approve": True}).status_code == 200
    assert client.get(f"{WR}/{rid2}", headers=h).json()["status"] == "cancelled"


def _active(client, h, qty=2):
    prod, w = _delivered(client, h, qty=qty)
    rec = client.get(f"{WR}?work_id={w['id']}", headers=h).json()[0]
    full = _fill(client, h, client.get(f"{WR}/{rec['id']}", headers=h).json())
    client.post(f"{WR}/{rec['id']}/submit", headers=h)
    d = client.post(f"{WR}/{rec['id']}/approve", headers=h).json()
    return prod, w, d


def _upload_all(client, h, cid, skip=()):
    for kind in ("customer_invoice", "warranty_copy", "model_photo", "serial_photo", "defect_image", "supporting"):
        if kind in skip:
            continue
        if kind in ("customer_invoice", "warranty_copy", "supporting"):
            f = (f"{kind}.pdf", PDF_BYTES, "application/pdf")
        else:
            f = (f"{kind}.png", PNG_BYTES, "image/png")
        r = client.post(f"{CL}/{cid}/files", headers=h, data={"kind": kind}, files=[("files", f)])
        assert r.status_code == 200, r.text


def test_claim_needs_all_six_documents_and_admin_decides_replacement(client, signup):
    h = signup()
    prod, w, wd = _active(client, h)
    unit = wd["units"][0]
    # no claim against a warranty that is not active
    c = client.post(CL, headers=h, json={"warranty_id": wd["id"], "unit_id": unit["id"], "issue": "Inverter shows E04 and shuts down"})
    assert c.status_code == 201, c.text
    c = c.json()
    assert c["status"] == "open" and c["claim_number"] == "CL-0001" and c["out_of_warranty"] is False
    assert [r["kind"] for r in c["required"]] == ["customer_invoice", "warranty_copy", "model_photo", "serial_photo", "defect_image", "supporting"]
    assert client.post(CL, headers=h, json={"warranty_id": wd["id"], "unit_id": unit["id"], "issue": "again"}).status_code == 400   # one at a time
    # photos must be images, documents may be PDFs
    bad = client.post(f"{CL}/{c['id']}/files", headers=h, data={"kind": "serial_photo"}, files=[("files", ("s.pdf", PDF_BYTES, "application/pdf"))])
    assert bad.status_code == 400
    _upload_all(client, h, c["id"], skip=("supporting",))
    r = client.post(f"{CL}/{c['id']}/submit", headers=h)
    assert r.status_code == 400 and "Additional supporting documents" in r.json()["detail"]
    _upload_all(client, h, c["id"], skip=("customer_invoice", "warranty_copy", "model_photo", "serial_photo", "defect_image"))
    assert client.post(f"{CL}/{c['id']}/submit", headers=h).status_code == 200
    # employees cannot decide
    staff = _user(client, h, [("claims", "view"), ("claims", "edit"), ("claims", "create")])
    assert client.post(f"{CL}/{c['id']}/approve", headers=staff, json={"resolution": "replace"}).status_code == 403
    assert client.post(f"{CL}/{c['id']}/reject", headers=staff, json={"note": "no"}).status_code == 403
    # vendor notice is only for an approved claim
    assert client.get(f"{CL}/{c['id']}/vendor-notice/preview", headers=h).status_code == 409
    ap = client.post(f"{CL}/{c['id']}/approve", headers=h, json={"resolution": "replace", "note": "Faulty board"})
    assert ap.status_code == 200, ap.text
    d = ap.json()
    assert d["status"] == "replaced" and d["replacement_work"]["work_number"]
    rw = client.get(f"{W}/{d['replacement_work']['id']}", headers=h).json()
    assert float(rw["quotation_amount"]) == 0 and rw["client_name"] == "Ferrari" and rw["items"][0]["qty"] == 1
    assert "CL-0001" in (rw["description"] or "")
    # the unit can be claimed again only after the claim is closed out (it is now)
    # vendor side: traced to the lot (vendor, its 24-month warranty), customer documents are never attached
    pv = client.get(f"{CL}/{c['id']}/vendor-notice/preview", headers=h).json()
    assert pv["to_name"] == "Sunvolt Distributors" and pv["to_email"] == "v@sunvolt.test"
    assert unit["serial_number"] in pv["body"] and "within your warranty to us" in pv["body"]
    assert "Ferrari" not in pv["body"] and not any(a.startswith(("customer_invoice", "warranty_copy")) for a in pv["attachments"]) and any(a.startswith("serial_photo") for a in pv["attachments"])
    sent = client.post(f"{CL}/{c['id']}/vendor-notice/send", headers=h, json={"to_email": "v@sunvolt.test", "note": "Please prioritise"})
    assert sent.status_code == 200 and sent.json()["status"] in ("sent", "logged")
    pr = client.post(f"{CL}/{c['id']}/vendor-notice/print", headers=h)
    assert pr.status_code == 200 and pr.content[:4] == b"%PDF" and unit["serial_number"] in _text(pr.content)
    after = client.get(f"{CL}/{c['id']}", headers=h).json()
    assert after["vendor"]["notice_at"] and after["vendor"]["in_vendor_warranty"] is True


def test_rejection_needs_a_reason_and_out_of_warranty_is_flagged(client, signup):
    h = signup()
    prod, w, wd = _active(client, h, qty=2)
    # push the warranty into the past directly in the database
    from app.core import database as dbm
    from app.models.warranty import WarrantyRecord
    db = dbm.SessionLocal()
    try:
        r = db.get(WarrantyRecord, wd["id"])
        r.end_date = date.today() - timedelta(days=3)
        db.commit()
    finally:
        db.close()
    unit = wd["units"][1]
    c = client.post(CL, headers=h, json={"warranty_id": wd["id"], "unit_id": unit["id"], "issue": "Dead on arrival of power"}).json()
    assert c["out_of_warranty"] is True
    _upload_all(client, h, c["id"])
    assert client.post(f"{CL}/{c['id']}/submit", headers=h).status_code == 200
    # out of warranty: approving needs an explicit reason
    assert client.post(f"{CL}/{c['id']}/approve", headers=h, json={"resolution": "repair"}).status_code == 400
    assert client.post(f"{CL}/{c['id']}/reject", headers=h, json={"note": ""}).status_code == 422
    rj = client.post(f"{CL}/{c['id']}/reject", headers=h, json={"note": "Warranty expired 3 days ago"})
    assert rj.status_code == 200 and rj.json()["status"] == "rejected"
    assert client.get(f"{CL}/{c['id']}/vendor-notice/preview", headers=h).status_code == 409
    lst = client.get(CL, headers=h).json()
    assert lst[0]["status"] == "rejected" and lst[0]["out_of_warranty"] is True


def test_other_orgs_cannot_see_warranty_or_claims(client, signup):
    a, b = signup(), signup()
    prod, w, wd = _active(client, a)
    assert client.get(f"{WR}/{wd['id']}", headers=b).status_code == 404
    assert client.get(WR, headers=b).json() == []
    c = client.post(CL, headers=a, json={"warranty_id": wd["id"], "unit_id": wd["units"][0]["id"], "issue": "broken"}).json()
    assert client.get(f"{CL}/{c['id']}", headers=b).status_code == 404
    assert client.post(CL, headers=b, json={"warranty_id": wd["id"], "unit_id": wd["units"][0]["id"], "issue": "broken"}).status_code == 404
