from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class VendorCreate(BaseModel):
    name: str = Field(..., min_length=1)
    contact: Optional[str] = None
    address: Optional[str] = None
    email: Optional[str] = None


class VendorUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1)
    contact: Optional[str] = None
    address: Optional[str] = None
    email: Optional[str] = None


class VendorOut(BaseModel):
    id: UUID
    name: str
    contact: Optional[str] = None
    address: Optional[str] = None
    email: Optional[str] = None

    model_config = {"from_attributes": True}


class PurchaseOrderItemIn(BaseModel):
    product_id: UUID
    qty: int = Field(..., gt=0)
    unit_price: Decimal = Field(..., ge=0)


class PurchaseOrderItemOut(BaseModel):
    id: UUID
    product_id: UUID
    product_name: Optional[str] = None
    qty: int
    unit_price: Decimal
    line_total: Decimal

    model_config = {"from_attributes": True}


class PurchaseOrderCreate(BaseModel):
    vendor_id: UUID
    items: list[PurchaseOrderItemIn] = Field(..., min_length=1)
    work_order_id: Optional[UUID] = None   # the customer work this PO is bought for (optional)


class ReceiptFileOut(BaseModel):
    id: UUID
    kind: str
    filename: str
    content_type: str
    size: int


class ReceiptOut(BaseModel):
    id: UUID
    condition: str
    notes: Optional[str] = None
    received_date: Optional[date] = None
    received_by_name: Optional[str] = None
    files: list[ReceiptFileOut] = []


class PurchaseOrderOut(BaseModel):
    id: UUID
    po_number: Optional[str] = None
    vendor_id: UUID
    vendor_name: Optional[str] = None
    order_date: date
    status: str                       # pending / received / defective / cancelled
    approval_status: str              # pending / approved / rejected
    total: Decimal
    created_by_name: Optional[str] = None
    created_by_email: Optional[str] = None
    approved_by_name: Optional[str] = None
    approved_at: Optional[datetime] = None
    work_order_id: Optional[UUID] = None
    items: list[PurchaseOrderItemOut] = []
    receipts: list[ReceiptOut] = []


class EmailPreviewOut(BaseModel):
    from_name: str
    to_name: str
    to_email: Optional[str] = None
    subject: str
    body: str
    attachments: list[str] = []


class SendEmailIn(BaseModel):
    to_email: str = Field(..., min_length=3)
    # Optional extra line the buyer may add above the standard body. The
    # template itself stays common to every vendor.
    note: Optional[str] = Field(None, max_length=1000)


class SendEmailOut(BaseModel):
    status: str        # sent / logged
    to_email: str
    subject: str
    message: str
