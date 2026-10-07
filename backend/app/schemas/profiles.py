import re
from datetime import date
from typing import Optional
from zoneinfo import ZoneInfo, available_timezones

from pydantic import BaseModel, ConfigDict, EmailStr, Field, TypeAdapter, field_validator

_email = TypeAdapter(EmailStr)
_PHONE = re.compile(r"^\+?[0-9][0-9 \-()]{5,18}$")


def _clean(v):
    if v is None:
        return None
    v = str(v).strip()
    return v or None


def _opt_email(v):
    v = _clean(v)
    return str(_email.validate_python(v)).lower() if v else None


def _opt_phone(v):
    v = _clean(v)
    if v and not _PHONE.match(v):
        raise ValueError("Enter a valid phone number (digits, +, spaces, - and brackets only).")
    return v


class OrgProfileUpdate(BaseModel):
    """Every field optional: only the ones sent are changed. Empty text clears a field."""
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, max_length=120)            # the organization's display name
    legal_name: Optional[str] = Field(None, max_length=160)
    industry: Optional[str] = Field(None, max_length=80)
    company_size: Optional[str] = Field(None, pattern=r"^(1-10|11-50|51-200|201-500|501-1000|1000\+)$")
    founded_on: Optional[date] = None
    description: Optional[str] = Field(None, max_length=1000)
    website: Optional[str] = Field(None, max_length=200)
    owner_name: Optional[str] = Field(None, max_length=120)
    owner_designation: Optional[str] = Field(None, max_length=80)
    owner_email: Optional[str] = None
    owner_phone: Optional[str] = None
    company_email: Optional[str] = None
    company_phone: Optional[str] = None
    support_email: Optional[str] = None
    support_phone: Optional[str] = None
    address_line1: Optional[str] = Field(None, max_length=160)
    address_line2: Optional[str] = Field(None, max_length=160)
    city: Optional[str] = Field(None, max_length=80)
    state: Optional[str] = Field(None, max_length=80)
    postal_code: Optional[str] = Field(None, max_length=12)
    country: Optional[str] = Field(None, max_length=80)
    gstin: Optional[str] = None
    pan: Optional[str] = None
    cin: Optional[str] = None
    registration_number: Optional[str] = Field(None, max_length=60)
    fiscal_year_start_month: Optional[int] = Field(None, ge=1, le=12)
    currency: Optional[str] = None
    timezone: Optional[str] = None

    @field_validator("owner_email", "company_email", "support_email", mode="before")
    @classmethod
    def _emails(cls, v):
        try:
            return _opt_email(v)
        except Exception:
            raise ValueError("Enter a valid email address.")

    @field_validator("owner_phone", "company_phone", "support_phone", mode="before")
    @classmethod
    def _phones(cls, v):
        return _opt_phone(v)

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, v):
        v = _clean(v)
        if v is not None and len(v) < 2:
            raise ValueError("Organization name must be at least 2 characters.")
        return v

    @field_validator("legal_name", "industry", "description", "owner_name", "owner_designation", "address_line1", "address_line2",
                     "city", "state", "country", "registration_number", mode="before")
    @classmethod
    def _text(cls, v):
        return _clean(v)

    @field_validator("website", mode="before")
    @classmethod
    def _website(cls, v):
        v = _clean(v)
        if not v:
            return None
        if not re.match(r"^https?://", v, re.I):
            v = "https://" + v
        if not re.match(r"^https?://[^\s/]+\.[^\s/]+(/\S*)?$", v, re.I):
            raise ValueError("Enter a valid website address.")
        return v

    @field_validator("postal_code", mode="before")
    @classmethod
    def _postal(cls, v):
        v = _clean(v)
        if v and not re.match(r"^[A-Za-z0-9 \-]{3,12}$", v):
            raise ValueError("Enter a valid postal / PIN code.")
        return v

    @field_validator("gstin", mode="before")
    @classmethod
    def _gstin(cls, v):
        v = (_clean(v) or "").upper() or None
        if v and not re.match(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$", v):
            raise ValueError("GSTIN must be 15 characters, e.g. 33ABCDE1234F1Z5.")
        return v

    @field_validator("pan", mode="before")
    @classmethod
    def _pan(cls, v):
        v = (_clean(v) or "").upper() or None
        if v and not re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", v):
            raise ValueError("PAN must be 10 characters, e.g. ABCDE1234F.")
        return v

    @field_validator("cin", mode="before")
    @classmethod
    def _cin(cls, v):
        v = (_clean(v) or "").upper() or None
        if v and not re.match(r"^[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$", v):
            raise ValueError("CIN must be 21 characters, e.g. U12345TN2020PTC123456.")
        return v

    @field_validator("currency", mode="before")
    @classmethod
    def _currency(cls, v):
        v = (_clean(v) or "").upper() or None
        if v and not re.match(r"^[A-Z]{3}$", v):
            raise ValueError("Currency must be a 3-letter code such as INR.")
        return v

    @field_validator("timezone", mode="before")
    @classmethod
    def _tz(cls, v):
        v = _clean(v)
        if v and v not in available_timezones():
            raise ValueError("Unknown time zone. Use a name like Asia/Kolkata.")
        return v

    @field_validator("founded_on")
    @classmethod
    def _founded(cls, v):
        if v and v > date.today():
            raise ValueError("Founding date cannot be in the future.")
        return v


class MyProfileUpdate(BaseModel):
    """What a person may change about themselves. Everything else (code, department, role, salary, joining date, status) is HR's."""
    model_config = ConfigDict(extra="forbid")

    otp: str = Field(..., min_length=6, max_length=6)
    name: Optional[str] = Field(None, max_length=120)
    phone: Optional[str] = None
    personal_email: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = Field(None, pattern="^(male|female|other)$")
    address: Optional[str] = Field(None, max_length=500)
    emergency_contact_name: Optional[str] = Field(None, max_length=120)
    emergency_contact_phone: Optional[str] = None

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, v):
        v = _clean(v)
        if v is not None and len(v) < 2:
            raise ValueError("Name must be at least 2 characters.")
        return v

    @field_validator("phone", "emergency_contact_phone", mode="before")
    @classmethod
    def _phones(cls, v):
        return _opt_phone(v)

    @field_validator("personal_email", mode="before")
    @classmethod
    def _pe(cls, v):
        try:
            return _opt_email(v)
        except Exception:
            raise ValueError("Enter a valid email address.")

    @field_validator("address", "emergency_contact_name", mode="before")
    @classmethod
    def _text(cls, v):
        return _clean(v)

    @field_validator("date_of_birth")
    @classmethod
    def _dob(cls, v):
        if v and (v >= date.today() or v.year < 1900):
            raise ValueError("Enter a valid date of birth.")
        return v


class OtpRequestIn(BaseModel):
    pass
