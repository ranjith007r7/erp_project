"""
Seeds a realistic demo organization by calling the REAL API endpoints,
the same way a real user or the frontend would - not direct SQL inserts.
This is deliberate: going through the real endpoints means every
business rule (stock checks, journal-entry balancing, self-healing
accounts, RBAC seeding) runs exactly as it would for a real user, so the
seeded data is guaranteed internally consistent, not just plausible-
looking rows dropped into tables.

Usage:
    cd backend
    # against local dev:
    python3 scripts/seed_demo_org.py
    # against a deployed instance:
    python3 scripts/seed_demo_org.py --api-url https://your-backend.onrender.com

Safe to re-run: each run creates a brand-new org with a timestamped
subdomain, so it never collides with a previous seed run or real client
data. It does NOT touch or modify any existing organization.
"""
import argparse
import random
import sys
import time
from datetime import date, timedelta

import requests

random.seed(42)  # reproducible demo data run to run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://localhost:8000")
    args = parser.parse_args()
    base = args.api_url.rstrip("/")

    def post(path, json=None, headers=None, expect=(200, 201)):
        resp = requests.post(f"{base}{path}", json=json, headers=headers)
        if resp.status_code not in expect:
            print(f"FAILED: POST {path} -> {resp.status_code}: {resp.text}", file=sys.stderr)
            sys.exit(1)
        return resp.json() if resp.text else None

    def patch(path, json=None, headers=None, expect=(200,)):
        resp = requests.patch(f"{base}{path}", json=json, headers=headers)
        if resp.status_code not in expect:
            print(f"FAILED: PATCH {path} -> {resp.status_code}: {resp.text}", file=sys.stderr)
            sys.exit(1)
        return resp.json() if resp.text else None

    def get(path, headers=None):
        resp = requests.get(f"{base}{path}", headers=headers)
        if resp.status_code != 200:
            print(f"FAILED: GET {path} -> {resp.status_code}: {resp.text}", file=sys.stderr)
            sys.exit(1)
        return resp.json()

    print(f"Seeding demo org against {base} ...")

    stamp = int(time.time())
    signup = post("/api/auth/signup", json={
        "org_name": "Meridian Furnishings",
        "subdomain": f"meridian-demo-{stamp}",
        "admin_name": "Priya Sharma",
        "admin_email": f"priya-{stamp}@meridianfurnishings.com",
        "admin_password": "DemoPass123!",
    })
    auth = {"Authorization": f"Bearer {signup['access_token']}"}
    print(f"  org created: subdomain=meridian-demo-{stamp}, admin login=priya-{stamp}@meridianfurnishings.com / DemoPass123!")

    # ---------------- Inventory: categories + products ----------------
    print("Seeding Inventory ...")
    cat_furniture = post("/api/inventory/categories", headers=auth, json={"name": "Office Furniture"})
    cat_seating = post("/api/inventory/categories", headers=auth, json={"name": "Seating"})

    products = [
        ("Oakwood Executive Desk", "DSK-001", cat_furniture["id"], 24999, 5),
        ("Meridian Standing Desk", "DSK-002", cat_furniture["id"], 34999, 3),
        ("Filing Cabinet — 3 Drawer", "STG-001", cat_furniture["id"], 8999, 10),
        ("ErgoPro Office Chair", "CHR-001", cat_seating["id"], 12999, 15),
        ("Visitor Chair — Pair", "CHR-002", cat_seating["id"], 6999, 5),  # reorder_level=5, will receive only 3 -> triggers a real low-stock alert
    ]
    product_ids = {}
    for name, sku, cat_id, price, reorder_level in products:
        p = post("/api/sales/products", headers=auth, json={
            "name": name, "sku": sku, "category_id": cat_id, "unit_price": price, "reorder_level": reorder_level,
        })
        product_ids[sku] = p["id"]

    # ---------------- Procurement: vendor + PO to actually stock everything ----------------
    print("Seeding Procurement ...")
    vendor = post("/api/procurement/vendors", headers=auth, json={
        "name": "Bharat Timber & Steel Supplies", "contact": "vikram@bharattimber.com",
    })
    po = post("/api/procurement/purchase-orders", headers=auth, json={
        "vendor_id": vendor["id"],
        "items": [
            {"product_id": product_ids["DSK-001"], "qty": 12, "unit_price": 15000},
            {"product_id": product_ids["DSK-002"], "qty": 8, "unit_price": 22000},
            {"product_id": product_ids["STG-001"], "qty": 20, "unit_price": 5500},
            {"product_id": product_ids["CHR-001"], "qty": 30, "unit_price": 8000},
            {"product_id": product_ids["CHR-002"], "qty": 3, "unit_price": 4500},  # receiving 3 against reorder_level=5 -> genuinely low stock
        ],
    })
    post(f"/api/procurement/purchase-orders/{po['id']}/receive", headers=auth)

    # A SECOND, small PO for visitor chairs left deliberately unreceived,
    # so Procurement's list shows a real "pending" order, not just
    # everything already fulfilled.
    post("/api/procurement/purchase-orders", headers=auth, json={
        "vendor_id": vendor["id"],
        "items": [{"product_id": product_ids["CHR-002"], "qty": 10, "unit_price": 4500}],
    })

    # ---------------- CRM: leads at different stages ----------------
    print("Seeding CRM ...")
    lead_names = [
        ("Anjali Mehta", "Konnect Coworking", "anjali@konnectcoworking.in", "Website"),
        ("Rohan Kapoor", "Zenith Legal LLP", "rohan@zenithlegal.in", "Referral"),
        ("Fatima Sheikh", "Bright Future School", "fatima@brightfutureschool.edu", "LinkedIn"),
    ]
    lead_ids = []
    for name, company, email, source in lead_names:
        lead = post("/api/crm/leads", headers=auth, json={
            "name": name, "company_name": company, "email": email, "source": source,
        })
        lead_ids.append(lead["id"])

    # Convert two of the three leads into real opportunities/accounts —
    # the third stays a raw lead, showing the pipeline mid-flow, not
    # artificially all-converted.
    post(f"/api/crm/leads/{lead_ids[0]}/convert", headers=auth, json={
        "opportunity_name": "Konnect Coworking — 40-Desk Fitout", "opportunity_value": 850000,
    })
    post(f"/api/crm/leads/{lead_ids[1]}/convert", headers=auth, json={
        "opportunity_name": "Zenith Legal — Partner Office Refresh", "opportunity_value": 320000,
    })

    # ---------------- Sales: the full quote-to-cash story ----------------
    print("Seeding Sales ...")
    customer_a = post("/api/sales/customers", headers=auth, json={"name": "Konnect Coworking Pvt Ltd"})
    customer_b = post("/api/sales/customers", headers=auth, json={"name": "Zenith Legal LLP"})

    # Customer A: full cycle through to a PAID invoice.
    quote_a = post("/api/sales/quotations", headers=auth, json={
        "customer_id": customer_a["id"],
        "items": [
            {"product_id": product_ids["DSK-002"], "qty": 5, "unit_price": 34999},
            {"product_id": product_ids["CHR-001"], "qty": 5, "unit_price": 12999},
        ],
    })
    order_a = post(f"/api/sales/quotations/{quote_a['id']}/accept", headers=auth)
    invoice_a = post(f"/api/sales/orders/{order_a['id']}/invoice", headers=auth)
    post("/api/finance/payments", headers=auth, json={"invoice_id": invoice_a["id"], "amount": invoice_a["amount"]})

    # Customer B: invoiced but deliberately left UNPAID, so Finance's
    # "Unpaid Invoices" panel has something real to show.
    quote_b = post("/api/sales/quotations", headers=auth, json={
        "customer_id": customer_b["id"],
        "items": [
            {"product_id": product_ids["DSK-001"], "qty": 3, "unit_price": 24999},
            {"product_id": product_ids["STG-001"], "qty": 3, "unit_price": 8999},
        ],
    })
    order_b = post(f"/api/sales/quotations/{quote_b['id']}/accept", headers=auth)
    post(f"/api/sales/orders/{order_b['id']}/invoice", headers=auth)

    # A THIRD quotation left as just a quotation, never accepted — shows
    # the top of the sales funnel too, not just closed deals.
    post("/api/sales/quotations", headers=auth, json={
        "customer_id": customer_a["id"],
        "items": [{"product_id": product_ids["CHR-002"], "qty": 2, "unit_price": 6999}],
    })

    # ---------------- HR: departments, employees, leave, a processed payroll run ----------------
    print("Seeding HR & Payroll ...")
    dept_sales = post("/api/hr/departments", headers=auth, json={"name": "Sales"})
    dept_ops = post("/api/hr/departments", headers=auth, json={"name": "Operations"})

    employees = [
        ("Arjun Nair", "Sales Executive", dept_sales["id"], 45000),
        ("Kavya Reddy", "Operations Manager", dept_ops["id"], 62000),
        ("Sameer Iyer", "Warehouse Associate", dept_ops["id"], 28000),
    ]
    employee_ids = []
    for name, designation, dept_id, salary in employees:
        emp = post("/api/hr/employees", headers=auth, json={
            "name": name, "designation": designation, "department_id": dept_id, "salary": salary,
        })
        employee_ids.append(emp["id"])

    # A pending leave request left un-actioned, so HR's "Leave Requests"
    # panel has something real to click through during a demo.
    post("/api/hr/leave-requests", headers=auth, json={
        "employee_id": employee_ids[0], "leave_type": "sick",
        "start_date": str(date.today() + timedelta(days=3)),
        "end_date": str(date.today() + timedelta(days=4)),
    })

    # A second leave request that IS actioned, to show the approved state too.
    leave2 = post("/api/hr/leave-requests", headers=auth, json={
        "employee_id": employee_ids[1], "leave_type": "annual",
        "start_date": str(date.today() + timedelta(days=10)),
        "end_date": str(date.today() + timedelta(days=14)),
    })
    patch(f"/api/hr/leave-requests/{leave2['id']}/status", headers=auth, json={"status": "approved"})

    run = post("/api/hr/payroll-runs", headers=auth, json={"month": date.today().month, "year": date.today().year})
    post(f"/api/hr/payroll-runs/{run['id']}/process", headers=auth)

    # ---------------- Documents: a workflow + a request awaiting action ----------------
    print("Seeding Documents & Workflow Approvals ...")
    workflow = post("/api/documents/workflows", headers=auth, json={
        "name": "Expense Approval", "module": "finance",
        "steps": [{"role": "Admin"}],  # only real role available out of the box
    })
    post("/api/documents/approval-requests", headers=auth, json={
        "workflow_id": workflow["id"], "entity_type": "expense_report", "entity_id": order_a["id"],
    })

    # ---------------- Custom Fields: define + populate on real records ----------------
    print("Seeding Custom Fields ...")
    field_batch = post("/api/custom-fields", headers=auth, json={
        "module": "inventory", "entity_type": "product", "field_name": "Warranty Period",
        "field_type": "dropdown", "options": "6 Months,1 Year,2 Years",
    })
    post("/api/custom-fields/values", headers=auth, json={
        "entity_type": "product", "entity_id": product_ids["DSK-002"],
        "values": [{"custom_field_id": field_batch["id"], "value": "2 Years"}],
    })

    field_linkedin = post("/api/custom-fields", headers=auth, json={
        "module": "crm", "entity_type": "lead", "field_name": "LinkedIn URL", "field_type": "text",
    })
    post("/api/custom-fields/values", headers=auth, json={
        "entity_type": "lead", "entity_id": lead_ids[2],
        "values": [{"custom_field_id": field_linkedin["id"], "value": "linkedin.com/in/fatimasheikh"}],
    })

    # ---------------- RBAC: one restricted role, to demo the security model ----------------
    print("Seeding a restricted role for the RBAC demo ...")
    viewer_role = post("/api/core/roles", headers=auth, json={"name": "Sales Viewer"})
    post(f"/api/core/roles/{viewer_role['id']}/permissions", headers=auth, json={"module": "sales", "action": "view"})
    post(f"/api/core/roles/{viewer_role['id']}/permissions", headers=auth, json={"module": "crm", "action": "view"})
    post("/api/core/users", headers=auth, json={
        "name": "Demo Viewer", "email": f"viewer-{stamp}@meridianfurnishings.com",
        "password": "DemoPass123!", "role_id": viewer_role["id"],
    })

    print("")
    print("=" * 70)
    print("Demo organization seeded successfully.")
    print(f"  Admin login:  priya-{stamp}@meridianfurnishings.com / DemoPass123!")
    print(f"  Viewer login: viewer-{stamp}@meridianfurnishings.com / DemoPass123!")
    print("=" * 70)


if __name__ == "__main__":
    main()
