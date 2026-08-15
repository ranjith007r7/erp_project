from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel


class SavedReportCreate(BaseModel):
    name: str
    module: str  # "sales" / "finance" / "inventory" / "hr" / "procurement" / "crm"
    query_config: dict[str, Any] = {}


class SavedReportOut(BaseModel):
    id: UUID
    name: str
    module: str
    query_config: dict[str, Any]
    created_by: Optional[UUID] = None
    created_at: datetime

    model_config = {"from_attributes": True}
