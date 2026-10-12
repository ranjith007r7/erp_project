"""po price corrections (audited amendment of a received purchase order's prices)

Revision ID: e7b3c2a15d90
Revises: c4a1d9e07b21
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e7b3c2a15d90"
down_revision = "c4a1d9e07b21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "po_price_corrections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("po_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("purchase_orders.id"), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("old_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("new_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("corrected_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_po_price_corrections_po_id", "po_price_corrections", ["po_id"])


def downgrade() -> None:
    op.drop_index("ix_po_price_corrections_po_id", table_name="po_price_corrections")
    op.drop_table("po_price_corrections")
