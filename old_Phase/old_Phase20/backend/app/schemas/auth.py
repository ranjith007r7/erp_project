"""
Pydantic schemas define the *shape* of data going in and out of the API.
Think of these as the "form validation rules" — FastAPI automatically
rejects a request that doesn't match these shapes, before your own code
ever has to check for it.
"""
from pydantic import BaseModel, EmailStr, Field


class OrganizationSignup(BaseModel):
    """What a brand-new client sends to create their organization + first admin user."""
    org_name: str = Field(..., min_length=2, max_length=200)
    subdomain: str = Field(..., min_length=2, max_length=63, pattern=r"^[a-z0-9-]+$")
    admin_name: str = Field(..., min_length=2, max_length=200)
    admin_email: EmailStr
    admin_password: str = Field(..., min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8)


class VerifyEmailRequest(BaseModel):
    token: str


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class AcceptInviteRequest(BaseModel):
    token: str
    password: str = Field(..., min_length=8)


class UserOut(BaseModel):
    id: str
    name: str
    email: str
    org_id: str
    status: str
    email_verified: bool

    model_config = {"from_attributes": True}
