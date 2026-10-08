from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class WorkCreate(BaseModel):
    client_name: str = Field(min_length=1, max_length=200)
    domain: Optional[str] = Field(default=None, max_length=120)
    client_details: Optional[str] = Field(default=None, max_length=4000)
    description: Optional[str] = Field(default=None, max_length=4000)
    quotation_amount: Decimal = Field(default=0, ge=0)
    vendor_amount: Decimal = Field(default=0, ge=0)
    discount_percent: Decimal = Field(default=0, ge=0, le=100)
    department_id: Optional[UUID] = None
    customer_id: Optional[UUID] = None


class WorkUpdate(BaseModel):
    client_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    domain: Optional[str] = Field(default=None, max_length=120)
    client_details: Optional[str] = Field(default=None, max_length=4000)
    description: Optional[str] = Field(default=None, max_length=4000)
    quotation_amount: Optional[Decimal] = Field(default=None, ge=0)
    vendor_amount: Optional[Decimal] = Field(default=None, ge=0)
    discount_percent: Optional[Decimal] = Field(default=None, ge=0, le=100)


class AllocateIn(BaseModel):
    department_id: UUID
    employee_id: Optional[UUID] = None


class DeliverIn(BaseModel):
    delivered_on: Optional[date] = None
    note: Optional[str] = Field(default=None, max_length=1000)
    from_stock: bool = False


class WorkPaymentIn(BaseModel):
    amount: Decimal = Field(gt=0)
    method: str
    transaction_id: Optional[str] = Field(default=None, max_length=64)
    note: Optional[str] = Field(default=None, max_length=300)
    paid_on: Optional[date] = None
