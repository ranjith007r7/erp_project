from datetime import datetime
from typing import Optional, Any
from uuid import UUID

from pydantic import BaseModel, Field


class DocumentCreate(BaseModel):
    title: str = Field(..., min_length=1)
    file_url: str = Field(..., min_length=1)
    related_type: Optional[str] = None
    related_id: Optional[UUID] = None


class DocumentOut(BaseModel):
    id: UUID
    title: str
    file_url: Optional[str] = None
    storage_key: Optional[str] = None
    related_type: Optional[str] = None
    related_id: Optional[UUID] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentDownloadOut(BaseModel):
    url: str
    expires_in_seconds: int


class WorkflowStep(BaseModel):
    role: str


class ApprovalWorkflowCreate(BaseModel):
    name: str = Field(..., min_length=1)
    module: str = Field(..., min_length=1)
    steps: list[WorkflowStep] = Field(..., min_length=1)


class ApprovalWorkflowOut(BaseModel):
    id: UUID
    name: str
    module: str
    steps_config: Any

    model_config = {"from_attributes": True}


class ApprovalRequestCreate(BaseModel):
    workflow_id: UUID
    entity_type: str = Field(..., min_length=1)
    entity_id: UUID


class ApprovalStepOut(BaseModel):
    id: UUID
    step_order: int
    role_required: str
    approver_id: Optional[UUID] = None
    status: str
    acted_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ApprovalRequestOut(BaseModel):
    id: UUID
    workflow_id: UUID
    entity_type: str
    entity_id: UUID
    status: str
    created_at: datetime
    steps: list[ApprovalStepOut] = []

    model_config = {"from_attributes": True}


class ApprovalActionRequest(BaseModel):
    decision: str = Field(..., pattern="^(approve|reject)$")
