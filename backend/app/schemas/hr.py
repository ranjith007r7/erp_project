from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class DepartmentCreate(BaseModel):
    name: str = Field(..., min_length=1)


class DepartmentOut(BaseModel):
    id: UUID
    name: str

    model_config = {"from_attributes": True}


class PositionCreate(BaseModel):
    department_id: UUID
    title: str = Field(..., min_length=1, max_length=80)
    base_salary: Decimal = Field(..., ge=0)
    access_role_id: Optional[UUID] = None


class PositionUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=80)
    base_salary: Optional[Decimal] = Field(None, ge=0)
    access_role_id: Optional[UUID] = None
    clear_access_role: bool = False
    # When the salary changes: also move people already in this position to it?
    apply_to_existing: bool = False


class PositionOut(BaseModel):
    id: UUID
    department_id: UUID
    department_name: Optional[str] = None
    title: str
    base_salary: Decimal
    access_role_id: Optional[UUID] = None
    access_role_name: Optional[str] = None
    employee_count: int = 0


EMPLOYMENT_TYPES = "^(full_time|part_time|contract|intern)$"


class EmployeeCreate(BaseModel):
    """
    The application form. department_id + position_id decide designation and
    salary: whatever salary a caller sends is IGNORED when a position is chosen.
    Without a position (legacy / CSV style) only someone with hr.approve may
    set salary and designation by hand.
    """
    name: str = Field(..., min_length=1)
    department_id: Optional[UUID] = None
    position_id: Optional[UUID] = None
    joining_date: Optional[date] = None
    employment_type: Optional[str] = Field(None, pattern=EMPLOYMENT_TYPES)
    phone: Optional[str] = Field(None, max_length=30)
    personal_email: Optional[str] = Field(None, max_length=120)
    date_of_birth: Optional[date] = None
    gender: Optional[str] = Field(None, pattern="^(male|female|other)$")
    address: Optional[str] = Field(None, max_length=500)
    emergency_contact_name: Optional[str] = Field(None, max_length=80)
    emergency_contact_phone: Optional[str] = Field(None, max_length=30)
    # Legacy manual path (needs hr.approve when no position is chosen)
    designation: Optional[str] = None
    salary: Optional[Decimal] = Field(None, ge=0)
    user_id: Optional[UUID] = None


class EmployeeUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1)
    position_id: Optional[UUID] = None       # changing it needs hr.approve (it changes salary)
    joining_date: Optional[date] = None
    employment_type: Optional[str] = Field(None, pattern=EMPLOYMENT_TYPES)
    phone: Optional[str] = Field(None, max_length=30)
    personal_email: Optional[str] = Field(None, max_length=120)
    date_of_birth: Optional[date] = None
    gender: Optional[str] = Field(None, pattern="^(male|female|other)$")
    address: Optional[str] = Field(None, max_length=500)
    emergency_contact_name: Optional[str] = Field(None, max_length=80)
    emergency_contact_phone: Optional[str] = Field(None, max_length=30)


class EmployeeOut(BaseModel):
    id: UUID
    employee_code: Optional[str] = None
    name: str
    designation: Optional[str] = None
    department_id: Optional[UUID] = None
    department_name: Optional[str] = None
    position_id: Optional[UUID] = None
    joining_date: Optional[date] = None
    salary: Decimal
    status: str
    user_id: Optional[UUID] = None
    login_status: Optional[str] = None       # None = no login, else invited / active / disabled
    login_email: Optional[str] = None
    access_role_name: Optional[str] = None
    employment_type: Optional[str] = None
    phone: Optional[str] = None
    personal_email: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    address: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None


class CreateLoginIn(BaseModel):
    email: str = Field(..., min_length=3, max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LeaveTypeOut(BaseModel):
    id: UUID
    code: str
    name: str
    days_per_year: Optional[Decimal] = None
    per_month: Optional[Decimal] = None
    paid: bool
    note: Optional[str] = None

    model_config = {"from_attributes": True}


class LeaveTypeUpdate(BaseModel):
    days_per_year: Optional[Decimal] = Field(None, ge=0, le=366)
    per_month: Optional[Decimal] = Field(None, ge=0, le=31)
    paid: Optional[bool] = None
    note: Optional[str] = Field(None, max_length=200)


class LeaveRequestCreate(BaseModel):
    employee_id: UUID
    leave_type: str = Field(..., min_length=1)
    start_date: date
    end_date: date


class LeaveRequestOut(BaseModel):
    id: UUID
    employee_id: UUID
    leave_type: str
    start_date: date
    end_date: date
    status: str

    model_config = {"from_attributes": True}


class LeaveStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(pending|approved|rejected)$")


class AttendanceMark(BaseModel):
    employee_id: UUID
    status: str = Field("present", pattern="^(present|absent|half_day|leave)$")


class AttendanceOut(BaseModel):
    id: UUID
    employee_id: UUID
    date: date
    status: str

    model_config = {"from_attributes": True}


class PayrollRunCreate(BaseModel):
    month: int = Field(..., ge=1, le=12)
    year: int = Field(..., ge=2000, le=2100)


class PayslipOut(BaseModel):
    id: UUID
    employee_id: UUID
    gross: Decimal
    deductions: Decimal
    net_pay: Decimal
    pf_percent: Decimal = Decimal(0)
    insurance_percent: Decimal = Decimal(0)
    tds_percent: Decimal = Decimal(0)
    pf_amount: Decimal = Decimal(0)
    insurance_amount: Decimal = Decimal(0)
    tds_amount: Decimal = Decimal(0)
    lop_days: Decimal = Decimal(0)
    leave_deduction: Decimal = Decimal(0)

    model_config = {"from_attributes": True}


class PayrollRunOut(BaseModel):
    id: UUID
    month: int
    year: int
    status: str
    payslips: list[PayslipOut] = []
    # Set only by /process: how many employees had no deduction profile filled in by Finance (treated as 0%).
    employees_without_deductions: int = 0

    model_config = {"from_attributes": True}
