from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.hr import LeaveTypeOut  # noqa: F401  (re-exported for the Finance leave legend)


class AccountOut(BaseModel):
    id: UUID
    code: str
    name: str
    account_type: str

    model_config = {"from_attributes": True}


class JournalLineOut(BaseModel):
    id: UUID
    account_id: UUID
    debit: Decimal
    credit: Decimal

    model_config = {"from_attributes": True}


class JournalEntryOut(BaseModel):
    id: UUID
    entry_number: Optional[str] = None
    date: date
    reference: Optional[str] = None
    description: Optional[str] = None
    lines: list[JournalLineOut] = []

    model_config = {"from_attributes": True}


PAYMENT_METHODS = ("cash", "card", "gpay", "bank_transfer")
METHODS_NEEDING_REFERENCE = ("card", "gpay", "bank_transfer")


class PaymentCreate(BaseModel):
    invoice_id: UUID
    amount: Decimal = Field(..., gt=0)
    method: str = Field("cash", pattern="^(cash|card|gpay|bank_transfer)$")
    # Required for card, gpay and bank_transfer (checked in the route so the
    # message can name the method); ignored for cash.
    transaction_id: Optional[str] = Field(None, max_length=64)


class PaymentOut(BaseModel):
    id: UUID
    invoice_id: UUID
    amount: Decimal
    method: str
    transaction_id: Optional[str] = None
    date: date

    model_config = {"from_attributes": True}


# ---------------- Payroll deductions (filled by Finance) ----------------
class DeductionProfileIn(BaseModel):
    pf_percent: Decimal = Field(0, ge=0, le=100)
    insurance_percent: Decimal = Field(0, ge=0, le=100)
    tds_percent: Decimal = Field(0, ge=0, le=100)


class DeductionRow(BaseModel):
    employee_id: UUID
    employee_code: Optional[str] = None
    name: str
    designation: Optional[str] = None
    salary: Decimal
    configured: bool                 # False = Finance has not filled this employee in yet
    pf_percent: Decimal
    insurance_percent: Decimal
    tds_percent: Decimal
    lop_days: Optional[Decimal] = None   # only when a payroll run is selected


class LopIn(BaseModel):
    lop_days: Decimal = Field(0, ge=0, le=31)


class RunSummary(BaseModel):
    id: UUID
    month: int
    year: int
    status: str

    model_config = {"from_attributes": True}
