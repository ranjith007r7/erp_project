from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ProductCreate(BaseModel):
    name: str = Field(..., min_length=1)
    unit_price: Decimal = Decimal("0")
    sku: Optional[str] = None
    category_id: Optional[UUID] = None
    reorder_level: int = 0
    cgst_percent: Decimal = Field(Decimal("0"), ge=0, le=50)
    sgst_percent: Decimal = Field(Decimal("0"), ge=0, le=50)
    hsn_code: Optional[str] = None


class ProductUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1)
    unit_price: Optional[Decimal] = Field(None, ge=0)
    sku: Optional[str] = None
    reorder_level: Optional[int] = Field(None, ge=0)
    cgst_percent: Optional[Decimal] = Field(None, ge=0, le=50)
    sgst_percent: Optional[Decimal] = Field(None, ge=0, le=50)
    hsn_code: Optional[str] = None


class ProductOut(BaseModel):
    id: UUID
    name: str
    unit_price: Decimal
    sku: Optional[str] = None
    category_id: Optional[UUID] = None
    reorder_level: int
    cgst_percent: Decimal = Decimal("0")
    sgst_percent: Decimal = Decimal("0")
    hsn_code: Optional[str] = None

    model_config = {"from_attributes": True}


class CustomerCreate(BaseModel):
    name: str = Field(..., min_length=1)
    account_id: Optional[UUID] = None
    billing_address: Optional[str] = None
    gst_number: Optional[str] = None


class CustomerOut(BaseModel):
    id: UUID
    name: str
    account_id: Optional[UUID] = None
    billing_address: Optional[str] = None
    gst_number: Optional[str] = None

    model_config = {"from_attributes": True}


class QuotationItemIn(BaseModel):
    product_id: UUID
    qty: int = Field(..., gt=0)
    unit_price: Decimal                      # excludes GST
    cgst_percent: Optional[Decimal] = Field(None, ge=0, le=50)   # left out = the product's rate
    sgst_percent: Optional[Decimal] = Field(None, ge=0, le=50)


class QuotationItemOut(BaseModel):
    id: UUID
    product_id: UUID
    qty: int
    unit_price: Decimal
    cgst_percent: Decimal = Decimal("0")
    sgst_percent: Decimal = Decimal("0")

    model_config = {"from_attributes": True}


class QuotationCreate(BaseModel):
    customer_id: UUID
    opportunity_id: Optional[UUID] = None
    items: list[QuotationItemIn] = Field(..., min_length=1)


class QuotationOut(BaseModel):
    id: UUID
    customer_id: UUID
    opportunity_id: Optional[UUID] = None
    total: Decimal                           # grand total, GST included
    subtotal: Decimal = Decimal("0")
    cgst_amount: Decimal = Decimal("0")
    sgst_amount: Decimal = Decimal("0")
    status: str
    created_at: datetime
    items: list[QuotationItemOut] = []

    model_config = {"from_attributes": True}


class QuotationStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(draft|sent|accepted|rejected)$")


class SalesOrderItemOut(BaseModel):
    id: UUID
    product_id: UUID
    qty: int
    unit_price: Decimal
    cgst_percent: Decimal = Decimal("0")
    sgst_percent: Decimal = Decimal("0")

    model_config = {"from_attributes": True}


class SalesOrderOut(BaseModel):
    id: UUID
    customer_id: UUID
    quotation_id: Optional[UUID] = None
    order_date: date
    status: str
    total: Decimal
    subtotal: Decimal = Decimal("0")
    cgst_amount: Decimal = Decimal("0")
    sgst_amount: Decimal = Decimal("0")
    items: list[SalesOrderItemOut] = []

    model_config = {"from_attributes": True}


class InvoiceOut(BaseModel):
    id: UUID
    order_id: UUID
    customer_id: UUID
    amount: Decimal
    invoice_number: Optional[str] = None
    subtotal: Decimal = Decimal("0")
    cgst_amount: Decimal = Decimal("0")
    sgst_amount: Decimal = Decimal("0")
    paid_amount: Decimal = Decimal("0")
    balance: Decimal = Decimal("0")
    document_ready: bool = False        # true once a payment exists: the printable tax invoice can be downloaded
    due_date: Optional[date] = None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
