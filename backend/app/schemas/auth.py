"""
Pydantic schemas define the *shape* of data going in and out of the API.
Think of these as the "form validation rules" — FastAPI automatically
rejects a request that doesn't match these shapes, before your own code
ever has to check for it.
"""
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field


class OrganizationSignup(BaseModel):
    """What a brand-new client sends to create their organization + first admin user."""
    org_name: str = Field(..., min_length=2, max_length=200)
    subdomain: str = Field(..., min_length=2, max_length=63, pattern=r"^[a-z0-9-]+$")
    admin_name: str = Field(..., min_length=2, max_length=200)
    admin_email: EmailStr
    admin_password: str = Field(..., min_length=8)
    access_code: Optional[str] = Field(default=None, max_length=100)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    # Which sign-in page the person used. Administrators may only use "admin",
    # everyone else only "employee"; the server checks it against the account.
    portal: Literal["admin", "employee"]


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    # set by /signup: true when the new admin must click the emailed link before using the app
    email_verification_required: bool = False


class LoginResponse(BaseModel):
    """Either a finished login (access_token) or a next step the admin must complete."""
    access_token: Optional[str] = None
    token_type: str = "bearer"
    requires_totp: bool = False          # admin has an authenticator: ask for the 6-digit code
    requires_totp_setup: bool = False    # admin has none yet: enrol one now
    challenge_token: Optional[str] = None


class TotpVerifyIn(BaseModel):
    challenge_token: str
    code: str = Field(..., min_length=6, max_length=20)   # 6-digit code or a recovery code


class TotpSetupStartIn(BaseModel):
    challenge_token: str


class TotpSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class TotpSetupConfirmIn(BaseModel):
    challenge_token: str
    code: str = Field(..., min_length=6, max_length=10)


class TotpEnrolledOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    recovery_codes: list[str]


class SignupConfigOut(BaseModel):
    access_code_required: bool


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
    is_admin: bool = False
    role_name: Optional[str] = None
    org_name: Optional[str] = None
    # "module:action" strings the sidebar / menus use to show only what this person can open.
    permissions: list[str] = []

    model_config = {"from_attributes": True}
