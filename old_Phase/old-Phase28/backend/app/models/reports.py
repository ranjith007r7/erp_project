import uuid
from datetime import datetime

from sqlalchemy import Column, String, ForeignKey, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class SavedReport(Base):
    """
    A saved VIEW of a report, not a stored copy of its data. query_config
    holds whatever filters/parameters were chosen (e.g. {"months": 12} for
    the sales report) so re-opening a saved report re-runs the same live
    query against current data - same "never store what you can calculate"
    principle used for stock levels and dashboard counts everywhere else in
    this codebase. module identifies which report type this belongs to
    (e.g. "sales", "finance", "inventory", "hr", "procurement", "crm").
    """
    __tablename__ = "saved_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    name = Column(String, nullable=False)
    module = Column(String, nullable=False)
    query_config = Column(JSON, nullable=False, default=dict)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
