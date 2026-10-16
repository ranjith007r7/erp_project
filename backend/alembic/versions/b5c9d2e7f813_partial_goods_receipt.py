"""partial goods receipt: received_qty per PO line + goods_receipt_lines

15 ordered, 14 good, 1 defective: the good units are received into stock at once; the defective one stays outstanding on the same
purchase order until the vendor's replacement arrives.

Revision ID: b5c9d2e7f813
Revises: a3d6e8b1c479
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b5c9d2e7f813"
down_revision: Union[str, None] = "a3d6e8b1c479"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("purchase_order_items", sa.Column("received_qty", sa.Integer(), nullable=False, server_default="0"))
    op.execute("""UPDATE purchase_order_items i SET received_qty = i.qty
                  FROM purchase_orders p WHERE p.id = i.po_id AND p.status = 'received'""")
    op.create_table(
        "goods_receipt_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("receipt_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("goods_receipts.id"), nullable=False),
        sa.Column("po_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("purchase_order_items.id"), nullable=False),
        sa.Column("qty_good", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("qty_defective", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_goods_receipt_lines_receipt", "goods_receipt_lines", ["receipt_id"])


def downgrade() -> None:
    op.drop_index("ix_goods_receipt_lines_receipt", table_name="goods_receipt_lines")
    op.drop_table("goods_receipt_lines")
    op.drop_column("purchase_order_items", "received_qty")
