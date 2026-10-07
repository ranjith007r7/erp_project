"""hr positions leave types payroll deductions payment modes journal numbers

Revision ID: b8d2e4f60a17
Revises: a7c1d2e3f405
Create Date: 2026-10-07 09:08:08.442252

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8d2e4f60a17'
down_revision: Union[str, None] = 'a7c1d2e3f405'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('leave_types',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('code', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('days_per_year', sa.Numeric(precision=6, scale=1), nullable=True),
    sa.Column('per_month', sa.Numeric(precision=4, scale=2), nullable=True),
    sa.Column('paid', sa.Boolean(), nullable=False),
    sa.Column('note', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'code', name='uq_leave_type_code')
    )
    op.create_table('positions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('department_id', sa.UUID(), nullable=False),
    sa.Column('title', sa.String(), nullable=False),
    sa.Column('base_salary', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('access_role_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['access_role_id'], ['roles.id'], ),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'department_id', 'title', name='uq_position_dept_title')
    )
    op.create_table('employee_payroll_profiles',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('employee_id', sa.UUID(), nullable=False),
    sa.Column('pf_percent', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('insurance_percent', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('tds_percent', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('employee_id')
    )
    op.create_table('payroll_inputs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('payroll_run_id', sa.UUID(), nullable=False),
    sa.Column('employee_id', sa.UUID(), nullable=False),
    sa.Column('lop_days', sa.Numeric(precision=4, scale=1), nullable=False),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ),
    sa.ForeignKeyConstraint(['payroll_run_id'], ['payroll_runs.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('payroll_run_id', 'employee_id', name='uq_payroll_input')
    )
    op.add_column('employees', sa.Column('employee_code', sa.String(), nullable=True))
    op.add_column('employees', sa.Column('position_id', sa.UUID(), nullable=True))
    op.add_column('employees', sa.Column('employment_type', sa.String(), nullable=True))
    op.add_column('employees', sa.Column('phone', sa.String(), nullable=True))
    op.add_column('employees', sa.Column('personal_email', sa.String(), nullable=True))
    op.add_column('employees', sa.Column('date_of_birth', sa.Date(), nullable=True))
    op.add_column('employees', sa.Column('gender', sa.String(), nullable=True))
    op.add_column('employees', sa.Column('address', sa.Text(), nullable=True))
    op.add_column('employees', sa.Column('emergency_contact_name', sa.String(), nullable=True))
    op.add_column('employees', sa.Column('emergency_contact_phone', sa.String(), nullable=True))
    op.add_column('employees', sa.Column('created_at', sa.DateTime(), nullable=True))
    op.create_unique_constraint('uq_employee_code', 'employees', ['org_id', 'employee_code'])
    op.create_foreign_key('fk_employee_position', 'employees', 'positions', ['position_id'], ['id'])
    # Back-fill: readable codes for existing employees and numbers for existing journal entries.
    op.execute("UPDATE employees SET created_at = now()")
    op.execute("""
        UPDATE employees e SET employee_code = 'EMP-' || lpad(n.rn::text, 4, '0')
        FROM (SELECT id, row_number() OVER (PARTITION BY org_id ORDER BY joining_date NULLS LAST, name, id) AS rn FROM employees) n
        WHERE e.id = n.id
    """)
    op.add_column('journal_entries', sa.Column('entry_number', sa.String(), nullable=True))
    op.execute("""
        UPDATE journal_entries j SET entry_number = 'JE-' || lpad(n.rn::text, 4, '0')
        FROM (SELECT id, row_number() OVER (PARTITION BY org_id ORDER BY date, id) AS rn FROM journal_entries) n
        WHERE j.id = n.id
    """)
    op.create_unique_constraint('uq_journal_entry_number', 'journal_entries', ['org_id', 'entry_number'])
    op.add_column('payments', sa.Column('transaction_id', sa.String(), nullable=True))
    op.add_column('payments', sa.Column('recorded_by', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_payment_recorded_by', 'payments', 'users', ['recorded_by'], ['id'])
    op.add_column('payslips', sa.Column('pf_percent', sa.Numeric(precision=5, scale=2), server_default='0', nullable=False))
    op.add_column('payslips', sa.Column('insurance_percent', sa.Numeric(precision=5, scale=2), server_default='0', nullable=False))
    op.add_column('payslips', sa.Column('tds_percent', sa.Numeric(precision=5, scale=2), server_default='0', nullable=False))
    op.add_column('payslips', sa.Column('pf_amount', sa.Numeric(precision=12, scale=2), server_default='0', nullable=False))
    op.add_column('payslips', sa.Column('insurance_amount', sa.Numeric(precision=12, scale=2), server_default='0', nullable=False))
    op.add_column('payslips', sa.Column('tds_amount', sa.Numeric(precision=12, scale=2), server_default='0', nullable=False))
    op.add_column('payslips', sa.Column('lop_days', sa.Numeric(precision=4, scale=1), server_default='0', nullable=False))
    op.add_column('payslips', sa.Column('leave_deduction', sa.Numeric(precision=12, scale=2), server_default='0', nullable=False))


def downgrade() -> None:
    op.drop_column('payslips', 'leave_deduction')
    op.drop_column('payslips', 'lop_days')
    op.drop_column('payslips', 'tds_amount')
    op.drop_column('payslips', 'insurance_amount')
    op.drop_column('payslips', 'pf_amount')
    op.drop_column('payslips', 'tds_percent')
    op.drop_column('payslips', 'insurance_percent')
    op.drop_column('payslips', 'pf_percent')
    op.drop_constraint('fk_payment_recorded_by', 'payments', type_='foreignkey')
    op.drop_column('payments', 'recorded_by')
    op.drop_column('payments', 'transaction_id')
    op.drop_constraint('uq_journal_entry_number', 'journal_entries', type_='unique')
    op.drop_column('journal_entries', 'entry_number')
    op.drop_constraint('fk_employee_position', 'employees', type_='foreignkey')
    op.drop_constraint('uq_employee_code', 'employees', type_='unique')
    op.drop_column('employees', 'created_at')
    op.drop_column('employees', 'emergency_contact_phone')
    op.drop_column('employees', 'emergency_contact_name')
    op.drop_column('employees', 'address')
    op.drop_column('employees', 'gender')
    op.drop_column('employees', 'date_of_birth')
    op.drop_column('employees', 'personal_email')
    op.drop_column('employees', 'phone')
    op.drop_column('employees', 'employment_type')
    op.drop_column('employees', 'position_id')
    op.drop_column('employees', 'employee_code')
    op.drop_table('payroll_inputs')
    op.drop_table('employee_payroll_profiles')
    op.drop_table('positions')
    op.drop_table('leave_types')
