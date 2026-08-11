import uuid
from datetime import datetime, date

from sqlalchemy import Column, String, ForeignKey, DateTime, Date, Numeric
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class Project(Base):
    """
    client_account_id optionally links back to a CRM Account - lets a
    services-oriented org tie a project to the client it's being done
    for, without requiring every project to have one (internal projects
    have no client).
    """
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    name = Column(String, nullable=False)
    client_account_id = Column(UUID(as_uuid=True), ForeignKey("crm_accounts.id"), nullable=True)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    status = Column(String, default="active")  # active / completed / on_hold


class Task(Base):
    __tablename__ = "tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    title = Column(String, nullable=False)
    assigned_to = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    due_date = Column(Date, nullable=True)
    status = Column(String, default="todo")     # todo / in_progress / done
    priority = Column(String, default="medium")  # low / medium / high


class TimeLog(Base):
    """
    Hours logged against a task. This is deliberately NOT wired into
    Finance yet (e.g. auto-billing a client for logged hours) - that's a
    reasonable Reports/Finance enhancement once real billing rules exist,
    not a Phase 6 fundamental.
    """
    __tablename__ = "time_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    hours = Column(Numeric(5, 2), nullable=False)
    date = Column(Date, default=date.today)
    created_at = Column(DateTime, default=datetime.utcnow)
