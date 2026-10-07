"""
Procurement workflow: approval -> email/PDF to vendor -> receiving with proof
(good / defective) -> defect notice by email or print. Real DB, real requests.
"""
import logging
from conftest import login_any
import uuid

import pytest

from conftest import PNG_BYTES, PDF_BYTES

PO = "/api/procurement/purchase-orders"


def make_user(client, admin, perms, name="Buyer Bob"):
    unique = uuid.uuid4().hex[:8]
    role = client.post("/api/core/roles", headers=admin, json={"name": f"Role {unique}"}).json()
    for module, action in perms:
        client.post(f"/api/core/roles/{role['id']}/permissions", headers=admin, json={"module": module, "action": action})
    email = f"u-{unique}@test.com"
    client.post("/api/core/users", headers=admin, json={"name": name, "email": email, "password": "pass12345", "role_id": role["id"]})
    tok = login_any(client, email, "pass12345").json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def setup(client, admin, vendor_email=None, creator=None, qty=10):
    product = client.post("/api/sales/products", headers=admin, json={"name": "Steel Rod", "unit_price": 100, "sku": "SR1"}).json()
    vendor = client.post("/api/procurement/vendors", headers=admin, json={"name": "Bharath Steels", "email": vendor_email}).json()
    po = client.post(PO, headers=creator or admin, json={
        "vendor_id": vendor["id"], "items": [{"product_id": product["id"], "qty": qty, "unit_price": 60}],
    })
    assert po.status_code == 201, po.text
    return product, vendor, po.json()


def stock_of(client, admin, product_id):
    rows = client.get("/api/inventory/stock-levels", headers=admin).json()
    return sum(r["quantity"] for r in rows if str(r.get("product_id")) == product_id)


@pytest.fixture(autouse=True)
def _enable_email_logger():
    # Alembic's fileConfig() (run by the migration fixture) disables pre-existing loggers.
    logging.getLogger("erp.email").disabled = False


def good_files():
    return {"invoice": ("inv.pdf", PDF_BYTES, "application/pdf"), "pod": ("pod.png", PNG_BYTES, "image/png")}


def test_po_starts_pending_with_number_and_creator(client, signup):
    admin = signup()
    _, vendor, po = setup(client, admin)
    assert po["po_number"] == "PO-0001"
    assert po["approval_status"] == "pending" and po["status"] == "pending"
    assert po["created_by_name"] == "Test Admin" and po["vendor_name"] == "Bharath Steels"
    assert po["items"][0]["product_name"] == "Steel Rod" and float(po["items"][0]["line_total"]) == 600
    po2 = setup(client, admin)[2]
    assert po2["po_number"] == "PO-0002"


def test_unapproved_po_cannot_be_emailed_exported_or_received(client, signup):
    admin = signup()
    _, _, po = setup(client, admin)
    assert client.get(f"{PO}/{po['id']}/email-preview", headers=admin).status_code == 400
    assert client.post(f"{PO}/{po['id']}/send-email", headers=admin, json={"to_email": "a@b.com"}).status_code == 400
    assert client.get(f"{PO}/{po['id']}/pdf", headers=admin).status_code == 400
    r = client.post(f"{PO}/{po['id']}/receive-good", headers=admin, files=good_files())
    assert r.status_code == 400 and "approved" in r.json()["detail"]


def test_approval_roles_and_audit(client, signup):
    admin = signup()
    buyer = make_user(client, admin, [("procurement", "view"), ("procurement", "create"), ("procurement", "edit"), ("sales", "view")])
    _, _, po = setup(client, admin, creator=buyer)
    assert po["created_by_name"] == "Buyer Bob"
    r = client.post(f"{PO}/{po['id']}/approve", headers=buyer)
    assert r.status_code == 403 and "approve" in r.json()["detail"]
    r = client.post(f"{PO}/{po['id']}/approve", headers=admin)
    assert r.status_code == 200 and r.json()["approval_status"] == "approved"
    assert r.json()["approved_by_name"] == "Test Admin"
    assert client.post(f"{PO}/{po['id']}/approve", headers=admin).status_code == 400
    assert client.post(f"{PO}/{po['id']}/reject", headers=admin).status_code == 400
    log = client.get("/api/core/audit-log", headers=admin).json()
    assert {"create_purchase_order", "approve_purchase_order"} <= {e["action"] for e in log}
    # buyer is notified of the approval
    notes = client.get("/api/notifications", headers=buyer).json()
    assert any("approved" in n["message"] for n in notes)


def test_reject_cancels(client, signup):
    admin = signup()
    _, _, po = setup(client, admin)
    r = client.post(f"{PO}/{po['id']}/reject", headers=admin).json()
    assert r["approval_status"] == "rejected" and r["status"] == "cancelled"
    assert client.post(f"{PO}/{po['id']}/receive-good", headers=admin, files=good_files()).status_code == 400


def test_filter_by_vendor_and_approval(client, signup):
    admin = signup()
    product, v1, po1 = setup(client, admin)
    v2 = client.post("/api/procurement/vendors", headers=admin, json={"name": "Other Co"}).json()
    po2 = client.post(PO, headers=admin, json={"vendor_id": v2["id"], "items": [{"product_id": product["id"], "qty": 1, "unit_price": 5}]}).json()
    client.post(f"{PO}/{po1['id']}/approve", headers=admin)
    only_v1 = client.get(PO, headers=admin, params={"vendor_id": v1["id"]}).json()
    assert [p["id"] for p in only_v1] == [po1["id"]]
    assert [p["id"] for p in client.get(PO, headers=admin, params={"approval": "pending"}).json()] == [po2["id"]]
    assert [p["id"] for p in client.get(PO, headers=admin, params={"approval": "approved"}).json()] == [po1["id"]]
    assert client.get(PO, headers=admin, params={"approval": "bogus"}).status_code == 422


def test_email_preview_and_send_falls_back_to_logged(client, signup, caplog):
    admin = signup()
    _, vendor, po = setup(client, admin, vendor_email="sales@bharath.com")
    client.post(f"{PO}/{po['id']}/approve", headers=admin)
    pv = client.get(f"{PO}/{po['id']}/email-preview", headers=admin).json()
    assert pv["to_email"] == "sales@bharath.com" and pv["to_name"] == "Bharath Steels"
    assert pv["from_name"].startswith("Test Org")
    for needle in ("Steel Rod", "qty 10", "Rs. 600.00", "Raised by: Test Admin", "Approved by: Test Admin", "PO-0001"):
        assert needle in pv["body"], needle
    assert pv["subject"].startswith("Purchase Order PO-0001")

    assert client.post(f"{PO}/{po['id']}/send-email", headers=admin, json={"to_email": "not-an-email"}).status_code == 400
    with caplog.at_level(logging.WARNING, logger="erp.email"):
        r = client.post(f"{PO}/{po['id']}/send-email", headers=admin, json={"to_email": "typed@vendor.com", "note": "Urgent please"})
    assert r.status_code == 200 and r.json()["status"] == "logged"   # no RESEND key in tests
    assert "typed@vendor.com" in caplog.text and "Urgent please" in caplog.text and "PO-0001.pdf" in caplog.text
    log = client.get("/api/core/audit-log", headers=admin).json()
    assert any(e["action"] == "send_purchase_order_email" for e in log)


def test_email_send_requires_edit_permission(client, signup):
    admin = signup()
    viewer = make_user(client, admin, [("procurement", "view")])
    _, _, po = setup(client, admin)
    client.post(f"{PO}/{po['id']}/approve", headers=admin)
    assert client.get(f"{PO}/{po['id']}/email-preview", headers=viewer).status_code == 200
    assert client.post(f"{PO}/{po['id']}/send-email", headers=viewer, json={"to_email": "a@b.com"}).status_code == 403


def test_vendor_pdf_scopes(client, signup):
    admin = signup()
    product, vendor, po1 = setup(client, admin)
    po2 = client.post(PO, headers=admin, json={"vendor_id": vendor["id"], "items": [{"product_id": product["id"], "qty": 2, "unit_price": 7}]}).json()
    client.post(f"{PO}/{po1['id']}/approve", headers=admin)
    base = f"/api/procurement/vendors/{vendor['id']}/purchase-orders/pdf"
    for scope in ("pending", "approved", "all"):
        r = client.get(base, headers=admin, params={"scope": scope})
        assert r.status_code == 200 and r.content.startswith(b"%PDF"), scope
        assert r.headers["content-type"] == "application/pdf"
        assert "attachment" in r.headers["content-disposition"]
    all_len = len(client.get(base, headers=admin, params={"scope": "all"}).content)
    one_len = len(client.get(base, headers=admin, params={"scope": "approved"}).content)
    assert all_len != one_len
    # empty scope -> clear 404
    client.post(f"{PO}/{po2['id']}/approve", headers=admin)
    assert client.get(base, headers=admin, params={"scope": "pending"}).status_code == 404
    assert client.get(base, headers=admin, params={"scope": "bad"}).status_code == 422
    one = client.get(f"{PO}/{po1['id']}/pdf", headers=admin)
    assert one.status_code == 200 and one.content.startswith(b"%PDF")


def test_pdf_text_contains_po_details(client, signup):
    admin = signup()
    _, vendor, po = setup(client, admin)
    client.post(f"{PO}/{po['id']}/approve", headers=admin)
    from app.services import procurement_docs  # noqa
    import zlib, re
    pdf = client.get(f"/api/procurement/vendors/{vendor['id']}/purchase-orders/pdf", headers=admin, params={"scope": "all"}).content
    text = b""
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", pdf, re.S):
        try:
            import base64
            raw = m.group(1).strip()
            try:
                raw = base64.a85decode(raw, adobe=True)
            except Exception:
                pass
            text += zlib.decompress(raw)
        except Exception:
            pass
    assert b"Bharath Steels" in text and b"PO-0001" in text and b"Steel Rod" in text


def test_good_receipt_requires_both_proofs_then_stocks_up(client, signup):
    admin = signup()
    product, _, po = setup(client, admin)
    client.post(f"{PO}/{po['id']}/approve", headers=admin)
    url = f"{PO}/{po['id']}/receive-good"
    r = client.post(url, headers=admin)
    assert r.status_code == 400 and "invoice" in r.json()["detail"]
    r = client.post(url, headers=admin, files={"invoice": ("inv.pdf", PDF_BYTES, "application/pdf")})
    assert r.status_code == 400 and "POD" in r.json()["detail"]
    r = client.post(url, headers=admin, files={"invoice": ("inv.exe", b"MZ", "application/x-msdownload"), "pod": ("p.png", PNG_BYTES, "image/png")})
    assert r.status_code == 400
    r = client.post(url, headers=admin, files={"invoice": ("inv.pdf", b"", "application/pdf"), "pod": ("p.png", PNG_BYTES, "image/png")})
    assert r.status_code == 400
    assert stock_of(client, admin, product["id"]) == 0          # nothing leaked through failures

    r = client.post(url, headers=admin, files=good_files(), data={"notes": "all counted"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "received"
    rc = body["receipts"][0]
    assert rc["condition"] == "good" and rc["received_by_name"] == "Test Admin"
    assert sorted(f["kind"] for f in rc["files"]) == ["invoice", "pod"]
    assert stock_of(client, admin, product["id"]) == 10
    # file round-trip
    f = next(f for f in rc["files"] if f["kind"] == "pod")
    d = client.get(f"/api/procurement/receipt-files/{f['id']}", headers=admin)
    assert d.status_code == 200 and d.content == PNG_BYTES and d.headers["content-type"] == "image/png"
    # cannot receive twice
    assert client.post(url, headers=admin, files=good_files()).status_code == 400
    assert stock_of(client, admin, product["id"]) == 10


def test_bad_receipt_needs_defect_image_and_does_not_stock(client, signup):
    admin = signup()
    product, _, po = setup(client, admin)
    client.post(f"{PO}/{po['id']}/approve", headers=admin)
    url = f"{PO}/{po['id']}/receive-bad"
    r = client.post(url, headers=admin, files=good_files())
    assert r.status_code == 400 and "defect" in r.json()["detail"]
    r = client.post(url, headers=admin, files=[("invoice", ("i.pdf", PDF_BYTES, "application/pdf")), ("pod", ("p.png", PNG_BYTES, "image/png")),
                                              ("defect", ("d.pdf", PDF_BYTES, "application/pdf"))])
    assert r.status_code == 400                                  # defect must be an image
    r = client.post(url, headers=admin, data={"notes": "Rods bent"}, files=[
        ("invoice", ("i.pdf", PDF_BYTES, "application/pdf")), ("pod", ("p.png", PNG_BYTES, "image/png")),
        ("defect", ("d1.png", PNG_BYTES, "image/png")), ("defect", ("d2.png", PNG_BYTES, "image/png"))])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "defective"
    assert [f["kind"] for f in body["receipts"][0]["files"]].count("defect") == 2
    assert stock_of(client, admin, product["id"]) == 0
    # replacement arrives later in good condition
    r = client.post(f"{PO}/{po['id']}/receive-good", headers=admin, files=good_files())
    assert r.status_code == 200 and r.json()["status"] == "received"
    assert stock_of(client, admin, product["id"]) == 10
    assert len(r.json()["receipts"]) == 2


def _bad(client, admin, po_id):
    r = client.post(f"{PO}/{po_id}/receive-bad", headers=admin, data={"notes": "Rods bent"}, files=[
        ("invoice", ("i.pdf", PDF_BYTES, "application/pdf")), ("pod", ("p.png", PNG_BYTES, "image/png")),
        ("defect", ("d1.png", PNG_BYTES, "image/png"))])
    assert r.status_code == 200, r.text
    return r.json()["receipts"][0]["id"]


def test_defect_notice_email_and_print(client, signup, caplog):
    admin = signup()
    _, _, po = setup(client, admin, vendor_email="v@x.com")
    client.post(f"{PO}/{po['id']}/approve", headers=admin)
    rid = _bad(client, admin, po["id"])
    pv = client.get(f"/api/procurement/receipts/{rid}/defect-preview", headers=admin).json()
    assert pv["to_email"] == "v@x.com" and pv["to_name"] == "Bharath Steels"
    assert "Rods bent" in pv["body"] and "NOT accepted" in pv["body"] and "d1.png" in pv["attachments"]
    assert len(pv["attachments"]) == 3

    assert client.post(f"/api/procurement/receipts/{rid}/send-defect-email", headers=admin, json={"to_email": "nope"}).status_code == 400
    with caplog.at_level(logging.WARNING, logger="erp.email"):
        r = client.post(f"/api/procurement/receipts/{rid}/send-defect-email", headers=admin, json={"to_email": "typed@v.com"})
    assert r.status_code == 200 and r.json()["status"] == "logged"
    assert "d1.png" in caplog.text and "typed@v.com" in caplog.text

    pr = client.post(f"/api/procurement/receipts/{rid}/print-notice", headers=admin)
    assert pr.status_code == 200 and pr.content.startswith(b"%PDF")
    actions = {e["action"] for e in client.get("/api/core/audit-log", headers=admin).json()}
    assert {"receive_purchase_order_defective", "send_defect_notice_email", "print_defect_notice"} <= actions


def test_defect_notice_rejected_for_good_receipt(client, signup):
    admin = signup()
    _, _, po = setup(client, admin)
    client.post(f"{PO}/{po['id']}/approve", headers=admin)
    rid = client.post(f"{PO}/{po['id']}/receive-good", headers=admin, files=good_files()).json()["receipts"][0]["id"]
    assert client.get(f"/api/procurement/receipts/{rid}/defect-preview", headers=admin).status_code == 400
    assert client.post(f"/api/procurement/receipts/{rid}/print-notice", headers=admin).status_code == 400


def test_receiving_needs_edit_permission(client, signup):
    admin = signup()
    viewer = make_user(client, admin, [("procurement", "view")])
    _, _, po = setup(client, admin)
    client.post(f"{PO}/{po['id']}/approve", headers=admin)
    assert client.post(f"{PO}/{po['id']}/receive-good", headers=viewer, files=good_files()).status_code == 403


def test_org_isolation_on_everything(client, signup):
    a, b = signup(), signup()
    _, vendor, po = setup(client, a)
    client.post(f"{PO}/{po['id']}/approve", headers=a)
    rid = _bad(client, a, po["id"])
    fid = client.get(PO, headers=a).json()[0]["receipts"][0]["files"][0]["id"]
    assert client.get(PO, headers=b).json() == []
    for method, url, kw in [
        ("get", f"{PO}/{po['id']}/email-preview", {}),
        ("post", f"{PO}/{po['id']}/approve", {}),
        ("get", f"{PO}/{po['id']}/pdf", {}),
        ("post", f"{PO}/{po['id']}/send-email", {"json": {"to_email": "a@b.com"}}),
        ("post", f"{PO}/{po['id']}/receive-good", {"files": good_files()}),
        ("get", f"/api/procurement/vendors/{vendor['id']}/purchase-orders/pdf", {}),
        ("get", f"/api/procurement/receipts/{rid}/defect-preview", {}),
        ("post", f"/api/procurement/receipts/{rid}/print-notice", {}),
        ("get", f"/api/procurement/receipt-files/{fid}", {}),
        ("patch", f"/api/procurement/vendors/{vendor['id']}", {"json": {"email": "x@y.com"}}),
    ]:
        assert getattr(client, method)(url, headers=b, **kw).status_code == 404, url


def test_vendor_email_validation_and_update(client, signup):
    admin = signup()
    assert client.post("/api/procurement/vendors", headers=admin, json={"name": "V", "email": "bad"}).status_code == 400
    v = client.post("/api/procurement/vendors", headers=admin, json={"name": "V"}).json()
    assert v["email"] is None
    r = client.patch(f"/api/procurement/vendors/{v['id']}", headers=admin, json={"email": "ok@v.com"})
    assert r.status_code == 200 and r.json()["email"] == "ok@v.com"
    assert client.patch(f"/api/procurement/vendors/{v['id']}", headers=admin, json={"email": ""}).json()["email"] is None


def test_legacy_receive_route_is_gone(client, signup):
    admin = signup()
    _, _, po = setup(client, admin)
    assert client.post(f"{PO}/{po['id']}/receive", headers=admin).status_code in (404, 405)


def test_corrupt_defect_image_is_rejected_at_upload(client, signup):
    admin = signup()
    _, _, po = setup(client, admin)
    client.post(f"{PO}/{po['id']}/approve", headers=admin)
    r = client.post(f"{PO}/{po['id']}/receive-bad", headers=admin, files=[
        ("invoice", ("i.pdf", PDF_BYTES, "application/pdf")), ("pod", ("p.png", PNG_BYTES, "image/png")),
        ("defect", ("d.png", b"not really a png", "image/png"))])
    assert r.status_code == 400 and "image" in r.json()["detail"]
    assert client.get(PO, headers=admin).json()[0]["status"] == "pending"
