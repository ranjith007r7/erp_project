"""stock batches, work items and stock issues, lead mobile amount, work lead link

Revision ID: 5242143a3692
Revises: 2f0646635153
Create Date: 2026-10-09 15:33:07.501910

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5242143a3692'
down_revision: Union[str, None] = '2f0646635153'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('work_items',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('work_id', sa.UUID(), nullable=False),
    sa.Column('product_id', sa.UUID(), nullable=False),
    sa.Column('qty', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
    sa.ForeignKeyConstraint(['work_id'], ['work_orders.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('stock_batches',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('product_id', sa.UUID(), nullable=False),
    sa.Column('vendor_id', sa.UUID(), nullable=True),
    sa.Column('vendor_name', sa.String(), nullable=False),
    sa.Column('quantity_in', sa.Integer(), nullable=False),
    sa.Column('quantity_remaining', sa.Integer(), nullable=False),
    sa.Column('vendor_amount', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('mrp', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('max_discount_percent', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('inward_date', sa.Date(), nullable=False),
    sa.Column('manufacture_month', sa.Date(), nullable=True),
    sa.Column('expiry_date', sa.Date(), nullable=True),
    sa.Column('source', sa.String(), nullable=False),
    sa.Column('po_id', sa.UUID(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
    sa.ForeignKeyConstraint(['po_id'], ['purchase_orders.id'], ),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
    sa.ForeignKeyConstraint(['vendor_id'], ['vendors.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('work_stock_issues',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('work_id', sa.UUID(), nullable=False),
    sa.Column('batch_id', sa.UUID(), nullable=False),
    sa.Column('product_id', sa.UUID(), nullable=False),
    sa.Column('qty', sa.Integer(), nullable=False),
    sa.Column('cost_rate', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('mrp', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('max_discount_percent', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('issued_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['batch_id'], ['stock_batches.id'], ),
    sa.ForeignKeyConstraint(['issued_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
    sa.ForeignKeyConstraint(['work_id'], ['work_orders.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.add_column('crm_leads', sa.Column('estimated_amount', sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column('crm_leads', sa.Column('industry', sa.String(), nullable=True))
    op.add_column('crm_leads', sa.Column('converted_at', sa.DateTime(), nullable=True))
    op.add_column('work_orders', sa.Column('lead_id', sa.UUID(), nullable=True))
    op.add_column('work_orders', sa.Column('opportunity_id', sa.UUID(), nullable=True))
    op.add_column('work_orders', sa.Column('client_mobile', sa.String(), nullable=True))
    op.add_column('work_orders', sa.Column('pending_note', sa.Text(), nullable=True))
    op.create_foreign_key('fk_work_orders_lead', 'work_orders', 'crm_leads', ['lead_id'], ['id'])
    op.execute("UPDATE crm_leads SET converted_at = created_at WHERE status = 'converted' AND converted_at IS NULL")
    op.create_foreign_key('fk_work_orders_opportunity', 'work_orders', 'crm_opportunities', ['opportunity_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_work_orders_opportunity', 'work_orders', type_='foreignkey')
    op.drop_constraint('fk_work_orders_lead', 'work_orders', type_='foreignkey')
    op.drop_column('work_orders', 'pending_note')
    op.drop_column('work_orders', 'client_mobile')
    op.drop_column('work_orders', 'opportunity_id')
    op.drop_column('work_orders', 'lead_id')
    op.drop_column('crm_leads', 'converted_at')
    op.drop_column('crm_leads', 'industry')
    op.drop_column('crm_leads', 'estimated_amount')
    op.drop_table('work_stock_issues')
    op.drop_table('stock_batches')
    op.drop_table('work_items')
