"""work cancellation: request/decision columns, stock issue source, nullable batch

Revision ID: c4a1d9e07b21
Revises: 5242143a3692
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c4a1d9e07b21"
down_revision = "5242143a3692"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("work_orders", sa.Column("status_before_cancel", sa.String(), nullable=True))
    op.add_column("work_orders", sa.Column("cancel_reason", sa.String(), nullable=True))
    op.add_column("work_orders", sa.Column("cancel_remark", sa.Text(), nullable=True))
    op.add_column("work_orders", sa.Column("cancel_requested_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("work_orders", sa.Column("cancel_requested_at", sa.DateTime(), nullable=True))
    op.add_column("work_orders", sa.Column("cancel_decided_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("work_orders", sa.Column("cancel_decided_at", sa.DateTime(), nullable=True))
    op.add_column("work_orders", sa.Column("cancel_decision_note", sa.Text(), nullable=True))
    op.create_foreign_key("fk_work_cancel_requested_by", "work_orders", "users", ["cancel_requested_by"], ["id"])
    op.create_foreign_key("fk_work_cancel_decided_by", "work_orders", "users", ["cancel_decided_by"], ["id"])
    op.add_column("work_stock_issues", sa.Column("source", sa.String(), nullable=False, server_default="inventory"))
    op.alter_column("work_stock_issues", "batch_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM work_stock_issues WHERE batch_id IS NULL")
    op.alter_column("work_stock_issues", "batch_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    op.drop_column("work_stock_issues", "source")
    op.drop_constraint("fk_work_cancel_decided_by", "work_orders", type_="foreignkey")
    op.drop_constraint("fk_work_cancel_requested_by", "work_orders", type_="foreignkey")
    for c in ("cancel_decision_note", "cancel_decided_at", "cancel_decided_by", "cancel_requested_at", "cancel_requested_by",
              "cancel_remark", "cancel_reason", "status_before_cancel"):
        op.drop_column("work_orders", c)
