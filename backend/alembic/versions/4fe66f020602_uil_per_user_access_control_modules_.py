"""uil per user access control modules restricted tier

Adds PER-USER access control to the Unified Intelligence Layer, enforced by the
DATABASE ITSELF (not only by application code):

  uil.session_context   gains `modules` (the RBAC modules the asking user holds
                        `view` on) and `restricted` (holds intelligence.approve).
                        Still writable only by the privileged application login.
  uil.can_read(req, r)  true only if this connection's registered modules overlap
                        `req` AND (the view is not restricted OR the user is
                        approved). No registration => false => zero rows
                        (fail closed, same as the tenant check).
  every uil.<view>      rebuilt so its WHERE clause also calls can_read().

So even if the SQL validator and the prompts both had a bug, a user without the
HR module (or without `approve`) gets ZERO rows from salary and payroll views.

Also splits salary out of `employees` into a new restricted `employee_pay` view:
RBAC here works per module, with no per-field control, so a salary column inside
a general HR view could not be restricted on its own.

The two view lists below are FROZEN copies (old = before this migration, new =
after). Migrations must never import application code that may change later.
tests/test_uil_manifest.py fails if the database and manifest drift apart.

Re-granting: dropping a view drops its grants, so this migration re-grants SELECT
(and EXECUTE on can_read) to uil_readonly IF that role already exists, so there is
no window where the AI cannot query. It holds no secret, unlike creating the role.

Revision ID: 4fe66f020602
Revises: 533798133a8d
"""
from typing import Sequence, Union

from alembic import op

revision: str = "4fe66f020602"
down_revision: Union[str, None] = "533798133a8d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# BEFORE this migration: (name, base, cols, via, custom_sql)
OLD_VIEW_SPEC = [
    ('crm_accounts', 'crm_accounts', ['id', 'name', 'industry', 'address', 'created_at'], None, None),
    ('crm_contacts', 'crm_contacts', ['id', 'account_id', 'name', 'created_at'], None, None),
    ('crm_leads', 'crm_leads', ['id', 'name', 'company_name', 'source', 'status', 'assigned_to', 'created_at'], None, None),
    ('crm_opportunities', 'crm_opportunities', ['id', 'account_id', 'contact_id', 'name', 'stage', 'value', 'expected_close', 'created_at'], None, None),
    ('products', 'products', ['id', 'name', 'unit_price', 'sku', 'category_id', 'reorder_level', 'created_at'], None, None),
    ('customers', 'customers', ['id', 'account_id', 'name', 'billing_address', 'gst_number', 'created_at'], None, None),
    ('quotations', 'quotations', ['id', 'customer_id', 'opportunity_id', 'total', 'status', 'created_at'], None, None),
    ('quotation_items', 'quotation_items', ['id', 'quotation_id', 'product_id', 'qty', 'unit_price'], ('quotations', 'quotation_id'), None),
    ('sales_orders', 'sales_orders', ['id', 'customer_id', 'quotation_id', 'order_date', 'status', 'total'], None, None),
    ('sales_order_items', 'sales_order_items', ['id', 'order_id', 'product_id', 'qty', 'unit_price'], ('sales_orders', 'order_id'), None),
    ('invoices', 'invoices', ['id', 'order_id', 'customer_id', 'amount', 'due_date', 'status', 'created_at'], None, None),
    ('chart_of_accounts', 'chart_of_accounts', ['id', 'code', 'name', 'account_type'], None, None),
    ('journal_entries', 'journal_entries', ['id', 'date', 'reference', 'description'], None, None),
    ('journal_lines', 'journal_lines', ['id', 'journal_entry_id', 'account_id', 'debit', 'credit'], ('journal_entries', 'journal_entry_id'), None),
    ('payments', 'payments', ['id', 'invoice_id', 'amount', 'method', 'date', 'created_at'], None, None),
    ('product_categories', 'product_categories', ['id', 'name'], None, None),
    ('warehouses', 'warehouses', ['id', 'name', 'location'], None, None),
    ('stock_levels', 'stock_levels', ['id', 'product_id', 'warehouse_id', 'quantity'], ('products', 'product_id'), None),
    ('stock_movements', 'stock_movements', ['id', 'product_id', 'warehouse_id', 'movement_type', 'qty', 'ref_type', 'ref_id', 'date', 'created_at'], None, None),
    ('departments', 'departments', ['id', 'name'], None, None),
    ('employees', 'employees', ['id', 'name', 'designation', 'department_id', 'joining_date', 'salary', 'status'], None, None),
    ('attendance', 'attendance', ['id', 'employee_id', 'date', 'status', 'check_in', 'check_out'], ('employees', 'employee_id'), None),
    ('leave_requests', 'leave_requests', ['id', 'employee_id', 'leave_type', 'start_date', 'end_date', 'status', 'created_at'], ('employees', 'employee_id'), None),
    ('payroll_runs', 'payroll_runs', ['id', 'month', 'year', 'status'], None, None),
    ('payslips', 'payslips', ['id', 'payroll_run_id', 'employee_id', 'gross', 'deductions', 'net_pay'], ('payroll_runs', 'payroll_run_id'), None),
    ('vendors', 'vendors', ['id', 'name', 'address', 'created_at'], None, None),
    ('purchase_orders', 'purchase_orders', ['id', 'vendor_id', 'order_date', 'status', 'total'], None, None),
    ('purchase_order_items', 'purchase_order_items', ['id', 'po_id', 'product_id', 'qty', 'unit_price'], ('purchase_orders', 'po_id'), None),
    ('goods_receipts', 'goods_receipts', ['id', 'po_id', 'received_date'], None, None),
    ('projects', 'projects', ['id', 'name', 'client_account_id', 'start_date', 'end_date', 'status'], None, None),
    ('tasks', 'tasks', ['id', 'project_id', 'title', 'assigned_to', 'due_date', 'status', 'priority'], ('projects', 'project_id'), None),
    ('time_logs', 'time_logs', ['id', 'task_id', 'user_id', 'hours', 'date', 'created_at'], ('users', 'user_id'), None),
    ('users', 'users', ['id', 'name', 'status', 'created_at', 'role_name'], None, 'SELECT u.id, u.name, u.status, u.created_at, r.name AS role_name FROM public.users u LEFT JOIN public.roles r ON r.id = u.role_id WHERE u.org_id = uil.current_org()'),
]

# AFTER: (name, base, cols, via, custom_sql, modules, restricted)
NEW_VIEW_SPEC = [
    ('crm_accounts', 'crm_accounts', ['id', 'name', 'industry', 'address', 'created_at'], None, None, ['crm', 'sales', 'projects'], False),
    ('crm_contacts', 'crm_contacts', ['id', 'account_id', 'name', 'created_at'], None, None, ['crm'], False),
    ('crm_leads', 'crm_leads', ['id', 'name', 'company_name', 'source', 'status', 'assigned_to', 'created_at'], None, None, ['crm'], False),
    ('crm_opportunities', 'crm_opportunities', ['id', 'account_id', 'contact_id', 'name', 'stage', 'value', 'expected_close', 'created_at'], None, None, ['crm'], False),
    ('products', 'products', ['id', 'name', 'unit_price', 'sku', 'category_id', 'reorder_level', 'created_at'], None, None, ['sales', 'inventory', 'procurement'], False),
    ('customers', 'customers', ['id', 'account_id', 'name', 'billing_address', 'gst_number', 'created_at'], None, None, ['sales', 'finance'], False),
    ('quotations', 'quotations', ['id', 'customer_id', 'opportunity_id', 'total', 'status', 'created_at'], None, None, ['sales'], False),
    ('quotation_items', 'quotation_items', ['id', 'quotation_id', 'product_id', 'qty', 'unit_price'], ('quotations', 'quotation_id'), None, ['sales'], False),
    ('sales_orders', 'sales_orders', ['id', 'customer_id', 'quotation_id', 'order_date', 'status', 'total'], None, None, ['sales'], False),
    ('sales_order_items', 'sales_order_items', ['id', 'order_id', 'product_id', 'qty', 'unit_price'], ('sales_orders', 'order_id'), None, ['sales'], False),
    ('invoices', 'invoices', ['id', 'order_id', 'customer_id', 'amount', 'due_date', 'status', 'created_at'], None, None, ['sales', 'finance'], False),
    ('chart_of_accounts', 'chart_of_accounts', ['id', 'code', 'name', 'account_type'], None, None, ['finance'], False),
    ('journal_entries', 'journal_entries', ['id', 'date', 'reference', 'description'], None, None, ['finance'], False),
    ('journal_lines', 'journal_lines', ['id', 'journal_entry_id', 'account_id', 'debit', 'credit'], ('journal_entries', 'journal_entry_id'), None, ['finance'], False),
    ('payments', 'payments', ['id', 'invoice_id', 'amount', 'method', 'date', 'created_at'], None, None, ['finance'], False),
    ('product_categories', 'product_categories', ['id', 'name'], None, None, ['inventory', 'sales'], False),
    ('warehouses', 'warehouses', ['id', 'name', 'location'], None, None, ['inventory'], False),
    ('stock_levels', 'stock_levels', ['id', 'product_id', 'warehouse_id', 'quantity'], ('products', 'product_id'), None, ['inventory'], False),
    ('stock_movements', 'stock_movements', ['id', 'product_id', 'warehouse_id', 'movement_type', 'qty', 'ref_type', 'ref_id', 'date', 'created_at'], None, None, ['inventory'], False),
    ('departments', 'departments', ['id', 'name'], None, None, ['hr'], False),
    ('employees', 'employees', ['id', 'name', 'designation', 'department_id', 'joining_date', 'status'], None, None, ['hr'], False),
    ('employee_pay', 'employees', ['employee_id', 'salary'], None, 'SELECT id AS employee_id, salary FROM public.employees WHERE org_id = uil.current_org()', ['hr'], True),
    ('attendance', 'attendance', ['id', 'employee_id', 'date', 'status', 'check_in', 'check_out'], ('employees', 'employee_id'), None, ['hr'], False),
    ('leave_requests', 'leave_requests', ['id', 'employee_id', 'leave_type', 'start_date', 'end_date', 'status', 'created_at'], ('employees', 'employee_id'), None, ['hr'], False),
    ('payroll_runs', 'payroll_runs', ['id', 'month', 'year', 'status'], None, None, ['hr'], True),
    ('payslips', 'payslips', ['id', 'payroll_run_id', 'employee_id', 'gross', 'deductions', 'net_pay'], ('payroll_runs', 'payroll_run_id'), None, ['hr'], True),
    ('vendors', 'vendors', ['id', 'name', 'address', 'created_at'], None, None, ['procurement'], False),
    ('purchase_orders', 'purchase_orders', ['id', 'vendor_id', 'order_date', 'status', 'total'], None, None, ['procurement'], False),
    ('purchase_order_items', 'purchase_order_items', ['id', 'po_id', 'product_id', 'qty', 'unit_price'], ('purchase_orders', 'po_id'), None, ['procurement'], False),
    ('goods_receipts', 'goods_receipts', ['id', 'po_id', 'received_date'], None, None, ['procurement'], False),
    ('projects', 'projects', ['id', 'name', 'client_account_id', 'start_date', 'end_date', 'status'], None, None, ['projects'], False),
    ('tasks', 'tasks', ['id', 'project_id', 'title', 'assigned_to', 'due_date', 'status', 'priority'], ('projects', 'project_id'), None, ['projects'], False),
    ('time_logs', 'time_logs', ['id', 'task_id', 'user_id', 'hours', 'date', 'created_at'], ('users', 'user_id'), None, ['projects'], False),
    ('users', 'users', ['id', 'name', 'status', 'created_at', 'role_name'], None, 'SELECT u.id, u.name, u.status, u.created_at, r.name AS role_name FROM public.users u LEFT JOIN public.roles r ON r.id = u.role_id WHERE u.org_id = uil.current_org()', ['core', 'crm', 'projects', 'hr'], False),
]


def _select_sql(base, cols, via, custom_sql):
    if custom_sql:
        return custom_sql
    if via is None:
        return "SELECT %s FROM public.%s WHERE org_id = uil.current_org()" % (", ".join(cols), base)
    parent, fk = via
    return (
        "SELECT %s FROM public.%s c JOIN public.%s p ON p.id = c.%s WHERE p.org_id = uil.current_org()"
    ) % (", ".join("c." + col for col in cols), base, parent, fk)


def _new_view_sql(name, base, cols, via, custom_sql, modules, restricted):
    required = "ARRAY[" + ", ".join("'%s'" % m for m in modules) + "]"
    select = _select_sql(base, cols, via, custom_sql)
    return "CREATE VIEW uil.%s WITH (security_barrier = true) AS %s AND uil.can_read(%s, %s)" % (
        name, select, required, "true" if restricted else "false")


def _old_view_sql(name, base, cols, via, custom_sql):
    return "CREATE VIEW uil.%s WITH (security_barrier = true) AS %s" % (name, _select_sql(base, cols, via, custom_sql))


def _regrant(names, with_can_read):
    """Re-grant to the read-only login IF it exists (a missing role is fine: setup_uil_role.py grants later)."""
    stmts = []
    if with_can_read:
        stmts.append("GRANT EXECUTE ON FUNCTION uil.can_read(text[], boolean) TO uil_readonly;")
    stmts.append("GRANT SELECT ON " + ", ".join("uil." + n for n in names) + " TO uil_readonly;")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'uil_readonly') THEN "
        + " ".join(stmts) + " END IF; END $$"
    )


def upgrade() -> None:
    op.execute("ALTER TABLE uil.session_context "
               "ADD COLUMN modules text[] NOT NULL DEFAULT '{}', "
               "ADD COLUMN restricted boolean NOT NULL DEFAULT false")

    # Same hardening as current_org(): SECURITY DEFINER with a pinned search_path.
    # It only ever reports facts about the CALLER'S OWN registered context, so granting
    # EXECUTE to the read-only login is safe even though it takes arguments.
    op.execute("""
        CREATE FUNCTION uil.can_read(required text[], needs_restricted boolean) RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, uil
        AS $$ SELECT COALESCE(
                (SELECT (s.modules && required) AND (NOT needs_restricted OR s.restricted)
                   FROM uil.session_context s WHERE s.backend_pid = pg_backend_pid()),
                false) $$
    """)
    op.execute("REVOKE ALL ON FUNCTION uil.can_read(text[], boolean) FROM PUBLIC")

    for name, *_ in OLD_VIEW_SPEC:
        op.execute("DROP VIEW uil.%s" % name)  # CREATE OR REPLACE cannot drop employees.salary
    for name, base, cols, via, custom_sql, modules, restricted in NEW_VIEW_SPEC:
        op.execute(_new_view_sql(name, base, cols, via, custom_sql, modules, restricted))

    _regrant([s[0] for s in NEW_VIEW_SPEC], with_can_read=True)


def downgrade() -> None:
    for name, *_ in NEW_VIEW_SPEC:
        op.execute("DROP VIEW uil.%s" % name)
    op.execute("DROP FUNCTION uil.can_read(text[], boolean)")
    op.execute("ALTER TABLE uil.session_context DROP COLUMN modules, DROP COLUMN restricted")
    for name, base, cols, via, custom_sql in OLD_VIEW_SPEC:
        op.execute(_old_view_sql(name, base, cols, via, custom_sql))
    _regrant([s[0] for s in OLD_VIEW_SPEC], with_can_read=False)
