from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class RoleCreate(BaseModel):
    name: str = Field(..., min_length=1)


class RoleOut(BaseModel):
    id: UUID
    org_id: UUID
    name: str

    class Config:
        from_attributes = True


class PermissionCreate(BaseModel):
    module: str = Field(..., min_length=1)
    action: str = Field(..., pattern="^(view|create|edit|delete|approve|manage_access)$")


class PermissionOut(BaseModel):
    id: UUID
    role_id: UUID
    module: str
    action: str

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    """
    Creates a login directly with a password, rather than an email-invite
    flow — there's no outbound email sending anywhere in this codebase
    yet (that's Phase 13, security/production hardening). Same tradeoff
    signup itself already makes.
    """
    name: str = Field(..., min_length=2)
    email: EmailStr
    password: str = Field(..., min_length=8)
    role_id: UUID | None = None


class UserRoleUpdate(BaseModel):
    role_id: UUID | None = None


class UserManagementOut(BaseModel):
    id: UUID
    name: str
    email: str
    role_id: UUID | None = None
    role_name: str | None = None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True
