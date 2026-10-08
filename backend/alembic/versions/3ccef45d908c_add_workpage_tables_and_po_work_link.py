"""add workpage tables and po work link

Revision ID: 3ccef45d908c
Revises: 59eb0d67c2b3
Create Date: 2026-10-08 15:37:18.987450

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '3ccef45d908c'
down_revision: Union[str, None] = '59eb0d67c2b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('work_orders',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('work_number', sa.String(), nullable=False),
    sa.Column('client_name', sa.String(), nullable=False),
    sa.Column('domain', sa.String(), nullable=True),
    sa.Column('client_details', sa.Text(), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('status', sa.String(), server_default='assigned', nullable=False),
    sa.Column('quotation_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('vendor_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('discount_percent', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=True),
    sa.Column('quotation_id', sa.UUID(), nullable=True),
    sa.Column('sales_order_id', sa.UUID(), nullable=True),
    sa.Column('handling_department_id', sa.UUID(), nullable=True),
    sa.Column('allocated_employee_id', sa.UUID(), nullable=True),
    sa.Column('delivered_on', sa.Date(), nullable=True),
    sa.Column('delivery_note', sa.Text(), nullable=True),
    sa.Column('closed_at', sa.DateTime(), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['allocated_employee_id'], ['employees.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ),
    sa.ForeignKeyConstraint(['handling_department_id'], ['departments.id'], ),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
    sa.ForeignKeyConstraint(['quotation_id'], ['quotations.id'], ),
    sa.ForeignKeyConstraint(['sales_order_id'], ['sales_orders.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'work_number', name='uq_work_number')
    )
    op.create_table('work_events',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('work_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('title', sa.String(), nullable=False),
    sa.Column('detail', sa.Text(), nullable=True),
    sa.Column('actor_user_id', sa.UUID(), nullable=True),
    sa.Column('actor_name', sa.String(), nullable=True),
    sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
    sa.ForeignKeyConstraint(['work_id'], ['work_orders.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('work_payments',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('work_id', sa.UUID(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('method', sa.String(), nullable=False),
    sa.Column('transaction_id', sa.String(), nullable=True),
    sa.Column('note', sa.String(), nullable=True),
    sa.Column('paid_on', sa.Date(), nullable=True),
    sa.Column('recorded_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
    sa.ForeignKeyConstraint(['recorded_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['work_id'], ['work_orders.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.add_column('purchase_orders', sa.Column('work_order_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_purchase_orders_work_order', 'purchase_orders', 'work_orders', ['work_order_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_purchase_orders_work_order', 'purchase_orders', type_='foreignkey')
    op.drop_column('purchase_orders', 'work_order_id')
    op.drop_table('work_payments')
    op.drop_table('work_events')
    op.drop_table('work_orders')
