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


class EmployeeCreate(BaseModel):
    name: str = Field(..., min_length=1)
    designation: Optional[str] = None
    department_id: Optional[UUID] = None
    joining_date: Optional[date] = None
    salary: Decimal = Decimal("0")
    user_id: Optional[UUID] = None


class EmployeeOut(BaseModel):
    id: UUID
    name: str
    designation: Optional[str] = None
    department_id: Optional[UUID] = None
    joining_date: Optional[date] = None
    salary: Decimal
    status: str
    user_id: Optional[UUID] = None

    model_config = {"from_attributes": True}


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

    model_config = {"from_attributes": True}


class PayrollRunOut(BaseModel):
    id: UUID
    month: int
    year: int
    status: str
    payslips: list[PayslipOut] = []

    model_config = {"from_attributes": True}
