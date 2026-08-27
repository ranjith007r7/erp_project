import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime
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
