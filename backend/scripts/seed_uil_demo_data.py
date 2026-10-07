"""
Seeds ONE realistic demo organization with a year of history across every
module, so the Unified Intelligence Layer has something meaningful to
answer questions about ("revenue by month", "overdue invoices", "headcount
by department" are meaningless on an org with 5 rows).

SYNTHETIC DATA ONLY. Everything here is invented. That matters because the
free Gemini tier may use prompts and responses to improve Google's models;
never point the intelligence layer at real client data on the free tier.

Reuses the app's own logic instead of re-implementing it:
  - the real signup route function (roles, permissions, default chart of
    accounts, report subscription all come out exactly like a real org)
  - the real accounting service (invoice/payment/payroll ledger postings), with
    only the posting date changed so the history is spread over time.

Deterministic: the same --seed always produces the same data, so an
interesting answer can be reproduced.

DANGER GUARD: this writes a lot of rows. Given this project's own history
(a migration once hit production because DATABASE_URL was left pointing at it),
the script prints the target database and requires you to TYPE its name.

Usage (from the backend folder, venv active):
    python scripts/seed_uil_demo_data.py --subdomain acme-demo
    python scripts/seed_uil_demo_data.py --subdomain globex-demo --org-name "Globex Demo" --seed 7
"""
import argparse
import datetime
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.engine.url import make_url  # noqa: E402

DEPARTMENTS = ["Engineering", "Sales", "Finance", "Human Resources", "Operations"]
DESIGNATIONS = {
    "Engineering": ["Software Engineer", "Senior Engineer", "QA Engineer"],
    "Sales": ["Sales Executive", "Account Manager"],
    "Finance": ["Accountant", "Finance Analyst"],
    "Human Resources": ["HR Executive"],
    "Operations": ["Operations Associate", "Logistics Coordinator"],
}
FIRST = ["Aarav", "Diya", "Kabir", "Meera", "Rohan", "Ananya", "Vikram", "Isha", "Arjun", "Sneha", "Nikhil", "Priya",
         "Rahul", "Kavya", "Siddharth", "Neha", "Aditya", "Pooja", "Karthik", "Divya"]
LAST = ["Sharma", "Iyer", "Reddy", "Nair", "Gupta", "Menon", "Patel", "Das", "Rao", "Kapoor"]
COMPANIES = ["Northwind Traders", "Blue Harbor Logistics", "Sundial Retail", "Apex Fabricators", "Lotus Healthcare",
             "Orbit Telecom", "Greenfield Foods", "Zenith Auto Parts", "Harbor Light Hotels", "Pinnacle Textiles",
             "Riverside Pharma", "Crestview Education"]
PRODUCTS = [  # (name, category, unit_price, reorder_level)
    ("Industrial Sensor X1", "Hardware", 4500, 40), ("Control Panel CP-200", "Hardware", 18500, 10),
    ("Wireless Gateway G5", "Hardware", 7200, 25), ("Smart Meter SM-10", "Hardware", 3100, 60),
    ("Cable Kit (50m)", "Hardware", 950, 80), ("Analytics Suite - Annual", "Software", 24000, 0),
    ("Monitoring Platform - Annual", "Software", 16000, 0), ("Mobile App License", "Software", 2200, 0),
    ("Installation Service", "Services", 5500, 0), ("Maintenance Contract - Quarterly", "Services", 8800, 0),
    ("Training Workshop", "Services", 12000, 0), ("Remote Support Pack", "Services", 3000, 0),
    ("Spare Battery Pack", "Hardware", 1400, 100), ("Mounting Bracket Set", "Hardware", 600, 120),
]
LEAD_SOURCES = ["Website", "Referral", "Cold Call", "Trade Show", "Partner", "LinkedIn"]


def _month_start(today, back):
    year, month = today.year, today.month - back
    while month <= 0:
        month += 12
        year -= 1
    return datetime.date(year, month, 1)


def seed_demo_org(db, *, org_name, subdomain, admin_email, admin_password, seed=42, months=12):
    """Create one fully-populated demo org. Returns its org_id (str)."""
    import app.api.routes.auth as auth_routes
    import app.models  # noqa: F401  - registers every table
    from app.core.security import hash_password
    from app.models.crm import Account, Contact, Lead, Opportunity
    from app.models.finance import Payment
    from app.models.hr import Attendance, Department, Employee, LeaveRequest, PayrollRun, Payslip
    from app.models.inventory import ProductCategory, StockLevel, StockMovement, Warehouse
    from app.models.procurement import GoodsReceipt, PurchaseOrder, PurchaseOrderItem, Vendor
    from app.models.projects import Project, Task, TimeLog
    from app.models.role import Role
    from app.models.sales import Customer, Invoice, Product, SalesOrder, SalesOrderItem
    from app.models.user import User
    from app.schemas.auth import OrganizationSignup
    from app.services import accounting

    rng = random.Random(seed)
    today = datetime.date.today()

    # --- the real signup logic; silence the verification email it would send.
    # (Must patch the name auth.py actually calls. With a real RESEND_API_KEY
    # configured, an unsilenced seed run would try to send real emails.)
    original_sender = auth_routes.send_verification_email
    auth_routes.send_verification_email = lambda *args, **kwargs: None
    try:
        auth_routes.signup(
            OrganizationSignup(org_name=org_name, subdomain=subdomain, admin_name="Demo Admin",
                               admin_email=admin_email, admin_password=admin_password),
            db,
        )
    finally:
        auth_routes.send_verification_email = original_sender  # never leave global state patched
    admin = db.query(User).filter(User.email == admin_email).one()
    admin.email_verified = True  # demo org: log in immediately, no emailed link
    org_id = str(admin.org_id)

    # --- sales team (users)
    rep_role = Role(org_id=org_id, name="Sales Rep")
    db.add(rep_role)
    db.flush()
    reps = []
    for i in range(1, 4):
        u = User(org_id=org_id, name=f"{rng.choice(FIRST)} {rng.choice(LAST)}", email=f"rep{i}@{subdomain}.example.com",
                 password_hash=hash_password(admin_password), role_id=rep_role.id, email_verified=True)
        db.add(u)
        reps.append(u)
    db.flush()
    people = [admin] + reps

    # --- HR
    depts = {}
    for name in DEPARTMENTS:
        d = Department(org_id=org_id, name=name)
        db.add(d)
        depts[name] = d
    db.flush()
    employees = []
    for i in range(18):
        dept = rng.choice(DEPARTMENTS)
        base = {"Engineering": 90000, "Sales": 60000, "Finance": 65000, "Human Resources": 55000, "Operations": 45000}[dept]
        e = Employee(org_id=org_id, name=f"{FIRST[i % len(FIRST)]} {rng.choice(LAST)}",
                     designation=rng.choice(DESIGNATIONS[dept]), department_id=depts[dept].id,
                     joining_date=today - datetime.timedelta(days=rng.randint(60, 1500)),
                     salary=round(base * rng.uniform(0.8, 1.6), -2), status="inactive" if i >= 16 else "active")
        db.add(e)
        employees.append(e)
    db.flush()
    active_employees = [e for e in employees if e.status == "active"]

    for e in rng.sample(active_employees, 6):
        for d in range(1, 8):
            day = today - datetime.timedelta(days=d)
            if day.weekday() < 5:
                db.add(Attendance(employee_id=e.id, date=day, status=rng.choice(["present"] * 8 + ["absent", "half_day"])))
    for e in rng.sample(active_employees, 5):
        start = today - datetime.timedelta(days=rng.randint(5, 120))
        db.add(LeaveRequest(employee_id=e.id, leave_type=rng.choice(["Sick", "Casual", "Earned"]), start_date=start,
                            end_date=start + datetime.timedelta(days=rng.randint(0, 3)),
                            status=rng.choice(["approved", "approved", "pending", "rejected"])))

    # --- inventory + products
    cats = {}
    for name in ("Hardware", "Software", "Services"):
        c = ProductCategory(org_id=org_id, name=name)
        db.add(c)
        cats[name] = c
    warehouses = [Warehouse(org_id=org_id, name="Chennai Main", location="Chennai"),
                  Warehouse(org_id=org_id, name="Bengaluru Hub", location="Bengaluru")]
    db.add_all(warehouses)
    db.flush()
    products = []
    for name, cat, price, reorder in PRODUCTS:
        p = Product(org_id=org_id, name=name, unit_price=price, sku=f"SKU-{len(products) + 1:03d}",
                    category_id=cats[cat].id, reorder_level=reorder)
        db.add(p)
        products.append(p)
    db.flush()
    for p in products:
        if p.reorder_level > 0:
            # Decide per PRODUCT (low-stock is defined on the total across warehouses),
            # so roughly a third of stocked products really are at/below reorder level.
            is_low = rng.random() < 0.4
            total = rng.randint(0, p.reorder_level) if is_low else rng.randint(p.reorder_level + 10, p.reorder_level * 4)
            first_share = rng.randint(0, total)
            for w, qty in zip(warehouses, (first_share, total - first_share)):
                db.add(StockLevel(product_id=p.id, warehouse_id=w.id, quantity=qty))
                db.add(StockMovement(org_id=org_id, product_id=p.id, warehouse_id=w.id, movement_type="in", qty=qty,
                                     ref_type="purchase_order", date=today - datetime.timedelta(days=rng.randint(10, 200))))

    # --- CRM
    accounts, customers = [], []
    for name in COMPANIES:
        acc = Account(org_id=org_id, name=name, industry=rng.choice(["Retail", "Logistics", "Healthcare", "Manufacturing", "Telecom", "Education"]),
                      address=f"{rng.randint(1, 99)} Industrial Estate, {rng.choice(['Chennai', 'Pune', 'Hyderabad', 'Mumbai'])}")
        db.add(acc)
        accounts.append(acc)
    db.flush()
    for acc in accounts:
        db.add(Contact(org_id=org_id, account_id=acc.id, name=f"{rng.choice(FIRST)} {rng.choice(LAST)}",
                       email=f"contact@{acc.name.split()[0].lower()}.example.com", phone="9000000000"))
        cust = Customer(org_id=org_id, account_id=acc.id, name=acc.name, billing_address=acc.address,
                        gst_number=f"33{rng.randint(10000, 99999)}A1Z5")
        db.add(cust)
        customers.append(cust)
    for i in range(28):
        db.add(Lead(org_id=org_id, name=f"{rng.choice(FIRST)} {rng.choice(LAST)}", company_name=f"{rng.choice(LAST)} {rng.choice(['Industries', 'Exports', 'Solutions'])}",
                    email=f"lead{i}@example.com", phone="9111111111", source=rng.choice(LEAD_SOURCES),
                    status="converted" if rng.random() < 0.25 else "new", assigned_to=rng.choice(people).id,
                    created_at=datetime.datetime.combine(today - datetime.timedelta(days=rng.randint(1, 300)), datetime.time(10))))
    for i in range(10):
        acc = rng.choice(accounts)
        db.add(Opportunity(org_id=org_id, account_id=acc.id, name=f"{acc.name} - {rng.choice(['Rollout', 'Renewal', 'Expansion'])}",
                           stage=rng.choice(["prospecting", "qualification", "proposal", "negotiation", "won", "lost"]),
                           value=rng.randint(40, 600) * 1000, expected_close=today + datetime.timedelta(days=rng.randint(-30, 120))))
    db.flush()

    # --- Sales history: orders -> invoices -> payments, with real ledger postings
    for back in range(months - 1, -1, -1):
        start = _month_start(today, back)
        for _ in range(rng.randint(7, 14)):
            order_date = start + datetime.timedelta(days=rng.randint(0, 27))
            if order_date > today:
                continue
            cust = rng.choice(customers)
            order = SalesOrder(org_id=org_id, customer_id=cust.id, order_date=order_date, status="fulfilled" if (today - order_date).days > 10 else "pending", total=0)
            db.add(order)
            db.flush()
            total = 0
            for p in rng.sample(products, rng.randint(1, 3)):
                qty = rng.randint(1, 8) if p.reorder_level > 0 else rng.randint(1, 3)
                db.add(SalesOrderItem(order_id=order.id, product_id=p.id, qty=qty, unit_price=p.unit_price))
                total += qty * float(p.unit_price)
            order.total = total
            inv_date = order_date + datetime.timedelta(days=rng.randint(0, 3))
            age = (today - inv_date).days
            paid = rng.random() < (0.85 if age > 60 else 0.55 if age > 30 else 0.25)
            inv = Invoice(org_id=org_id, order_id=order.id, customer_id=cust.id, amount=total,
                          due_date=inv_date + datetime.timedelta(days=30), status="paid" if paid else "unpaid",
                          created_at=datetime.datetime.combine(inv_date, datetime.time(11)))
            db.add(inv)
            db.flush()
            je = accounting.post_invoice_journal_entry(db, org_id, str(inv.id), total)
            je.date = inv_date
            if paid:
                pay_date = min(today, inv_date + datetime.timedelta(days=rng.randint(5, 40)))
                pay = Payment(org_id=org_id, invoice_id=inv.id, amount=total, method=rng.choice(["bank_transfer", "upi", "cheque"]), date=pay_date)
                db.add(pay)
                db.flush()
                pje = accounting.post_payment_journal_entry(db, org_id, str(pay.id), total)
                pje.date = pay_date

    # --- Payroll: the last 6 months, processed, with ledger postings
    for back in range(6, 0, -1):
        start = _month_start(today, back)
        run = PayrollRun(org_id=org_id, month=start.month, year=start.year, status="processed")
        db.add(run)
        db.flush()
        net_total = 0
        for e in active_employees:
            gross = float(e.salary)
            deductions = round(gross * 0.1, 2)
            net = gross - deductions
            db.add(Payslip(payroll_run_id=run.id, employee_id=e.id, gross=gross, deductions=deductions, net_pay=net))
            net_total += net
        je = accounting.post_payroll_journal_entry(db, org_id, str(run.id), net_total)
        je.date = _month_start(today, back - 1) - datetime.timedelta(days=1)

    # --- Procurement
    vendors = [Vendor(org_id=org_id, name=n, contact="vendor-contact", address="Industrial Area") for n in
               ("Precision Components Ltd", "Metro Electronics", "Surya Packaging", "Vertex Cables", "BlueLine Logistics")]
    db.add_all(vendors)
    db.flush()
    hardware = [p for p in products if p.reorder_level > 0]
    for back in range(months - 1, -1, -1):
        start = _month_start(today, back)
        for _ in range(rng.randint(2, 4)):
            od = start + datetime.timedelta(days=rng.randint(0, 27))
            if od > today:
                continue
            received = (today - od).days > 14 and rng.random() < 0.9
            po = PurchaseOrder(org_id=org_id, vendor_id=rng.choice(vendors).id, order_date=od, status="received" if received else "pending", approval_status="approved", total=0)
            db.add(po)
            db.flush()
            total = 0
            for p in rng.sample(hardware, rng.randint(1, 3)):
                qty = rng.randint(20, 120)
                unit = round(float(p.unit_price) * 0.6, 2)
                db.add(PurchaseOrderItem(po_id=po.id, product_id=p.id, qty=qty, unit_price=unit))
                total += qty * unit
            po.total = total
            if received:
                db.add(GoodsReceipt(org_id=org_id, po_id=po.id, received_date=od + datetime.timedelta(days=rng.randint(3, 12))))

    # --- Projects
    for name, status in (("Plant Monitoring Rollout", "active"), ("ERP Integration - Northwind", "active"),
                         ("Smart Meter Pilot", "completed"), ("Warehouse Automation", "on_hold")):
        proj = Project(org_id=org_id, name=name, client_account_id=rng.choice(accounts).id,
                       start_date=today - datetime.timedelta(days=rng.randint(60, 240)),
                       end_date=today + datetime.timedelta(days=rng.randint(-30, 120)), status=status)
        db.add(proj)
        db.flush()
        for t in range(rng.randint(3, 6)):
            task = Task(project_id=proj.id, title=f"{name.split()[0]} task {t + 1}", assigned_to=rng.choice(people).id,
                        due_date=today + datetime.timedelta(days=rng.randint(-20, 45)),
                        status=rng.choice(["todo", "in_progress", "done", "done"]), priority=rng.choice(["low", "medium", "high"]))
            db.add(task)
            db.flush()
            for _ in range(rng.randint(0, 3)):
                db.add(TimeLog(task_id=task.id, user_id=rng.choice(people).id, hours=rng.choice([1, 1.5, 2, 3, 4, 6]),
                               date=today - datetime.timedelta(days=rng.randint(0, 60))))

    db.commit()
    return org_id


def main():
    parser = argparse.ArgumentParser(description="Seed one synthetic demo organization.")
    parser.add_argument("--org-name", default="Acme Demo Co")
    parser.add_argument("--subdomain", required=True)
    parser.add_argument("--admin-email", default=None)
    parser.add_argument("--admin-password", default="DemoPass123!")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--months", type=int, default=12)
    args = parser.parse_args()
    args.admin_email = args.admin_email or f"admin@{args.subdomain}.example.com"

    from app.core.config import settings
    from app.core.database import SessionLocal

    url = make_url(settings.DATABASE_URL)
    print(f"\nThis will write a LARGE amount of synthetic data into:\n  host: {url.host}\n  database: {url.database}\n")
    typed = input(f"Type the database name ({url.database}) to confirm, anything else aborts: ").strip()
    if typed != url.database:
        print("Aborted. Nothing was written.")
        sys.exit(1)

    db = SessionLocal()
    try:
        org_id = seed_demo_org(db, org_name=args.org_name, subdomain=args.subdomain, admin_email=args.admin_email,
                               admin_password=args.admin_password, seed=args.seed, months=args.months)
    finally:
        db.close()
    print(f"\nDone. Organization id: {org_id}")
    print(f"Log in as:  {args.admin_email}  /  {args.admin_password}")


if __name__ == "__main__":
    main()
