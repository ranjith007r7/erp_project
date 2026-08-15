from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ProductCategoryCreate(BaseModel):
    name: str = Field(..., min_length=1)


class ProductCategoryOut(BaseModel):
    id: UUID
    name: str

    model_config = {"from_attributes": True}


class WarehouseOut(BaseModel):
    id: UUID
    name: str
    location: Optional[str] = None

    model_config = {"from_attributes": True}


class StockLevelOut(BaseModel):
    id: UUID
    product_id: UUID
    warehouse_id: UUID
    quantity: int

    model_config = {"from_attributes": True}


class StockMovementOut(BaseModel):
    id: UUID
    product_id: UUID
    movement_type: str
    qty: int
    ref_type: Optional[str] = None
    date: date

    model_config = {"from_attributes": True}
