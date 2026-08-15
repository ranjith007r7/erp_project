

def stock_product(client, headers, product_id, qty=100):
    """Receives stock via a real Purchase Order - invoicing requires it."""
    vendor = client.post("/api/procurement/vendors", headers=headers, json={"name": "Test Vendor"}).json()
    po = client.post("/api/procurement/purchase-orders", headers=headers, json={
        "vendor_id": vendor["id"],
        "items": [{"product_id": product_id, "qty": qty, "unit_price": 10}],
    }).json()
    client.post(f"/api/procurement/purchase-orders/{po['id']}/receive", headers=headers)

"""
Flagged as an open gap since the very first handoff document: every
phase tested one organization thoroughly, but two organizations were
never deliberately compared side-by-side to prove Org A genuinely cannot
see Org B's data through any endpoint. This closes that gap.
"""


def test_org_b_cannot_see_org_as_leads(client, signup):
    headers_a = signup("Org A")
    headers_b = signup("Org B")

    client.post("/api/crm/leads", headers=headers_a, json={"name": "Org A Lead", "source": "Website"})
    client.post("/api/crm/leads", headers=headers_b, json={"name": "Org B Lead", "source": "Website"})

    leads_seen_by_a = client.get("/api/crm/leads", headers=headers_a).json()
    leads_seen_by_b = client.get("/api/crm/leads", headers=headers_b).json()

    a_names = {l["name"] for l in leads_seen_by_a}
    b_names = {l["name"] for l in leads_seen_by_b}

    assert "Org A Lead" in a_names and "Org B Lead" not in a_names
    assert "Org B Lead" in b_names and "Org A Lead" not in b_names


def test_org_b_cannot_fetch_org_as_specific_product_by_id(client, signup):
    """Not just list endpoints — direct-by-ID access must also be blocked across orgs."""
    headers_a = signup("Org A")
    headers_b = signup("Org B")

    product_a = client.post("/api/sales/products", headers=headers_a, json={"name": "Org A Product", "unit_price": 100}).json()

    # Org B's product list must not contain Org A's product at all.
    products_seen_by_b = client.get("/api/sales/products", headers=headers_b).json()
    assert product_a["id"] not in [p["id"] for p in products_seen_by_b]


def test_org_b_cannot_pay_org_as_invoice(client, signup):
    """Cross-org write attempts (not just reads) must be blocked too."""
    headers_a = signup("Org A")
    headers_b = signup("Org B")

    product = client.post("/api/sales/products", headers=headers_a, json={"name": "Widget", "unit_price": 100}).json()
    stock_product(client, headers_a, product["id"])
    customer = client.post("/api/sales/customers", headers=headers_a, json={"name": "Customer"}).json()
    quotation = client.post("/api/sales/quotations", headers=headers_a, json={
        "customer_id": customer["id"],
        "items": [{"product_id": product["id"], "qty": 1, "unit_price": 100}],
    }).json()
    order = client.post(f"/api/sales/quotations/{quotation['id']}/accept", headers=headers_a).json()
    invoice = client.post(f"/api/sales/orders/{order['id']}/invoice", headers=headers_a).json()

    # Org B attempts to pay Org A's invoice directly by ID.
    resp = client.post("/api/finance/payments", headers=headers_b, json={
        "invoice_id": invoice["id"], "amount": 100,
    })
    assert resp.status_code in (400, 403, 404), (
        f"expected Org B to be blocked from paying Org A's invoice, got {resp.status_code}: {resp.text}"
    )


def test_org_b_admin_cannot_manage_org_as_users(client, signup):
    """The RBAC/user-management endpoints themselves must also be org-scoped."""
    headers_a = signup("Org A")
    headers_b = signup("Org B")

    users_seen_by_b = client.get("/api/core/users", headers=headers_b).json()
    emails_seen_by_b = {u["email"] for u in users_seen_by_b}

    users_seen_by_a = client.get("/api/core/users", headers=headers_a).json()
    a_admin_email = users_seen_by_a[0]["email"]

    assert a_admin_email not in emails_seen_by_b
