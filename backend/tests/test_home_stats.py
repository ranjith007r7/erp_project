"""Analytics home figures (daily-resetting) and the admin-only report downloads."""
import uuid
from datetime import date, timedelta

from conftest import login_any, PDF_BYTES

H = "/api/dashboard/home"
W = "/api/workpage/works"


def user_with(client, admin, perms, name="Emp"):
    unique = uuid.uuid4().hex[:8]
    role = client.post("/api/core/roles", headers=admin, json={"name": f"R {unique}"}).json()
    for m, a in perms:
        client.post(f"/api/core/roles/{role['id']}/permissions", headers=admin, json={"module": m, "action": a})
    email = f"u-{unique}@test.com"
    client.post("/api/core/users", headers=admin, json={"name": name, "email": email, "password": "pass12345", "role_id": role["id"]})
    return {"Authorization": f"Bearer {login_any(client, email, 'pass12345').json()['access_token']}"}


def test_empty_org_home_is_all_zero(client, signup):
    h = signup()
    d = client.get(H, headers=h).json()
    assert d["period"] == "today" and d["scope"] == "organization"
    assert d["income"]["total"] == 0 and d["works"] == {"assigned": 0, "completed": 0, "pending": 0}
    assert d["quotes"]["processed"] == 0 and d["purchase_orders"]["raised"] == 0 and len(d["income_trend"]) == 7


def test_figures_move_with_real_activity(client, signup):
    h = signup()
    w = client.post(W, headers=h, json={"client_name": "Acme", "quotation_amount": 1000, "vendor_amount": 400}).json()
    client.post(f"{W}/{w['id']}/payments", headers=h, json={"amount": 250, "method": "cash"})
    prod = client.post("/api/sales/products", headers=h, json={"name": "P", "unit_price": 10}).json()
    cust = client.post("/api/sales/customers", headers=h, json={"name": "C"}).json()
    q = client.post("/api/sales/quotations", headers=h, json={"customer_id": cust["id"], "items": [{"product_id": prod["id"], "qty": 2, "unit_price": 10}]}).json()
    client.post(f"/api/sales/quotations/{q['id']}/accept", headers=h)   # opens a second work
    vendor = client.post("/api/procurement/vendors", headers=h, json={"name": "V"}).json()
    client.post("/api/procurement/purchase-orders", headers=h, json={"vendor_id": vendor["id"], "work_order_id": w["id"], "items": [{"product_id": prod["id"], "qty": 1, "unit_price": 5}]})
    d = client.get(H, headers=h).json()
    assert d["income"]["total"] == 250
    assert d["quotes"] == {"processed": 1, "accepted": 1, "value": 20.0}
    assert d["deals"]["new"] == 2 and d["works"]["assigned"] == 2 and d["works"]["pending"] == 2 and d["works"]["completed"] == 0
    assert d["purchase_orders"]["raised"] == 1 and d["purchase_orders"]["awaiting_approval"] == 1
    assert {s["key"]: s["count"] for s in d["work_status"]}["po_raised"] == 1
    assert d["income_trend"][-1]["amount"] == 250
    assert len(d["recent_works"]) == 2


def test_other_days_start_at_zero_and_week_month_include_today(client, signup):
    h = signup()
    client.post(W, headers=h, json={"client_name": "Acme", "quotation_amount": 100})
    yesterday = (date.today() - timedelta(days=2)).isoformat()
    assert client.get(H, headers=h, params={"on": yesterday}).json()["deals"]["new"] == 0
    assert client.get(H, headers=h, params={"period": "week"}).json()["deals"]["new"] == 1
    assert client.get(H, headers=h, params={"period": "month"}).json()["deals"]["new"] == 1
    assert client.get(H, headers=h, params={"period": "year"}).status_code == 422


def test_cards_hidden_without_module_permission_and_tenant_isolated(client, signup):
    admin, other = signup(), signup()
    client.post(W, headers=admin, json={"client_name": "Acme", "quotation_amount": 100})
    assert client.get(H, headers=other).json()["deals"]["new"] == 0
    only_dash = user_with(client, admin, [("dashboard", "view")])
    d = client.get(H, headers=only_dash).json()
    assert d["scope"] == "mine" and d["income"] is None and d["works"] is None and d["quotes"] is None and d["tasks"] is None
    nothing = user_with(client, admin, [("crm", "view")])
    assert client.get(H, headers=nothing).status_code == 403


def test_non_admin_sees_only_own_department_works(client, signup):
    admin = signup()
    d1 = client.post("/api/hr/departments", headers=admin, json={"name": "Ops X"}).json()
    mine = client.post(W, headers=admin, json={"client_name": "Mine", "quotation_amount": 10, "department_id": d1["id"]}).json()
    client.post(W, headers=admin, json={"client_name": "Not mine", "quotation_amount": 10})
    emp = client.post("/api/hr/employees", headers=admin, json={"name": "Ops Person", "department_id": d1["id"]}).json()
    unique = uuid.uuid4().hex[:8]
    role = client.post("/api/core/roles", headers=admin, json={"name": f"Ops {unique}"}).json()
    for m in ("dashboard", "workpage"):
        client.post(f"/api/core/roles/{role['id']}/permissions", headers=admin, json={"module": m, "action": "view"})
    email = f"ops-{unique}@test.com"
    created = client.post("/api/core/users", headers=admin, json={"name": "Ops Person", "email": email, "password": "pass12345", "role_id": role["id"]})
    assert created.status_code == 201, created.text
    from app.core import database as dbm
    from app.models.hr import Employee
    s = dbm.SessionLocal()
    s.query(Employee).filter(Employee.id == emp["id"]).update({"user_id": created.json()["id"]})
    s.commit(); s.close()
    h = {"Authorization": f"Bearer {login_any(client, email, 'pass12345').json()['access_token']}"}
    d = client.get(H, headers=h).json()
    assert d["works"]["pending"] == 1 and [w["client_name"] for w in d["recent_works"]] == ["Mine"]
    assert mine["id"]


def test_report_downloads_admin_only_pdf_and_csv(client, signup):
    admin = signup()
    w = client.post(W, headers=admin, json={"client_name": "Acme & Sons", "quotation_amount": 500, "vendor_amount": 100}).json()
    client.post(f"{W}/{w['id']}/payments", headers=admin, json={"amount": 100, "method": "cash"})
    for kind in ("daily", "weekly", "monthly"):
        pdf = client.get("/api/dashboard/report", headers=admin, params={"kind": kind, "format": "pdf"})
        assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF" and "attachment" in pdf.headers["content-disposition"]
    csv = client.get("/api/dashboard/report", headers=admin, params={"kind": "daily", "format": "csv"})
    text = csv.content.decode("utf-8-sig")
    assert csv.status_code == 200 and "Daily report" in text and "Acme & Sons" in text and "Income received,Rs. 100.00" in text
    emp = user_with(client, admin, [("dashboard", "view"), ("reports", "view"), ("workpage", "view")])
    assert client.get("/api/dashboard/report", headers=emp, params={"kind": "daily"}).status_code == 403
    assert client.get("/api/dashboard/report", headers=admin, params={"kind": "yearly"}).status_code == 422
