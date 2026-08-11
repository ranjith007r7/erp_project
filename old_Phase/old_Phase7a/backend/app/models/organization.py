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
