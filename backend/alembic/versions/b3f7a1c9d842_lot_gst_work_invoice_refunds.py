"""lot GST slab (MSP + CGST + SGST = MRP), issue-line GST snapshot, work tax invoice number, refunds

Revision ID: b3f7a1c9d842
Revises: a9d4e6b1c730
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b3f7a1c9d842"
down_revision = "a9d4e6b1c730"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for t in ("stock_batches", "work_stock_issues"):
        op.add_column(t, sa.Column("cgst_percent", sa.Numeric(5, 2), nullable=False, server_default="0"))
        op.add_column(t, sa.Column("sgst_percent", sa.Numeric(5, 2), nullable=False, server_default="0"))
    # existing lots take the GST slab of their product
    op.execute("""UPDATE stock_batches b SET cgst_percent = p.cgst_percent, sgst_percent = p.sgst_percent
                  FROM products p WHERE p.id = b.product_id""")
    op.add_column("work_orders", sa.Column("invoice_number", sa.String(), nullable=True))
    op.add_column("work_orders", sa.Column("invoiced_on", sa.Date(), nullable=True))
    op.create_unique_constraint("uq_work_invoice_number", "work_orders", ["org_id", "invoice_number"])
    op.create_table(
        "refunds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("refund_number", sa.String(), nullable=False),
        sa.Column("work_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("work_orders.id"), nullable=False),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("invoices.id"), nullable=True),
        sa.Column("client_name", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("received_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("charge_percent", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("charge_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("refund_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("method", sa.String(), nullable=True),
        sa.Column("transaction_id", sa.String(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("refund_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("completed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("org_id", "refund_number", name="uq_refund_number"),
    )
    op.create_index("ix_refunds_work_id", "refunds", ["work_id"])
    # works that were already cancelled with money received get their pending refund
    op.execute("""
        INSERT INTO refunds (id, org_id, refund_number, work_id, client_name, reason, received_amount, charge_percent, charge_amount, refund_amount, status, created_at)
        SELECT gen_random_uuid(), w.org_id,
               'RF-' || lpad(row_number() OVER (PARTITION BY w.org_id ORDER BY w.created_at)::text, 4, '0'),
               w.id, w.client_name, w.cancel_reason, s.total, 0, 0, s.total, 'pending', now()
        FROM work_orders w
        JOIN (SELECT work_id, SUM(amount) AS total FROM work_payments GROUP BY work_id) s ON s.work_id = w.id
        WHERE w.status = 'cancelled' AND s.total > 0 AND w.work_type = 'project'""")


def downgrade() -> None:
    op.drop_index("ix_refunds_work_id", table_name="refunds")
    op.drop_table("refunds")
    op.drop_constraint("uq_work_invoice_number", "work_orders", type_="unique")
    op.drop_column("work_orders", "invoiced_on")
    op.drop_column("work_orders", "invoice_number")
    for t in ("work_stock_issues", "stock_batches"):
        op.drop_column(t, "sgst_percent")
        op.drop_column(t, "cgst_percent")
