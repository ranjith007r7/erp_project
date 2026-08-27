from datetime import datetime
from uuid import UUID
from typing import Optional

from pydantic import BaseModel


class AuditLogOut(BaseModel):
    id: UUID
    user_id: Optional[UUID] = None
    user_name: Optional[str] = None
    action: str
    entity: str
    entity_id: Optional[UUID] = None
    created_at: datetime

    class Config:
        from_attributes = True
