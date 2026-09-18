from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class VendorCreate(BaseModel):
    name: str = Field(..., min_length=1)
    contact: Optional[str] = None
    address: Optional[str] = None


class VendorOut(BaseModel):
    id: UUID
    name: str
    contact: Optional[str] = None
    address: Optional[str] = None

    model_config = {"from_attributes": True}


class PurchaseOrderItemIn(BaseModel):
    product_id: UUID
    qty: int = Field(..., gt=0)
    unit_price: Decimal


class PurchaseOrderItemOut(BaseModel):
    id: UUID
    product_id: UUID
    qty: int
    unit_price: Decimal

    model_config = {"from_attributes": True}


class PurchaseOrderCreate(BaseModel):
    vendor_id: UUID
    items: list[PurchaseOrderItemIn] = Field(..., min_length=1)


class PurchaseOrderOut(BaseModel):
    id: UUID
    vendor_id: UUID
    order_date: date
    status: str
    total: Decimal
    items: list[PurchaseOrderItemOut] = []

    model_config = {"from_attributes": True}
