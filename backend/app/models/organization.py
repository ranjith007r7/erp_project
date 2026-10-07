import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Date, Integer, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class Organization(Base):
    """
    One row per client company using this ERP ("tenant").
    Every other table in the whole system eventually points back to one
    of these via an org_id column — this is the foundation of multi-tenancy.
    """
    __tablename__ = "organizations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    subdomain = Column(String, unique=True, nullable=False)
    plan = Column(String, default="trial")       # trial / basic / pro etc.
    status = Column(String, default="active")    # active / suspended
    created_at = Column(DateTime, default=datetime.utcnow)

    # --- Org-wide branding (logo/background image, admin-controlled,
    # visible to every member of this org) ---
    # A storage KEY, not a URL - the actual image lives in Cloudflare R2
    # (same service Documents uses, see app/services/storage.py). A
    # presigned URL is generated fresh on request rather than stored,
    # matching the same reasoning as Documents - the URL itself expires,
    # so persisting one would just mean it silently breaks later. Unlike
    # Documents, this isn't treated as sensitive (a logo/background is
    # inherently a "shown to everyone in the org" asset, not a private
    # business record), but the SAME upload/presigned-URL mechanism is
    # reused rather than standing up a second storage pattern for one
    # feature.
    branding_storage_key = Column(String, nullable=True)


class OrganizationProfile(Base):
    """
    The company's own details (owner, contacts, address, tax ids, locale).
    One row per organization, created on the first save. Admins edit it;
    every member can read it. Kept separate from `organizations` so that
    table stays the tiny tenant anchor every other table points at.
    """
    __tablename__ = "organization_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, unique=True)
    legal_name = Column(String, nullable=True)
    industry = Column(String, nullable=True)
    company_size = Column(String, nullable=True)
    founded_on = Column(Date, nullable=True)
    description = Column(Text, nullable=True)
    website = Column(String, nullable=True)
    owner_name = Column(String, nullable=True)
    owner_designation = Column(String, nullable=True)
    owner_email = Column(String, nullable=True)
    owner_phone = Column(String, nullable=True)
    company_email = Column(String, nullable=True)
    company_phone = Column(String, nullable=True)
    support_email = Column(String, nullable=True)
    support_phone = Column(String, nullable=True)
    address_line1 = Column(String, nullable=True)
    address_line2 = Column(String, nullable=True)
    city = Column(String, nullable=True)
    state = Column(String, nullable=True)
    postal_code = Column(String, nullable=True)
    country = Column(String, nullable=True)
    gstin = Column(String, nullable=True)
    pan = Column(String, nullable=True)
    cin = Column(String, nullable=True)
    registration_number = Column(String, nullable=True)
    fiscal_year_start_month = Column(Integer, nullable=True)
    currency = Column(String, nullable=True)
    timezone = Column(String, nullable=True)
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow)
