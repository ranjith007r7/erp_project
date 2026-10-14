"""product master carries MRP + max discount (lots inherit them); GST-credit (ITC) flag on lots and issue lines

Revision ID: c5e8d2f1a403
Revises: b3f7a1c9d842
"""
from alembic import op
import sqlalchemy as sa

revision = "c5e8d2f1a403"
down_revision = "b3f7a1c9d842"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("mrp", sa.Numeric(12, 2), nullable=True))                       # GST included, as printed on the pack
    op.add_column("products", sa.Column("max_discount_percent", sa.Numeric(5, 2), nullable=False, server_default="0"))
    for t in ("stock_batches", "work_stock_issues"):
        op.add_column(t, sa.Column("itc_eligible", sa.Boolean(), nullable=False, server_default=sa.true()))
    # lots that were left without a GST slab (entered before the product had its rates) take the product's slab now
    op.execute("""UPDATE stock_batches b SET cgst_percent = p.cgst_percent, sgst_percent = p.sgst_percent
                  FROM products p WHERE p.id = b.product_id AND b.cgst_percent = 0 AND b.sgst_percent = 0
                  AND (p.cgst_percent > 0 OR p.sgst_percent > 0)""")


def downgrade() -> None:
    for t in ("stock_batches", "work_stock_issues"):
        op.drop_column(t, "itc_eligible")
    op.drop_column("products", "max_discount_percent")
    op.drop_column("products", "mrp")
