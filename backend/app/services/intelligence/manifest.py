"""
THE CURATED MANIFEST - the single source of truth for what the AI may
see. Nothing exists to the AI unless it is listed here.

Design rules (each one a deliberate security or quality decision):

1. EXPLICIT ALLOW-LIST, never "everything except". A table or column
   added to the ERP tomorrow is invisible to the AI until someone
   consciously adds it here. Widening access later is easy; taking back
   something that already leaked is not.

2. NO SECRETS, EVER. Not present anywhere below: password_hash, every
   *_token_hash / *_token_expires column, storage keys, audit logs,
   roles/permissions, notifications, report subscriptions. The AI
   cannot be tricked into revealing what it was never told exists, and
   the database role it queries as has no grant on any of it either
   (see role_setup.py) - two independent reasons, not one.

3. NO INDIVIDUAL CONTACT PII. Email and phone columns are excluded from
   contacts and leads, and `vendors.contact` from vendors. Analytics
   questions ("leads per source") never need them. Company-level data
   (company addresses, GST numbers) IS included.

4. NO org_id COLUMN IS EXPOSED. Every view is already filtered to the
   caller's organization inside the database (see the migration). The
   model is told never to filter by organization, which removes a whole
   class of hallucinated "WHERE org_id = '<made up uuid>'" queries.

5. SALARY DATA IS IN SCOPE (employees.salary, payslips). This is a
   deliberate consequence of "anyone with the intelligence.view
   permission may ask anything in the manifest" (Option A). It means
   holders of that permission can read payroll through the AI even if
   their role could not open the HR module. Grant it accordingly, until
   per-table permission checks (Option B) exist.

If you change anything here, you MUST also add a migration that alters
the matching view, and re-run scripts/setup_uil_role.py so grants line
up. tests/test_uil_manifest.py fails if this file and the database's
actual views ever disagree.
"""
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Column:
    name: str
    type: str  # uuid | text | numeric | integer | date | timestamp | time
    note: str = ""


@dataclass(frozen=True)
class View:
    name: str
    module: str
    description: str
    columns: tuple
    base: str                 # the real table this view reads
    via: tuple | None = None  # (parent_table, fk_column_on_this_table) when the table has no org_id of its own
    custom_sql: str | None = None  # only for views needing a special join (users)
    # WHO MAY READ IT. Filled in from the ACCESS table further down (not inline,
    # so a reviewer can audit every rule in one place).
    access: tuple = ()        # RBAC module names; holding `view` on ANY ONE of them opens this view
    restricted: bool = False  # True = ALSO needs intelligence.approve (salary / payroll)


def _cols(*specs):
    out = []
    for spec in specs:
        parts = spec.split(":", 2)
        out.append(Column(parts[0], parts[1], parts[2] if len(parts) > 2 else ""))
    return tuple(out)


_RAW_VIEWS: tuple = (
    # ----------------------------------------------------------- CRM
    View("crm_accounts", "CRM", "Companies the business deals with (prospects and clients).",
         _cols("id:uuid", "name:text", "industry:text", "address:text", "created_at:timestamp"),
         base="crm_accounts"),
    View("crm_contacts", "CRM", "People at those companies (names only; contact details are not available).",
         _cols("id:uuid", "account_id:uuid:-> crm_accounts.id", "name:text", "created_at:timestamp"),
         base="crm_contacts"),
    View("crm_leads", "CRM", "Sales leads not yet converted to opportunities.",
         _cols("id:uuid", "name:text", "company_name:text",
               "source:text:free text such as Website, Referral, Cold Call; use ILIKE",
               "status:text:'new' by default; 'converted' once turned into an opportunity",
               "assigned_to:uuid:-> users.id (the owning salesperson)", "created_at:timestamp"),
         base="crm_leads"),
    View("crm_opportunities", "CRM", "Potential deals in the sales pipeline.",
         _cols("id:uuid", "account_id:uuid:-> crm_accounts.id", "contact_id:uuid:-> crm_contacts.id", "name:text",
               "stage:text:pipeline stage, e.g. prospecting; use ILIKE",
               "value:numeric:expected deal value", "expected_close:date", "created_at:timestamp"),
         base="crm_opportunities"),

    # --------------------------------------------------------- SALES
    View("products", "Sales", "Products and services the business sells.",
         _cols("id:uuid", "name:text", "unit_price:numeric", "sku:text", "category_id:uuid:-> product_categories.id",
               "reorder_level:integer:0 means no reorder alert; otherwise low stock = on-hand quantity <= this",
               "created_at:timestamp"),
         base="products"),
    View("customers", "Sales", "Customers that have been or can be invoiced.",
         _cols("id:uuid", "account_id:uuid:-> crm_accounts.id", "name:text", "billing_address:text",
               "gst_number:text:tax registration number of the customer", "created_at:timestamp"),
         base="customers"),
    View("quotations", "Sales", "Price quotes sent to customers.",
         _cols("id:uuid", "customer_id:uuid:-> customers.id", "opportunity_id:uuid:-> crm_opportunities.id",
               "total:numeric", "status:text:'draft', 'sent', 'accepted' or 'rejected'", "created_at:timestamp"),
         base="quotations"),
    View("quotation_items", "Sales", "Line items of a quotation.",
         _cols("id:uuid", "quotation_id:uuid:-> quotations.id", "product_id:uuid:-> products.id",
               "qty:integer", "unit_price:numeric"),
         base="quotation_items", via=("quotations", "quotation_id")),
    View("sales_orders", "Sales", "Confirmed customer orders.",
         _cols("id:uuid", "customer_id:uuid:-> customers.id", "quotation_id:uuid:-> quotations.id",
               "order_date:date", "status:text:'pending', 'fulfilled' or 'cancelled'", "total:numeric"),
         base="sales_orders"),
    View("sales_order_items", "Sales", "Line items of a sales order. Revenue by product comes from here.",
         _cols("id:uuid", "order_id:uuid:-> sales_orders.id", "product_id:uuid:-> products.id",
               "qty:integer", "unit_price:numeric:line value = qty * unit_price"),
         base="sales_order_items", via=("sales_orders", "order_id")),
    View("invoices", "Sales", "Bills raised against sales orders.",
         _cols("id:uuid", "order_id:uuid:-> sales_orders.id", "customer_id:uuid:-> customers.id",
               "amount:numeric:invoice total",
               "due_date:date",
               "status:text:ONLY 'unpaid' or 'paid' are stored. 'overdue' is NOT a stored value: "
               "overdue means status = 'unpaid' AND due_date < CURRENT_DATE",
               "created_at:timestamp:when the invoice was raised"),
         base="invoices"),

    # ------------------------------------------------------- FINANCE
    View("chart_of_accounts", "Finance", "The ledger accounts.",
         _cols("id:uuid", "code:text:e.g. 1000, 4000", "name:text:e.g. Cash, Sales Revenue",
               "account_type:text:'asset', 'liability', 'equity', 'revenue' or 'expense'"),
         base="chart_of_accounts"),
    View("journal_entries", "Finance", "Double-entry ledger postings (one per invoice, payment, payroll run).",
         _cols("id:uuid", "date:date:the posting date; use this for revenue/expense by month",
               "reference:text:e.g. INV-<id>", "description:text"),
         base="journal_entries"),
    View("journal_lines", "Finance", "Debit and credit lines of a ledger posting.",
         _cols("id:uuid", "journal_entry_id:uuid:-> journal_entries.id", "account_id:uuid:-> chart_of_accounts.id",
               "debit:numeric", "credit:numeric"),
         base="journal_lines", via=("journal_entries", "journal_entry_id")),
    View("payments", "Finance", "Money received against invoices.",
         _cols("id:uuid", "invoice_id:uuid:-> invoices.id", "amount:numeric",
               "method:text:e.g. bank_transfer", "date:date:when cash was received", "created_at:timestamp"),
         base="payments"),

    # ------------------------------------------------------ INVENTORY
    View("product_categories", "Inventory", "Product groupings.",
         _cols("id:uuid", "name:text"), base="product_categories"),
    View("warehouses", "Inventory", "Places stock is held.",
         _cols("id:uuid", "name:text", "location:text"), base="warehouses"),
    View("stock_levels", "Inventory", "CURRENT on-hand quantity of a product in a warehouse. Sum across warehouses for a product total.",
         _cols("id:uuid", "product_id:uuid:-> products.id", "warehouse_id:uuid:-> warehouses.id", "quantity:integer"),
         base="stock_levels", via=("products", "product_id")),
    View("stock_movements", "Inventory", "History of stock going in or out.",
         _cols("id:uuid", "product_id:uuid:-> products.id", "warehouse_id:uuid:-> warehouses.id",
               "movement_type:text:'in' or 'out'", "qty:integer",
               "ref_type:text:'purchase_order' or 'sales_order'", "ref_id:uuid", "date:date", "created_at:timestamp"),
         base="stock_movements"),

    # ------------------------------------------------------------- HR
    View("departments", "HR", "Company departments.",
         _cols("id:uuid", "name:text"), base="departments"),
    View("employees", "HR", "Employees: names, designations and departments (pay is NOT here; see employee_pay).",
         _cols("id:uuid", "name:text", "designation:text", "department_id:uuid:-> departments.id",
               "joining_date:date", "status:text:'active' or 'inactive'; usually filter to 'active'"),
         base="employees"),
    View("employee_pay", "HR", "RESTRICTED. Each employee's monthly salary.",
         _cols("employee_id:uuid:-> employees.id", "salary:numeric:monthly salary"),
         base="employees",
         custom_sql="SELECT id AS employee_id, salary FROM public.employees WHERE org_id = uil.current_org()"),
    View("attendance", "HR", "Daily attendance records.",
         _cols("id:uuid", "employee_id:uuid:-> employees.id", "date:date",
               "status:text:'present', 'absent', 'half_day' or 'leave'", "check_in:time", "check_out:time"),
         base="attendance", via=("employees", "employee_id")),
    View("leave_requests", "HR", "Employee leave applications.",
         _cols("id:uuid", "employee_id:uuid:-> employees.id", "leave_type:text:e.g. Sick, Casual, Earned",
               "start_date:date", "end_date:date", "status:text:'pending', 'approved' or 'rejected'",
               "created_at:timestamp"),
         base="leave_requests", via=("employees", "employee_id")),
    View("payroll_runs", "HR", "RESTRICTED. Monthly payroll batches.",
         _cols("id:uuid", "month:integer:1-12", "year:integer", "status:text:'draft' or 'processed'"),
         base="payroll_runs"),
    View("payslips", "HR", "RESTRICTED. Per-employee pay for a payroll run.",
         _cols("id:uuid", "payroll_run_id:uuid:-> payroll_runs.id", "employee_id:uuid:-> employees.id",
               "gross:numeric", "deductions:numeric", "net_pay:numeric"),
         base="payslips", via=("payroll_runs", "payroll_run_id")),

    # ---------------------------------------------------- PROCUREMENT
    View("vendors", "Procurement", "Suppliers (contact details are not available).",
         _cols("id:uuid", "name:text", "address:text", "created_at:timestamp"), base="vendors"),
    View("purchase_orders", "Procurement", "Orders placed with vendors.",
         _cols("id:uuid", "vendor_id:uuid:-> vendors.id", "order_date:date",
               "status:text:'pending' or 'received'", "total:numeric"),
         base="purchase_orders"),
    View("purchase_order_items", "Procurement", "Line items of a purchase order.",
         _cols("id:uuid", "po_id:uuid:-> purchase_orders.id", "product_id:uuid:-> products.id",
               "qty:integer", "unit_price:numeric"),
         base="purchase_order_items", via=("purchase_orders", "po_id")),
    View("goods_receipts", "Procurement", "Records of goods received against purchase orders.",
         _cols("id:uuid", "po_id:uuid:-> purchase_orders.id", "received_date:date"),
         base="goods_receipts"),

    # -------------------------------------------------------- PROJECTS
    View("projects", "Projects", "Client or internal projects.",
         _cols("id:uuid", "name:text", "client_account_id:uuid:-> crm_accounts.id", "start_date:date",
               "end_date:date", "status:text:'active', 'completed' or 'on_hold'"),
         base="projects"),
    View("tasks", "Projects", "Tasks inside projects.",
         _cols("id:uuid", "project_id:uuid:-> projects.id", "title:text", "assigned_to:uuid:-> users.id",
               "due_date:date", "status:text:'todo', 'in_progress' or 'done'",
               "priority:text:'low', 'medium' or 'high'"),
         base="tasks", via=("projects", "project_id")),
    View("time_logs", "Projects", "Hours people logged against tasks.",
         _cols("id:uuid", "task_id:uuid:-> tasks.id", "user_id:uuid:-> users.id", "hours:numeric",
               "date:date", "created_at:timestamp"),
         base="time_logs", via=("users", "user_id")),

    # ------------------------------------------------------------ CORE
    View("users", "Core", "People who log in to the ERP (names, roles and status only).",
         _cols("id:uuid", "name:text", "status:text:'active', 'disabled' or 'invited'",
               "created_at:timestamp", "role_name:text:the user's role, e.g. Admin"),
         base="users",
         custom_sql=(
             "SELECT u.id, u.name, u.status, u.created_at, r.name AS role_name "
             "FROM public.users u LEFT JOIN public.roles r ON r.id = u.role_id "
             "WHERE u.org_id = uil.current_org()"
         )),
)

# ---------------------------------------------------------------------------
# WHO MAY READ WHAT: the one table to audit.
#
#   view name -> (modules, restricted)
#
# RULE: a user may read a view if they hold `view` on AT LEAST ONE of its
# modules. The modules listed are the ones whose normal screens already show
# this data, so Ask Data never shows anyone more than the app itself would.
# (products appears under Sales, Inventory and Procurement because stock and
# purchasing screens show product names; an inventory-only user must still be
# able to ask "which products are low on stock".)
#
# restricted=True means the view ALSO needs `approve` on the Ask Data
# permission. approve is an ADDITIONAL gate, never a substitute: someone with
# approve but no HR access still cannot read salaries.
#
# Deliberately NOT restricted: total payroll EXPENSE, which Finance users already
# see on their normal Finance report (it is a ledger line). Per-person pay is.
# ---------------------------------------------------------------------------
ACCESS: dict = {
    "crm_accounts": (("crm", "sales", "projects"), False),
    "crm_contacts": (("crm",), False),
    "crm_leads": (("crm",), False),
    "crm_opportunities": (("crm",), False),
    "products": (("sales", "inventory", "procurement"), False),
    "customers": (("sales", "finance"), False),
    "quotations": (("sales",), False),
    "quotation_items": (("sales",), False),
    "sales_orders": (("sales",), False),
    "sales_order_items": (("sales",), False),
    "invoices": (("sales", "finance"), False),
    "chart_of_accounts": (("finance",), False),
    "journal_entries": (("finance",), False),
    "journal_lines": (("finance",), False),
    "payments": (("finance",), False),
    "product_categories": (("inventory", "sales"), False),
    "warehouses": (("inventory",), False),
    "stock_levels": (("inventory",), False),
    "stock_movements": (("inventory",), False),
    "departments": (("hr",), False),
    "employees": (("hr",), False),
    "employee_pay": (("hr",), True),
    "attendance": (("hr",), False),
    "leave_requests": (("hr",), False),
    "payroll_runs": (("hr",), True),
    "payslips": (("hr",), True),
    "vendors": (("procurement",), False),
    "purchase_orders": (("procurement",), False),
    "purchase_order_items": (("procurement",), False),
    "goods_receipts": (("procurement",), False),
    "projects": (("projects",), False),
    "tasks": (("projects",), False),
    "time_logs": (("projects",), False),
    "users": (("core", "crm", "projects", "hr"), False),
}

_missing = {v.name for v in _RAW_VIEWS} - set(ACCESS)
_unknown = set(ACCESS) - {v.name for v in _RAW_VIEWS}
if _missing or _unknown:  # fail at import, never silently default to "open"
    raise RuntimeError(f"ACCESS table out of step with views. No rule for: {sorted(_missing)}; rule for unknown view: {sorted(_unknown)}")

VIEWS: tuple = tuple(
    replace(v, access=ACCESS[v.name][0], restricted=ACCESS[v.name][1]) for v in _RAW_VIEWS
)

VIEWS_BY_NAME = {v.name: v for v in VIEWS}
ALLOWED_VIEW_NAMES = frozenset(VIEWS_BY_NAME)
ALL_MODULES = frozenset(m for v in VIEWS for m in v.access)

MODULE_LABELS = {
    "crm": "CRM", "sales": "Sales", "finance": "Finance", "inventory": "Inventory", "hr": "HR",
    "procurement": "Procurement", "projects": "Projects", "core": "Users & Roles",
}


# Each definition is tagged with the views it depends on, so a user is only ever
# TAUGHT definitions for data they can actually read (a basic user's prompt never
# mentions payroll at all).
GLOSSARY_ENTRIES: tuple = (
    (frozenset(), "Money columns are numeric in the organization's own currency; do not invent a currency symbol."),
    (frozenset({"journal_lines", "chart_of_accounts"}),
     "Revenue = SUM(journal_lines.credit) for accounts where chart_of_accounts.account_type = 'revenue'. "
     "Revenue by month: join journal_lines -> journal_entries (use journal_entries.date) and chart_of_accounts."),
    (frozenset({"journal_lines", "chart_of_accounts"}),
     "Expenses = SUM(journal_lines.debit) for accounts where account_type = 'expense'. Net profit = revenue minus expenses."),
    (frozenset({"invoices"}),
     "\"Invoiced\" / \"billed\" amounts = SUM(invoices.amount). Outstanding receivables = invoices with status = 'unpaid'."),
    (frozenset({"payments"}), "\"Cash received\" / \"collected\" = SUM(payments.amount)."),
    (frozenset({"invoices"}),
     "Overdue invoices = status = 'unpaid' AND due_date < CURRENT_DATE. ('overdue' is never stored as a status.)"),
    (frozenset({"stock_levels"}), "Stock on hand for a product = SUM(stock_levels.quantity) across warehouses."),
    (frozenset({"products", "stock_levels"}),
     "Low stock = product reorder_level > 0 AND on-hand quantity <= reorder_level."),
    (frozenset({"employees"}), "Headcount = employees with status = 'active'."),
    (frozenset({"employee_pay"}), "An employee's salary is employee_pay.salary (monthly); join employee_pay.employee_id = employees.id."),
    (frozenset({"payslips", "payroll_runs"}),
     "Payroll cost for a period = SUM(payslips.net_pay) joined to payroll_runs (month, year)."),
)


def render_glossary(allowed=None) -> str:
    lines = [text for needs, text in GLOSSARY_ENTRIES if allowed is None or needs <= allowed]
    return "BUSINESS DEFINITIONS (use these exactly; they match the ERP's own reports):\n" + "\n".join(f"- {l}" for l in lines) + "\n"


RULES = """\
RULES:
1. Write exactly ONE PostgreSQL SELECT statement (a WITH ... SELECT is fine). Nothing else.
2. Use ONLY the views listed under VIEWS. Never reference any other table or schema.
3. Every view is already limited to the current organization. NEVER filter by organization and never mention org_id.
4. Match text with ILIKE and wildcards (e.g. name ILIKE '%acme%'), because stored spellings vary.
5. Use only these functions: SUM, COUNT, AVG, MIN, MAX, ROUND, COALESCE, NULLIF, GREATEST, LEAST, ABS, CEIL, FLOOR,
   UPPER, LOWER, LENGTH, SUBSTRING, TRIM, CONCAT, STRING_AGG, DATE_TRUNC, EXTRACT, DATE_PART, TO_CHAR, TO_DATE, AGE,
   MAKE_DATE, CURRENT_DATE, NOW, ROW_NUMBER, RANK, LAG, LEAD, STDDEV, VARIANCE, PERCENTILE_CONT.
6. Give every computed column a readable alias.
7. Prefer returning the few columns that actually answer the question.
"""

# Shown ONLY to users who actually have locked views (an admin's prompt never mentions any of this).
DENIED_RULE = (
    "If the question can only be answered with one of those, do not write SQL. "
    "Reply with exactly:  DENIED: <view name>"
)

# (question, sql, views the sql reads). tests/test_uil_manifest.py runs EVERY example through the
# validator and the real database, and checks the declared views match what the SQL really reads,
# so these can never silently rot.
EXAMPLES: tuple = (
    ("What is our total revenue?",
     "SELECT COALESCE(SUM(jl.credit), 0) AS total_revenue FROM journal_lines jl "
     "JOIN chart_of_accounts a ON a.id = jl.account_id WHERE a.account_type = 'revenue'",
     frozenset({"journal_lines", "chart_of_accounts"})),
    ("Show revenue by month for the last 6 months",
     "SELECT date_trunc('month', je.date)::date AS month, SUM(jl.credit) AS revenue FROM journal_lines jl "
     "JOIN journal_entries je ON je.id = jl.journal_entry_id JOIN chart_of_accounts a ON a.id = jl.account_id "
     "WHERE a.account_type = 'revenue' AND je.date >= date_trunc('month', CURRENT_DATE) - INTERVAL '5 months' "
     "GROUP BY 1 ORDER BY 1",
     frozenset({"journal_lines", "journal_entries", "chart_of_accounts"})),
    ("Which invoices are overdue?",
     "SELECT i.id, c.name AS customer, i.amount, i.due_date, CURRENT_DATE - i.due_date AS days_overdue "
     "FROM invoices i JOIN customers c ON c.id = i.customer_id "
     "WHERE i.status = 'unpaid' AND i.due_date < CURRENT_DATE ORDER BY i.due_date",
     frozenset({"invoices", "customers"})),
    ("Who are our top 5 customers by invoiced amount?",
     "SELECT c.name AS customer, SUM(i.amount) AS total_invoiced FROM invoices i "
     "JOIN customers c ON c.id = i.customer_id GROUP BY c.name ORDER BY total_invoiced DESC LIMIT 5",
     frozenset({"invoices", "customers"})),
    ("Which products are low on stock?",
     "SELECT p.name, p.sku, COALESCE(SUM(s.quantity), 0) AS on_hand, p.reorder_level FROM products p "
     "LEFT JOIN stock_levels s ON s.product_id = p.id WHERE p.reorder_level > 0 "
     "GROUP BY p.id, p.name, p.sku, p.reorder_level HAVING COALESCE(SUM(s.quantity), 0) <= p.reorder_level",
     frozenset({"products", "stock_levels"})),
    ("How many active employees are in each department?",
     "SELECT COALESCE(d.name, 'Unassigned') AS department, COUNT(*) AS employees FROM employees e "
     "LEFT JOIN departments d ON d.id = e.department_id WHERE e.status = 'active' GROUP BY 1 ORDER BY 2 DESC",
     frozenset({"employees", "departments"})),
    ("How many leads came from each source?",
     "SELECT COALESCE(source, 'Unknown') AS source, COUNT(*) AS leads FROM crm_leads GROUP BY 1 ORDER BY 2 DESC",
     frozenset({"crm_leads"})),
    ("What was our total payroll cost for March 2026?",
     "SELECT SUM(ps.net_pay) AS total_net_pay FROM payslips ps "
     "JOIN payroll_runs pr ON pr.id = ps.payroll_run_id WHERE pr.year = 2026 AND pr.month = 3",
     frozenset({"payslips", "payroll_runs"})),
    ("What is the average salary in each department?",
     "SELECT d.name AS department, ROUND(AVG(p.salary), 2) AS avg_salary FROM employee_pay p "
     "JOIN employees e ON e.id = p.employee_id JOIN departments d ON d.id = e.department_id "
     "WHERE e.status = 'active' GROUP BY d.name ORDER BY 2 DESC",
     frozenset({"employee_pay", "employees", "departments"})),
)


def _visible(allowed):
    return [v for v in VIEWS if allowed is None or v.name in allowed]


def render_schema_description(allowed=None) -> str:
    """What the AI is told exists. Built only from views the caller may read (all, when allowed is None)."""
    lines = []
    current_module = None
    for v in _visible(allowed):
        if v.module != current_module:
            current_module = v.module
            lines.append(f"\n## {current_module}")
        lines.append(f"{v.name}  -- {v.description}")
        for c in v.columns:
            lines.append(f"    {c.name} {c.type}" + (f"  -- {c.note}" if c.note else ""))
    return "\n".join(lines).strip()


def render_unavailable(allowed) -> str:
    """Names and one-line descriptions ONLY of views this user cannot read (no columns), so the model can say DENIED."""
    hidden = [v for v in VIEWS if allowed is not None and v.name not in allowed]
    if not hidden:
        return ""
    return "\n".join(f"{v.name}  -- {v.description}" for v in hidden)


def render_examples(allowed=None) -> str:
    shown = [(q, s) for q, s, needs in EXAMPLES if allowed is None or needs <= allowed]
    return "\n\n".join(f"Question: {q}\nSQL: {s}" for q, s in shown)


def view_summary(allowed=None) -> list[dict]:
    """Lightweight, front-end friendly description of what can be asked about."""
    return [{"name": v.name, "module": v.module, "description": v.description} for v in _visible(allowed)]


def example_questions(allowed=None) -> list[str]:
    return [q for q, _s, needs in EXAMPLES if allowed is None or needs <= allowed]
