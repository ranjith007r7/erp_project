from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

import re

from pydantic import BaseModel, Field, field_validator


class AccountCreate(BaseModel):
    name: str = Field(..., min_length=1)
    industry: Optional[str] = None
    address: Optional[str] = None


class AccountOut(BaseModel):
    id: UUID
    name: str
    industry: Optional[str] = None
    address: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ContactCreate(BaseModel):
    account_id: Optional[UUID] = None
    name: str = Field(..., min_length=1)
    email: Optional[str] = None
    phone: Optional[str] = None


class ContactOut(BaseModel):
    id: UUID
    account_id: Optional[UUID] = None
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None

    model_config = {"from_attributes": True}


def clean_mobile(v: Optional[str]) -> Optional[str]:
    """Client mobile number: digits with an optional leading +, spaces, hyphens or brackets; 7 to 15 digits."""
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    if not re.fullmatch(r"\+?[0-9 ()\-]{7,24}", v) or not (7 <= len(re.sub(r"\D", "", v)) <= 15):
        raise ValueError("Enter a valid mobile number (7 to 15 digits, for example +91 98765 43210).")
    return v


class LeadCreate(BaseModel):
    name: str = Field(..., min_length=1)
    company_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None            # the client's mobile number
    source: Optional[str] = None
    estimated_amount: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("9999999999"))   # estimated quotation amount
    industry: Optional[str] = Field(default=None, max_length=120)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        return clean_mobile(v)


class LeadUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1)
    company_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    source: Optional[str] = None
    estimated_amount: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("9999999999"))
    industry: Optional[str] = Field(default=None, max_length=120)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        return clean_mobile(v)


class LeadOut(BaseModel):
    id: UUID
    name: str
    company_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    source: Optional[str] = None
    status: str
    estimated_amount: Optional[Decimal] = None
    industry: Optional[str] = None
    converted_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class LeadStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(new|contacted|qualified|converted|lost)$")


class OpportunityCreate(BaseModel):
    name: str = Field(..., min_length=1)
    account_id: Optional[UUID] = None
    contact_id: Optional[UUID] = None
    value: Decimal = Decimal("0")
    expected_close: Optional[date] = None


class OpportunityOut(BaseModel):
    id: UUID
    name: str
    account_id: Optional[UUID] = None
    contact_id: Optional[UUID] = None
    stage: str
    value: Decimal
    expected_close: Optional[date] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConvertedOut(OpportunityOut):
    """The new opportunity plus the Work it opened (None only if the Workpage module could not be reached)."""
    work_id: Optional[UUID] = None
    work_number: Optional[str] = None


class OpportunityStageUpdate(BaseModel):
    stage: str = Field(..., pattern="^(prospecting|proposal|negotiation|won|lost)$")


class ConvertLeadRequest(BaseModel):
    """What the frontend sends when turning a qualified Lead into a real Account + Opportunity."""
    opportunity_name: str = Field(..., min_length=1)
    opportunity_value: Decimal = Decimal("0")


class BulkDeleteRequest(BaseModel):
    ids: list[str] = Field(..., min_length=1, max_length=200)
