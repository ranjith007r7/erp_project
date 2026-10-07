"""procurement approval, goods receiving proof files, vendor email, email log

Adds to Procurement:
  vendors.email                          optional, pre-fills the "email PO" screen
  purchase_orders.po_number              "PO-0001"... unique per org (back-filled)
  purchase_orders.approval_status        pending / approved / rejected
  purchase_orders.created_by/approved_by/approved_at/created_at
  goods_receipts.condition/notes/received_by/created_at
  goods_receipt_files                    invoice / POD / defect-photo proof
  procurement_email_log                  every PO / defect notice sent or printed

Existing purchase orders pre-date approval, so they are back-filled as
"approved" (they were already acted on) and numbered by order of creation.

Revision ID: a7c1d2e3f405
Revises: 4fe66f020602
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7c1d2e3f405"
down_revision: Union[str, None] = "4fe66f020602"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("vendors", sa.Column("email", sa.String(), nullable=True))

    op.add_column("purchase_orders", sa.Column("po_number", sa.String(), nullable=True))
    op.add_column("purchase_orders", sa.Column("approval_status", sa.String(), nullable=False, server_default="pending"))
    op.add_column("purchase_orders", sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("purchase_orders", sa.Column("approved_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("purchase_orders", sa.Column("approved_at", sa.DateTime(), nullable=True))
    op.add_column("purchase_orders", sa.Column("created_at", sa.DateTime(), nullable=True))
    op.create_foreign_key("fk_po_created_by", "purchase_orders", "users", ["created_by"], ["id"])
    op.create_foreign_key("fk_po_approved_by", "purchase_orders", "users", ["approved_by"], ["id"])

    # Back-fill: legacy POs were already actioned, so they count as approved.
    op.execute("UPDATE purchase_orders SET approval_status = 'approved', created_at = now()")
    op.execute("""
        UPDATE purchase_orders p SET po_number = 'PO-' || lpad(n.rn::text, 4, '0')
        FROM (SELECT id, row_number() OVER (PARTITION BY org_id ORDER BY order_date, id) AS rn
              FROM purchase_orders) n
        WHERE p.id = n.id
    """)
    op.create_unique_constraint("uq_po_org_number", "purchase_orders", ["org_id", "po_number"])

    op.add_column("goods_receipts", sa.Column("condition", sa.String(), nullable=False, server_default="good"))
    op.add_column("goods_receipts", sa.Column("notes", sa.Text(), nullable=True))
    op.add_column("goods_receipts", sa.Column("received_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("goods_receipts", sa.Column("created_at", sa.DateTime(), nullable=True))
    op.create_foreign_key("fk_receipt_received_by", "goods_receipts", "users", ["received_by"], ["id"])
    op.execute("UPDATE goods_receipts SET created_at = now()")

    op.create_table(
        "goods_receipt_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("receipt_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("goods_receipts.id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "procurement_email_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("po_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("purchase_orders.id"), nullable=False),
        sa.Column("receipt_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("goods_receipts.id"), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("to_email", sa.String(), nullable=True),
        sa.Column("subject", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("procurement_email_log")
    op.drop_table("goods_receipt_files")
    op.drop_constraint("fk_receipt_received_by", "goods_receipts", type_="foreignkey")
    for c in ("created_at", "received_by", "notes", "condition"):
        op.drop_column("goods_receipts", c)
    op.drop_constraint("uq_po_org_number", "purchase_orders", type_="unique")
    op.drop_constraint("fk_po_approved_by", "purchase_orders", type_="foreignkey")
    op.drop_constraint("fk_po_created_by", "purchase_orders", type_="foreignkey")
    for c in ("created_at", "approved_at", "approved_by", "created_by", "approval_status", "po_number"):
        op.drop_column("purchase_orders", c)
    op.drop_column("vendors", "email")
