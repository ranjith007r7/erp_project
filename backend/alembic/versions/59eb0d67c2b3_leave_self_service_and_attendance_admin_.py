"""leave self service and attendance admin only

Revision ID: 59eb0d67c2b3
Revises: 838514aec2df
Create Date: 2026-10-08 06:37:26.261270

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '59eb0d67c2b3'
down_revision: Union[str, None] = '838514aec2df'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('attendance', sa.Column('marked_by', sa.UUID(), nullable=True))
    # one mark per employee per day from now on: keep a single row where older data has duplicates
    op.execute("DELETE FROM attendance a USING attendance b WHERE a.employee_id = b.employee_id AND a.date = b.date AND a.ctid < b.ctid")
    op.create_unique_constraint('uq_attendance_employee_date', 'attendance', ['employee_id', 'date'])
    op.create_foreign_key('fk_attendance_marked_by', 'attendance', 'users', ['marked_by'], ['id'])
    op.add_column('leave_requests', sa.Column('reason', sa.Text(), nullable=True))
    op.add_column('leave_requests', sa.Column('decided_by', sa.UUID(), nullable=True))
    op.add_column('leave_requests', sa.Column('decided_at', sa.DateTime(), nullable=True))
    op.add_column('leave_requests', sa.Column('decision_note', sa.String(), nullable=True))
    op.create_foreign_key('fk_leave_requests_decided_by', 'leave_requests', 'users', ['decided_by'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_leave_requests_decided_by', 'leave_requests', type_='foreignkey')
    op.drop_column('leave_requests', 'decision_note')
    op.drop_column('leave_requests', 'decided_at')
    op.drop_column('leave_requests', 'decided_by')
    op.drop_column('leave_requests', 'reason')
    op.drop_constraint('fk_attendance_marked_by', 'attendance', type_='foreignkey')
    op.drop_constraint('uq_attendance_employee_date', 'attendance', type_='unique')
    op.drop_column('attendance', 'marked_by')
