"""CRM: converted quotations leave the working list, show in the Converted list, and cannot be deleted; pending ones still can."""
from test_rbac_permissions import create_restricted_user


def _lead(client, h, name, **kw):
    r = client.post("/api/crm/leads", headers=h, json={"name": name, "company_name": "Acme", "phone": "9876543210", "estimated_amount": 5000, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def _convert(client, h, lead):
    r = client.post(f"/api/crm/leads/{lead['id']}/convert", headers=h, json={"opportunity_name": "Deal " + lead["name"], "opportunity_value": 5000})
    assert r.status_code == 201, r.text


def test_converted_leave_pending_list_and_show_in_converted_list(client, signup):
    h = signup()
    a, b = _lead(client, h, "Pending One"), _lead(client, h, "Done One")
    _convert(client, h, b)
    pending = client.get("/api/crm/leads?converted=false", headers=h).json()
    assert [x["name"] for x in pending] == ["Pending One"]
    assert [x["name"] for x in client.get("/api/crm/leads?converted=true", headers=h).json()] == ["Done One"]
    assert len(client.get("/api/crm/leads", headers=h).json()) == 2
    c = client.get("/api/crm/leads/converted", headers=h).json()
    assert c["total"] == 1 and c["items"][0]["name"] == "Done One"
    w = c["items"][0]["work"]
    assert w["work_number"].startswith("WK-") and w["status_label"] and w["work_id"]
    assert client.get("/api/crm/leads/converted?q=nomatch", headers=h).json()["total"] == 0
    assert client.get("/api/crm/leads/converted?q=acme", headers=h).json()["total"] == 1
    assert client.get("/api/crm/leads/converted", headers=signup()).json()["total"] == 0


def test_converted_cannot_be_deleted_but_pending_can(client, signup):
    h = signup()
    a, b = _lead(client, h, "Pending"), _lead(client, h, "Converted")
    _convert(client, h, b)
    r = client.delete(f"/api/crm/leads/{b['id']}", headers=h)
    assert r.status_code == 409 and "can't be deleted" in r.json()["detail"] and "Work completed or Cancelled" in r.json()["detail"]
    assert client.get("/api/crm/leads/converted", headers=h).json()["total"] == 1       # still there, work intact
    assert client.delete(f"/api/crm/leads/{a['id']}", headers=h).status_code == 204
    # bulk: converted ones are skipped and reported, others deleted
    c, d = _lead(client, h, "P2"), _lead(client, h, "P3")
    out = client.post("/api/crm/leads/bulk-delete", headers=h, json={"ids": [c["id"], b["id"], d["id"]]}).json()
    assert sorted(out["deleted"]) == sorted([c["id"], d["id"]]) and [x["id"] for x in out["blocked_converted"]] == [b["id"]] and out["message"]
    assert client.get("/api/crm/leads/converted", headers=h).json()["total"] == 1


def test_converted_list_needs_crm_view(client, signup):
    h = signup()
    sales_only = create_restricted_user(client, h, "sales", "view")
    assert client.get("/api/crm/leads/converted", headers=sales_only).status_code == 403
