"""add uil schema tenant scoped views and session context

Creates everything the Unified Intelligence Layer needs INSIDE the
database, so tenant isolation does not depend on application code
behaving:

  uil.session_context   which organization the current database connection
                        is acting for, keyed by the connection's backend PID.
                        Only the privileged application role can write it;
                        the AI's read-only role has no access to it at all.
  uil.current_org()     SECURITY DEFINER lookup of that row. Returns NULL
                        when no context is set, and since `org_id = NULL`
                        is never true, a connection with no context sees
                        ZERO rows (fail closed, never fail open).
  uil.<view> x 33       one curated, tenant-filtered view per exposed table.
                        security_barrier = true so a crafted function in a
                        query can never be evaluated ahead of the tenant
                        filter and leak rows through side effects.

The view list below is a FROZEN COPY of app/services/intelligence/
manifest.py at the time this migration was written. Migrations must never
import application code that may change later. If the manifest changes, add
a NEW migration; tests/test_uil_manifest.py fails if they drift apart.

The login role (uil_readonly) is deliberately NOT created here: a role is
cluster-wide and needs a password, and secrets do not belong in migrations.
See scripts/setup_uil_role.py.

Revision ID: 533798133a8d
Revises: 457c2fb8b682
"""
from typing import Sequence, Union

from alembic import op

revision: str = "533798133a8d"
down_revision: Union[str, None] = "457c2fb8b682"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (view name, base table, exposed columns, via=(parent table, fk) or None, custom sql or None)
VIEW_SPEC = [
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


def _view_sql(name, base, cols, via, custom_sql):
    if custom_sql:
        select = custom_sql
    elif via is None:
        select = "SELECT %s FROM public.%s WHERE org_id = uil.current_org()" % (", ".join(cols), base)
    else:
        parent, fk = via
        select = (
            "SELECT %s FROM public.%s c JOIN public.%s p ON p.id = c.%s "
            "WHERE p.org_id = uil.current_org()"
        ) % (", ".join("c." + col for col in cols), base, parent, fk)
    return "CREATE VIEW uil.%s WITH (security_barrier = true) AS %s" % (name, select)


def upgrade() -> None:
    op.execute("CREATE SCHEMA uil")

    op.execute("""
        CREATE TABLE uil.session_context (
            backend_pid integer PRIMARY KEY,
            org_id uuid NOT NULL,
            set_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("REVOKE ALL ON TABLE uil.session_context FROM PUBLIC")

    # SECURITY DEFINER + a pinned search_path (the standard hardening for
    # definer functions: without it, a caller could shadow objects the
    # function body refers to). STABLE so Postgres evaluates it once per
    # statement instead of once per row.
    op.execute("""
        CREATE FUNCTION uil.current_org() RETURNS uuid
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, uil
        AS $$ SELECT org_id FROM uil.session_context WHERE backend_pid = pg_backend_pid() $$
    """)
    op.execute("REVOKE ALL ON FUNCTION uil.current_org() FROM PUBLIC")

    for name, base, cols, via, custom_sql in VIEW_SPEC:
        op.execute(_view_sql(name, base, cols, via, custom_sql))


def downgrade() -> None:
    # CASCADE removes every view, the function and the context table in one
    # step. The uil_readonly ROLE is cluster-wide and intentionally left alone.
    op.execute("DROP SCHEMA IF EXISTS uil CASCADE")
