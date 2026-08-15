from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


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
    date: date
    reference: Optional[str] = None
    description: Optional[str] = None
    lines: list[JournalLineOut] = []

    model_config = {"from_attributes": True}


class PaymentCreate(BaseModel):
    invoice_id: UUID
    amount: Decimal = Field(..., gt=0)
    method: str = "bank_transfer"


class PaymentOut(BaseModel):
    id: UUID
    invoice_id: UUID
    amount: Decimal
    method: str
    date: date

    model_config = {"from_attributes": True}
