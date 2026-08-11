import uuid
from datetime import datetime

from sqlalchemy import Column, String, ForeignKey, DateTime, Boolean
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class Notification(Base):
    """
    A single in-app alert for one user, e.g. 'Your leave request was approved.'
    Any module can create one of these by importing the small helper in
    app/services/notifications.py (added once we build the first module
    that actually needs to notify someone) instead of writing its own logic.
    """
    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    message = Column(String, nullable=False)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
