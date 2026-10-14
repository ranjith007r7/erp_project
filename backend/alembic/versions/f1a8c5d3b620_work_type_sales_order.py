"""work type: separate direct sales (Sales-accepted quotations) from the normal work cycle

Revision ID: f1a8c5d3b620
Revises: e7b3c2a15d90
"""
from alembic import op
import sqlalchemy as sa

revision = "f1a8c5d3b620"
down_revision = "e7b3c2a15d90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("work_orders", sa.Column("work_type", sa.String(), nullable=False, server_default="project"))
    # Existing works opened by a Sales quotation with no CRM lead / opportunity behind them are direct sales.
    op.execute("UPDATE work_orders SET work_type = 'sales_order' "
               "WHERE quotation_id IS NOT NULL AND lead_id IS NULL AND opportunity_id IS NULL")


def downgrade() -> None:
    op.drop_column("work_orders", "work_type")
