from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


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


class LeadCreate(BaseModel):
    name: str = Field(..., min_length=1)
    company_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    source: Optional[str] = None


class LeadOut(BaseModel):
    id: UUID
    name: str
    company_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    source: Optional[str] = None
    status: str
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


class OpportunityStageUpdate(BaseModel):
    stage: str = Field(..., pattern="^(prospecting|proposal|negotiation|won|lost)$")


class ConvertLeadRequest(BaseModel):
    """What the frontend sends when turning a qualified Lead into a real Account + Opportunity."""
    opportunity_name: str = Field(..., min_length=1)
    opportunity_value: Decimal = Decimal("0")
