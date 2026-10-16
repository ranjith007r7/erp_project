"""warranty records / units, claims, claim files; product + lot + PO line warranty fields

Revision ID: c8e1f4a9d276
Revises: b5c9d2e7f813
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c8e1f4a9d276"
down_revision: Union[str, None] = "b5c9d2e7f813"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column("products", sa.Column("warranty_months", sa.Integer(), nullable=True))
    op.add_column("products", sa.Column("warranty_terms", sa.Text(), nullable=True))
    op.add_column("stock_batches", sa.Column("vendor_warranty_months", sa.Integer(), nullable=True))
    op.add_column("purchase_order_items", sa.Column("warranty_months", sa.Integer(), nullable=True))

    op.create_table(
        "warranty_records",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("org_id", UUID, sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("work_id", UUID, sa.ForeignKey("work_orders.id"), nullable=False),
        sa.Column("product_id", UUID, sa.ForeignKey("products.id"), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(), nullable=False, server_default="pending_details"),
        sa.Column("warranty_months", sa.Integer(), nullable=True),
        sa.Column("warranty_terms", sa.Text(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("card_number", sa.String(), nullable=True),
        sa.Column("submitted_by", UUID, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("approved_by", UUID, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("no_warranty_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("work_id", "product_id", name="uq_warranty_work_product"),
    )
    op.create_index("ix_warranty_records_org_status", "warranty_records", ["org_id", "status"])
    op.create_table(
        "warranty_units",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("org_id", UUID, sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("warranty_id", UUID, sa.ForeignKey("warranty_records.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("model_number", sa.String(), nullable=True),
        sa.Column("serial_number", sa.String(), nullable=True),
        sa.Column("manufacture_month", sa.Date(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("batch_id", UUID, sa.ForeignKey("stock_batches.id"), nullable=True),
    )
    op.create_index("ix_warranty_units_warranty", "warranty_units", ["warranty_id"])
    op.create_table(
        "warranty_claims",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("org_id", UUID, sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("claim_number", sa.String(), nullable=False),
        sa.Column("warranty_id", UUID, sa.ForeignKey("warranty_records.id"), nullable=False),
        sa.Column("unit_id", UUID, sa.ForeignKey("warranty_units.id"), nullable=False),
        sa.Column("issue", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("out_of_warranty", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("resolution", sa.String(), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("decided_by", UUID, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("replacement_work_id", UUID, sa.ForeignKey("work_orders.id"), nullable=True),
        sa.Column("vendor_notice_at", sa.DateTime(), nullable=True),
        sa.Column("vendor_notice_to", sa.String(), nullable=True),
        sa.Column("vendor_notice_channel", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("org_id", "claim_number", name="uq_claim_number"),
    )
    op.create_table(
        "warranty_claim_files",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("org_id", UUID, sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("claim_id", UUID, sa.ForeignKey("warranty_claims.id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_warranty_claim_files_claim", "warranty_claim_files", ["claim_id"])


def downgrade() -> None:
    op.drop_index("ix_warranty_claim_files_claim", table_name="warranty_claim_files")
    op.drop_table("warranty_claim_files")
    op.drop_table("warranty_claims")
    op.drop_index("ix_warranty_units_warranty", table_name="warranty_units")
    op.drop_table("warranty_units")
    op.drop_index("ix_warranty_records_org_status", table_name="warranty_records")
    op.drop_table("warranty_records")
    op.drop_column("purchase_order_items", "warranty_months")
    op.drop_column("stock_batches", "vendor_warranty_months")
    op.drop_column("products", "warranty_terms")
    op.drop_column("products", "warranty_months")
