"""
The insufficient-stock rejection is the single scenario the original
Phase 4 build manual calls out by name as proof the whole chain (stock
check, invoice generation, journal entry) succeeds or fails TOGETHER —
never partially. This locks that behavior in permanently.
"""


def create_product_with_stock(client, headers, qty_received=10):
    product = client.post("/api/sales/products", headers=headers, json={
        "name": "Test Widget", "sku": "TW-001", "unit_price": 100, "reorder_level": 5,
    }).json()

    vendor = client.post("/api/procurement/vendors", headers=headers, json={
        "name": "Test Vendor",
    }).json()

    po = client.post("/api/procurement/purchase-orders", headers=headers, json={
        "vendor_id": vendor["id"],
        "items": [{"product_id": product["id"], "qty": qty_received, "unit_price": 50}],
    }).json()

    client.post(f"/api/procurement/purchase-orders/{po['id']}/receive", headers=headers)

    return product


def get_stock_qty(client, headers, product_id):
    levels = client.get("/api/inventory/stock-levels", headers=headers).json()
    for level in levels:
        if level["product_id"] == product_id:
            return level["quantity"]
    return 0


def test_insufficient_stock_is_rejected_and_leaves_stock_untouched(client, signup):
    headers = signup()
    product = create_product_with_stock(client, headers, qty_received=10)

    assert get_stock_qty(client, headers, product["id"]) == 10

    customer = client.post("/api/sales/customers", headers=headers, json={"name": "Test Customer"}).json()
    quotation = client.post("/api/sales/quotations", headers=headers, json={
        "customer_id": customer["id"],
        "items": [{"product_id": product["id"], "qty": 999, "unit_price": 100}],  # far more than exists
    }).json()
    order = client.post(f"/api/sales/quotations/{quotation['id']}/accept", headers=headers).json()

    resp = client.post(f"/api/sales/orders/{order['id']}/invoice", headers=headers)
    assert resp.status_code in (400, 422), f"expected rejection, got {resp.status_code}: {resp.text}"

    # The critical assertion: stock must be EXACTLY what it was before the
    # attempt, not partially decremented.
    assert get_stock_qty(client, headers, product["id"]) == 10


def test_sufficient_stock_succeeds_and_decrements_correctly(client, signup):
    headers = signup()
    product = create_product_with_stock(client, headers, qty_received=10)

    customer = client.post("/api/sales/customers", headers=headers, json={"name": "Test Customer"}).json()
    quotation = client.post("/api/sales/quotations", headers=headers, json={
        "customer_id": customer["id"],
        "items": [{"product_id": product["id"], "qty": 4, "unit_price": 100}],
    }).json()
    order = client.post(f"/api/sales/quotations/{quotation['id']}/accept", headers=headers).json()

    resp = client.post(f"/api/sales/orders/{order['id']}/invoice", headers=headers)
    assert resp.status_code == 201, resp.text

    assert get_stock_qty(client, headers, product["id"]) == 6  # 10 received - 4 sold
