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
    Creates a login directly with an Admin-chosen password. Kept
    alongside the invite flow below (InviteCreate) rather than replaced
    by it - sometimes an Admin legitimately wants to set someone's
    password themselves (a quick test account, no email trust needed)
    rather than wait on an email round-trip.
    """
    name: str = Field(..., min_length=2)
    email: EmailStr
    password: str = Field(..., min_length=8)
    role_id: UUID | None = None


class InviteCreate(BaseModel):
    """
    Creates a pending user with NO usable password yet - a real
    verification-style email gets sent, and the invitee sets their own
    password by clicking through it. See AcceptInviteRequest in
    app/schemas/auth.py for the other half of this flow (that route is
    public, unlike this one, so it lives with signup/login instead).
    """
    name: str = Field(..., min_length=2)
    email: EmailStr
    role_id: UUID | None = None


class UserRoleUpdate(BaseModel):
    role_id: UUID | None = None


class BulkRoleAssignRequest(BaseModel):
    user_ids: list[UUID] = Field(..., min_length=1, max_length=200)
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
