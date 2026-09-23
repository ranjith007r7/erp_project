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


class ReportSubscription(Base):
    """
    Real per-user opt-in for the weekly digest email - the previous
    version of this feature hardcoded "every user with the Admin role,"
    with no way for anyone to opt out, and no way for a non-Admin who
    wants visibility to opt in. One row = one subscribed user; deleting
    the row unsubscribes them, matching this project's "don't store what
    you can just not store" philosophy rather than an is_active flag
    that could drift.

    Deliberately NOT gated by role or any permission - unlike granting
    someone access to a module, choosing to receive (or not receive) a
    summary email about your own org is a personal preference, the same
    category as a notification setting, not an access-control decision.

    The org's original Admin (the one who signed up) gets a real row
    created automatically at signup, preserving today's exact behavior
    for brand-new orgs. Existing orgs' Admins are backfilled once via
    scripts/grandfather_report_subscriptions.py - same established
    pattern as scripts/grandfather_existing_users.py.
    """
    __tablename__ = "report_subscriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)
