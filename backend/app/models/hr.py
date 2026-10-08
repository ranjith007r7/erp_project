import uuid
from datetime import datetime, date, time

from sqlalchemy import Column, String, ForeignKey, DateTime, Date, Time, Numeric, Integer, Boolean, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class Department(Base):
    __tablename__ = "departments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    name = Column(String, nullable=False)


class Position(Base):
    """
    A job role INSIDE a department, e.g. Sales > Sales Executive, with the
    monthly salary fixed up front by an authorised person (hr.approve). When
    HR hires someone they pick department then position and the salary comes
    from here; they never type it. `access_role_id` optionally names the
    login role (RBAC) a person in this position should get, so hiring and
    access stay in step. Not to be confused with RBAC `Role`.
    """
    __tablename__ = "positions"
    __table_args__ = (UniqueConstraint("org_id", "department_id", "title", name="uq_position_dept_title"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    department_id = Column(UUID(as_uuid=True), ForeignKey("departments.id"), nullable=False)
    title = Column(String, nullable=False)
    base_salary = Column(Numeric(12, 2), nullable=False, default=0)
    access_role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    department = relationship("Department")
    access_role = relationship("Role")


class LeaveType(Base):
    """
    The org's leave policy legend (casual, sick, earned, ...). Seeded with
    common Indian-norm defaults on first use. `paid=False` types (Loss of
    Pay) are the ones that reduce salary.
    """
    __tablename__ = "leave_types"
    __table_args__ = (UniqueConstraint("org_id", "code", name="uq_leave_type_code"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    code = Column(String, nullable=False)          # CL, SL, EL ...
    name = Column(String, nullable=False)
    days_per_year = Column(Numeric(6, 1), nullable=True)   # null = not accrued yearly
    per_month = Column(Numeric(4, 2), nullable=True)       # accrual per month, if any
    paid = Column(Boolean, nullable=False, default=True)
    note = Column(String, nullable=True)


class EmployeePayrollProfile(Base):
    """Deduction percentages for one employee, filled by Finance. One row per employee."""
    __tablename__ = "employee_payroll_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False, unique=True)
    pf_percent = Column(Numeric(5, 2), nullable=False, default=0)
    insurance_percent = Column(Numeric(5, 2), nullable=False, default=0)
    tds_percent = Column(Numeric(5, 2), nullable=False, default=0)
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow)


class PayrollInput(Base):
    """Per-run, per-employee input that varies month to month: unpaid (Loss of Pay) leave days."""
    __tablename__ = "payroll_inputs"
    __table_args__ = (UniqueConstraint("payroll_run_id", "employee_id", name="uq_payroll_input"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payroll_run_id = Column(UUID(as_uuid=True), ForeignKey("payroll_runs.id"), nullable=False)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    lop_days = Column(Numeric(4, 1), nullable=False, default=0)


class Employee(Base):
    """
    An HR record - distinct from a login User because not every employee
    necessarily has (or needs) a system login, and a User who DOES log in
    isn't automatically an employee (e.g. an external accountant granted
    access). user_id links the two when both exist, but is optional.
    """
    __tablename__ = "employees"
    __table_args__ = (UniqueConstraint("org_id", "employee_code", name="uq_employee_code"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    name = Column(String, nullable=False)
    designation = Column(String, nullable=True)
    department_id = Column(UUID(as_uuid=True), ForeignKey("departments.id"), nullable=True)
    department = relationship("Department")
    joining_date = Column(Date, nullable=True)
    salary = Column(Numeric(12, 2), nullable=False, default=0)
    status = Column(String, default="active")  # active / inactive

    # Human-readable id ("EMP-0001"), unique per organization.
    employee_code = Column(String, nullable=True)
    position_id = Column(UUID(as_uuid=True), ForeignKey("positions.id"), nullable=True)
    position = relationship("Position")
    # The paper application form HR transcribes.
    employment_type = Column(String, nullable=True)   # full_time / part_time / contract / intern
    phone = Column(String, nullable=True)
    personal_email = Column(String, nullable=True)
    date_of_birth = Column(Date, nullable=True)
    gender = Column(String, nullable=True)
    address = Column(Text, nullable=True)
    emergency_contact_name = Column(String, nullable=True)
    emergency_contact_phone = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Attendance(Base):
    """One row per employee per day, marked by an administrator only (see hr routes)."""
    __tablename__ = "attendance"
    __table_args__ = (UniqueConstraint("employee_id", "date", name="uq_attendance_employee_date"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    date = Column(Date, default=date.today)
    status = Column(String, default="present")  # present / absent / half_day / leave
    check_in = Column(Time, nullable=True)
    check_out = Column(Time, nullable=True)
    marked_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class LeaveRequest(Base):
    __tablename__ = "leave_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    leave_type = Column(String, nullable=False)   # e.g. "Sick", "Casual", "Earned"
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    status = Column(String, default="pending")     # pending / approved / rejected / cancelled
    created_at = Column(DateTime, default=datetime.utcnow)
    reason = Column(Text, nullable=True)
    decided_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    decided_at = Column(DateTime, nullable=True)
    decision_note = Column(String, nullable=True)

    @property
    def days(self) -> int:
        """Calendar days, both ends included (the same counting payroll uses for unpaid leave)."""
        return (self.end_date - self.start_date).days + 1


class PayrollRun(Base):
    """
    One monthly payroll cycle for the whole organization. Creating one is
    just a placeholder ("draft") - the real work happens in /process,
    which generates a Payslip for every active Employee AND posts a single
    Journal Entry for the total, mirroring exactly how Sales' invoice
    generation and Procurement's goods receipt work: one action, multiple
    module effects, in the same transaction.
    """
    __tablename__ = "payroll_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    month = Column(Integer, nullable=False)
    year = Column(Integer, nullable=False)
    status = Column(String, default="draft")  # draft / processed

    payslips = relationship("Payslip", back_populates="payroll_run", cascade="all, delete-orphan")


class Payslip(Base):
    __tablename__ = "payslips"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payroll_run_id = Column(UUID(as_uuid=True), ForeignKey("payroll_runs.id"), nullable=False)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    gross = Column(Numeric(12, 2), nullable=False)
    deductions = Column(Numeric(12, 2), nullable=False, default=0)
    net_pay = Column(Numeric(12, 2), nullable=False)
    # Breakdown of `deductions` (their sum). Percentages used are kept so a
    # payslip stays explainable after the employee's profile changes later.
    pf_percent = Column(Numeric(5, 2), nullable=False, default=0, server_default="0")
    insurance_percent = Column(Numeric(5, 2), nullable=False, default=0, server_default="0")
    tds_percent = Column(Numeric(5, 2), nullable=False, default=0, server_default="0")
    pf_amount = Column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    insurance_amount = Column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    tds_amount = Column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    lop_days = Column(Numeric(4, 1), nullable=False, default=0, server_default="0")
    leave_deduction = Column(Numeric(12, 2), nullable=False, default=0, server_default="0")

    payroll_run = relationship("PayrollRun", back_populates="payslips")
