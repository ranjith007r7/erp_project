from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class StockBatchIn(BaseModel):
    product_id: UUID
    quantity: int = Field(ge=1, le=10_000_000)
    vendor_name: str = Field(min_length=1, max_length=200)
    vendor_amount: Decimal = Field(ge=0, le=Decimal("99999999"))      # rate bought at, per unit
    mrp: Decimal = Field(gt=0, le=Decimal("99999999"))                # most it can be sold for, per unit
    max_discount_percent: Decimal = Field(ge=0, le=100)
    inward_date: Optional[date] = None                                  # defaults to today
    manufacture_month: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}(-\d{2})?$")
    expiry_date: Optional[date] = None
    already_in_inventory: bool = False
    note: Optional[str] = Field(default=None, max_length=500)


class StockBatchUpdate(BaseModel):
    vendor_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    vendor_amount: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("99999999"))
    mrp: Optional[Decimal] = Field(default=None, gt=0, le=Decimal("99999999"))
    max_discount_percent: Optional[Decimal] = Field(default=None, ge=0, le=100)
    inward_date: Optional[date] = None
    manufacture_month: Optional[str] = Field(default=None, pattern=r"^(\d{4}-\d{2}(-\d{2})?)?$")
    expiry_date: Optional[date] = None
    note: Optional[str] = Field(default=None, max_length=500)
