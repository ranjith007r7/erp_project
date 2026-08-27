import uuid
from datetime import datetime, date, time

from sqlalchemy import Column, String, ForeignKey, DateTime, Date, Time, Numeric, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class Department(Base):
    __tablename__ = "departments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    name = Column(String, nullable=False)


class Employee(Base):
    """
    An HR record - distinct from a login User because not every employee
    necessarily has (or needs) a system login, and a User who DOES log in
    isn't automatically an employee (e.g. an external accountant granted
    access). user_id links the two when both exist, but is optional.
    """
    __tablename__ = "employees"

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


class Attendance(Base):
    __tablename__ = "attendance"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    date = Column(Date, default=date.today)
    status = Column(String, default="present")  # present / absent / half_day / leave
    check_in = Column(Time, nullable=True)
    check_out = Column(Time, nullable=True)


class LeaveRequest(Base):
    __tablename__ = "leave_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    leave_type = Column(String, nullable=False)   # e.g. "Sick", "Casual", "Earned"
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    status = Column(String, default="pending")     # pending / approved / rejected
    created_at = Column(DateTime, default=datetime.utcnow)


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

    payroll_run = relationship("PayrollRun", back_populates="payslips")
