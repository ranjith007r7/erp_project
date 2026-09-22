from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1)
    client_account_id: Optional[UUID] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class ProjectOut(BaseModel):
    id: UUID
    name: str
    client_account_id: Optional[UUID] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: str

    model_config = {"from_attributes": True}


class ProjectStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(active|completed|on_hold)$")


class TaskCreate(BaseModel):
    project_id: UUID
    title: str = Field(..., min_length=1)
    assigned_to: Optional[UUID] = None
    due_date: Optional[date] = None
    priority: str = Field("medium", pattern="^(low|medium|high)$")


class TaskOut(BaseModel):
    id: UUID
    project_id: UUID
    title: str
    assigned_to: Optional[UUID] = None
    due_date: Optional[date] = None
    status: str
    priority: str

    model_config = {"from_attributes": True}


class TaskStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(todo|in_progress|done)$")


class TimeLogCreate(BaseModel):
    task_id: UUID
    hours: Decimal = Field(..., gt=0)
    date: Optional[date] = None


class TimeLogOut(BaseModel):
    id: UUID
    task_id: UUID
    user_id: UUID
    hours: Decimal
    date: date

    model_config = {"from_attributes": True}
