"""
Two separate concerns, two separate schema groups:
- CustomField* — the DEFINITION (an admin saying "Products have a Batch
  Number field, it's text, it's required").
- CustomFieldValue* — one ACTUAL value on one ACTUAL record (this specific
  product's Batch Number is "BN-2201").

Kept split because they're managed on different screens by different
people at different times — Settings (admin, rare) vs. the record's own
form (any user, every save).
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, field_validator

ALLOWED_FIELD_TYPES = {"text", "number", "date", "dropdown"}


class CustomFieldCreate(BaseModel):
    module: str
    entity_type: str
    field_name: str
    field_type: str
    options: Optional[str] = None   # required in practice when field_type == "dropdown"
    is_required: bool = False
    display_order: int = 0

    @field_validator("field_type")
    @classmethod
    def validate_field_type(cls, v: str) -> str:
        if v not in ALLOWED_FIELD_TYPES:
            raise ValueError(f"field_type must be one of {sorted(ALLOWED_FIELD_TYPES)}")
        return v


class CustomFieldUpdate(BaseModel):
    field_name: Optional[str] = None
    options: Optional[str] = None
    is_required: Optional[bool] = None
    is_active: Optional[bool] = None
    display_order: Optional[int] = None


class CustomFieldOut(BaseModel):
    id: UUID
    org_id: UUID
    module: str
    entity_type: str
    field_name: str
    field_type: str
    options: Optional[str] = None
    is_required: bool
    is_active: bool
    display_order: int
    created_at: datetime

    class Config:
        from_attributes = True


class CustomFieldValueIn(BaseModel):
    """One field's value, submitted as part of a bulk save for a record."""
    custom_field_id: UUID
    value: Optional[str] = None


class CustomFieldValuesSetRequest(BaseModel):
    """
    Bulk-set every custom field value for one record in a single call —
    the frontend's <CustomFieldsSection> always saves the whole section
    at once, not field-by-field, so the API mirrors that.
    """
    entity_type: str
    entity_id: UUID
    values: list[CustomFieldValueIn]


class CustomFieldValueOut(BaseModel):
    custom_field_id: UUID
    field_name: str
    field_type: str
    value: Optional[str] = None

    class Config:
        from_attributes = True
