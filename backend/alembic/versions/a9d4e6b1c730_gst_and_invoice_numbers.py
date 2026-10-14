"""GST (CGST + SGST) on products, quotation/order/PO lines, work amounts; invoice numbers and tax split

Revision ID: a9d4e6b1c730
Revises: f1a8c5d3b620
"""
from alembic import op
import sqlalchemy as sa

revision = "a9d4e6b1c730"
down_revision = "f1a8c5d3b620"
branch_labels = None
depends_on = None


def _pct(table, name):
    op.add_column(table, sa.Column(name, sa.Numeric(5, 2), nullable=False, server_default="0"))


def _amt(table, name):
    op.add_column(table, sa.Column(name, sa.Numeric(12, 2), nullable=False, server_default="0"))


def upgrade() -> None:
    for t in ("products", "quotation_items", "sales_order_items", "purchase_order_items", "work_orders"):
        _pct(t, "cgst_percent")
        _pct(t, "sgst_percent")
    op.add_column("products", sa.Column("hsn_code", sa.String(), nullable=True))
    for t in ("quotations", "sales_orders", "invoices"):
        _amt(t, "subtotal")
        _amt(t, "cgst_amount")
        _amt(t, "sgst_amount")
    # existing documents had no GST: their taxable value is their whole total
    op.execute("UPDATE quotations SET subtotal = COALESCE(total, 0)")
    op.execute("UPDATE sales_orders SET subtotal = COALESCE(total, 0)")
    op.execute("UPDATE invoices SET subtotal = amount")
    _amt("purchase_orders", "cgst_amount")
    _amt("purchase_orders", "sgst_amount")
    _amt("purchase_orders", "grand_total")
    op.execute("UPDATE purchase_orders SET grand_total = COALESCE(total, 0)")
    op.add_column("invoices", sa.Column("invoice_number", sa.String(), nullable=True))
    op.execute("""
        UPDATE invoices i SET invoice_number = 'INV-' || lpad(n.rn::text, 4, '0')
        FROM (SELECT id, row_number() OVER (PARTITION BY org_id ORDER BY created_at, id) AS rn FROM invoices) n
        WHERE n.id = i.id""")
    op.create_unique_constraint("uq_invoice_org_number", "invoices", ["org_id", "invoice_number"])


def downgrade() -> None:
    op.drop_constraint("uq_invoice_org_number", "invoices", type_="unique")
    op.drop_column("invoices", "invoice_number")
    for c in ("grand_total", "sgst_amount", "cgst_amount"):
        op.drop_column("purchase_orders", c)
    for t in ("invoices", "sales_orders", "quotations"):
        for c in ("sgst_amount", "cgst_amount", "subtotal"):
            op.drop_column(t, c)
    op.drop_column("products", "hsn_code")
    for t in ("work_orders", "purchase_order_items", "sales_order_items", "quotation_items", "products"):
        op.drop_column(t, "sgst_percent")
        op.drop_column(t, "cgst_percent")
