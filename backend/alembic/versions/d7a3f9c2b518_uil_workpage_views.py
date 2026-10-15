"""uil views for the Workpage (jobs) data

The AI could not see works at all, so "what did Redbull Racing buy?" answered "no matching data" even though the
client's job, parts and payments were all in the ERP (a converted quotation becomes a WORK, not a sales order).
Adds four tenant-scoped, access-gated views. Frozen copy of the manifest entries (migrations never import app code);
tests/test_uil_manifest.py fails if this and app/services/intelligence/manifest.py ever disagree.

Client contact details (client_mobile, client_details) and free-text notes are deliberately NOT exposed.

Revision ID: d7a3f9c2b518
Revises: c5e8d2f1a403
"""
from typing import Sequence, Union

from alembic import op

revision: str = "d7a3f9c2b518"
down_revision: Union[str, None] = "c5e8d2f1a403"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (name, base, cols, modules)
SPEC = [
    ("work_orders", "work_orders",
     ["id", "work_number", "client_name", "domain", "description", "status", "work_type", "quotation_amount", "vendor_amount",
      "discount_percent", "cgst_percent", "sgst_percent", "customer_id", "lead_id", "opportunity_id", "handling_department_id",
      "allocated_employee_id", "invoice_number", "invoiced_on", "delivered_on", "cancel_reason", "closed_at", "created_at"], ["workpage"]),
    ("work_items", "work_items", ["id", "work_id", "product_id", "qty"], ["workpage"]),
    ("work_stock_issues", "work_stock_issues", ["id", "work_id", "product_id", "qty", "source", "cost_rate", "mrp", "created_at"], ["workpage"]),
    ("work_payments", "work_payments", ["id", "work_id", "amount", "method", "paid_on", "created_at"], ["workpage"]),
]


def _sql(name, base, cols, modules):
    required = "ARRAY[" + ", ".join("'%s'" % m for m in modules) + "]"
    return ("CREATE VIEW uil.%s WITH (security_barrier = true) AS SELECT %s FROM public.%s "
            "WHERE org_id = uil.current_org() AND uil.can_read(%s, false)") % (name, ", ".join(cols), base, required)


def upgrade() -> None:
    for name, base, cols, modules in SPEC:
        op.execute(_sql(name, base, cols, modules))
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'uil_readonly') THEN "
        "GRANT SELECT ON " + ", ".join("uil." + s[0] for s in SPEC) + " TO uil_readonly; END IF; END $$"
    )


def downgrade() -> None:
    for name, *_ in SPEC:
        op.execute("DROP VIEW IF EXISTS uil.%s" % name)
