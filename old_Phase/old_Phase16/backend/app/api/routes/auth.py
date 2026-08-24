"""
Auth endpoints: signup, login (with rate limiting), password reset,
email verification. See app/services/email.py for why "email" here means
"logged to console", not actually delivered — no provider is configured.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    hash_password, verify_password, create_access_token,
    generate_one_time_token, hash_token,
)
from app.models.organization import Organization
from app.models.role import Role, Permission
from app.models.user import User
from app.schemas.auth import (
    OrganizationSignup, LoginRequest, TokenResponse, UserOut,
    ForgotPasswordRequest, ResetPasswordRequest, VerifyEmailRequest, ResendVerificationRequest,
)
from app.api.deps import get_current_user
from app.services.accounting import seed_default_accounts
from app.services.email import send_password_reset_email, send_verification_email

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _issue_verification_token(db: Session, user: User) -> None:
    """
    The one place a fresh verification token gets generated and emailed -
    called by both signup (a user's first token) and resend-verification
    (a replacement one). Overwriting verification_token_hash here is what
    makes a fresh token implicitly invalidate whatever token came before
    it: only one hash can be "the current one" at a time, so the old
    link stops working the moment a new one is issued, with no separate
    invalidation step needed.
    """
    raw_token, token_hash = generate_one_time_token()
    user.verification_token_hash = token_hash
    user.verification_token_expires = datetime.now(timezone.utc) + timedelta(hours=settings.VERIFICATION_TOKEN_EXPIRE_HOURS)
    user.last_verification_email_sent_at = datetime.now(timezone.utc)
    send_verification_email(user.email, raw_token)


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: OrganizationSignup, db: Session = Depends(get_db)):
    # Subdomain must be unique across ALL organizations - it's how we'll
    # eventually route "clientname.yourapp.com" to the right tenant.
    existing_org = db.query(Organization).filter(Organization.subdomain == payload.subdomain).first()
    if existing_org:
        raise HTTPException(status_code=400, detail="That subdomain is already taken.")

    existing_user = db.query(User).filter(User.email == payload.admin_email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="That email is already registered.")

    # 1. Create the organization (the tenant).
    org = Organization(name=payload.org_name, subdomain=payload.subdomain)
    db.add(org)
    db.flush()  # lets us use org.id below without a full commit yet

    # 2. Create a default "Admin" role for this org, with full access.
    admin_role = Role(org_id=org.id, name="Admin")
    db.add(admin_role)
    db.flush()

    # Full-access permission per module we currently have. As new modules
    # are added later, add their names to this list so a fresh org's Admin
    # role automatically has access to everything from day one.
    modules = ["core", "dashboard", "crm", "sales", "procurement", "inventory",
               "finance", "hr", "projects", "documents", "reports", "custom_fields"]
    for module in modules:
        for action in ["view", "create", "edit", "delete", "approve"]:
            db.add(Permission(role_id=admin_role.id, module=module, action=action))

    # manage_access is deliberately separate from the loop above - it's
    # not a generic per-module action, it's the single capability that
    # controls the permission system itself (see app/api/deps.py). Every
    # brand-new org's Admin gets it immediately; existing orgs self-heal
    # it on first use of a manage_access-gated route.
    db.add(Permission(role_id=admin_role.id, module="core", action="manage_access"))

    # 3. Create the first user, as that org's Admin. email_verified
    #    starts False; a verification token is issued below.
    admin_user = User(
        org_id=org.id,
        name=payload.admin_name,
        email=payload.admin_email,
        password_hash=hash_password(payload.admin_password),
        role_id=admin_role.id,
    )
    db.add(admin_user)

    # 4. Seed a minimal default Chart of Accounts, so Finance isn't empty
    #    the moment this organization exists - see app/services/accounting.py
    seed_default_accounts(db, org.id)

    db.flush()  # admin_user needs a real id before _issue_verification_token touches it
    _issue_verification_token(db, admin_user)

    db.commit()
    db.refresh(admin_user)

    token = create_access_token({
        "sub": str(admin_user.id),
        "org_id": str(org.id),
        "role": "Admin",
    })
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()

    # Deliberately vague error message - never reveal whether the email
    # or the password was the wrong part, that helps attackers guess.
    invalid_error = HTTPException(status_code=401, detail="Incorrect email or password.")

    # Lockout check happens BEFORE password verification - a locked
    # account should reject even the CORRECT password until the lockout
    # window passes, otherwise "rate limiting" wouldn't actually rate-limit.
    now = datetime.now(timezone.utc)
    if user and user.locked_until:
        locked_until = user.locked_until if user.locked_until.tzinfo else user.locked_until.replace(tzinfo=timezone.utc)
        if locked_until > now:
            remaining_seconds = int((locked_until - now).total_seconds())
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many failed login attempts. Try again in {max(1, remaining_seconds // 60)} minute(s).",
            )

    if not user or not verify_password(payload.password, user.password_hash):
        if user:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= settings.MAX_FAILED_LOGIN_ATTEMPTS:
                user.locked_until = now + timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
            db.commit()
        raise invalid_error

    if user.status != "active":
        raise HTTPException(status_code=403, detail="This account has been disabled.")

    # Enforced only now that real email delivery exists (Resend, added
    # after Phase 13). Every account created BEFORE this point was
    # grandfathered to email_verified=True by a one-time script (see
    # scripts/grandfather_existing_users.py) specifically so this check
    # doesn't lock out anyone who never had a real link to click -
    # this only blocks accounts created from now on, who do.
    if not user.email_verified:
        raise HTTPException(
            status_code=403,
            detail="Please verify your email before logging in. Check your inbox for the verification "
                   "link, or use 'Resend verification email' if you can't find it.",
        )

    # Successful login clears any prior failed attempts / lockout.
    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()

    role_name = user.role.name if user.role else None
    token = create_access_token({
        "sub": str(user.id),
        "org_id": str(user.org_id),
        "role": role_name,
    })
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    return UserOut(
        id=str(current_user.id),
        name=current_user.name,
        email=current_user.email,
        org_id=str(current_user.org_id),
        status=current_user.status,
        email_verified=current_user.email_verified,
    )


@router.post("/forgot-password", status_code=200)
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """
    Always returns the same generic response, whether or not the email
    exists - the alternative (a different message for "email not found")
    lets an attacker enumerate which emails have accounts on this system.
    """
    user = db.query(User).filter(User.email == payload.email).first()
    if user:
        raw_token, hashed = generate_one_time_token()
        user.reset_token_hash = hashed
        user.reset_token_expires = datetime.now(timezone.utc) + timedelta(minutes=settings.RESET_TOKEN_EXPIRE_MINUTES)
        db.commit()
        send_password_reset_email(user.email, raw_token)

    return {"message": "If that email has an account, a password reset link has been sent."}


@router.post("/reset-password", status_code=200)
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    hashed = hash_token(payload.token)
    user = db.query(User).filter(User.reset_token_hash == hashed).first()

    if not user or not user.reset_token_expires:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token.")

    expires = user.reset_token_expires if user.reset_token_expires.tzinfo else user.reset_token_expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Invalid or expired reset token.")

    user.password_hash = hash_password(payload.new_password)
    # Invalidate the token immediately - a reset link is single-use.
    user.reset_token_hash = None
    user.reset_token_expires = None
    # A password reset is also a good moment to clear any lockout - the
    # person has just proven account ownership via their email.
    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()

    return {"message": "Password has been reset. You can now log in with your new password."}


@router.post("/verify-email", status_code=200)
def verify_email(payload: VerifyEmailRequest, db: Session = Depends(get_db)):
    hashed = hash_token(payload.token)
    user = db.query(User).filter(User.verification_token_hash == hashed).first()

    if not user or not user.verification_token_expires:
        raise HTTPException(status_code=400, detail="Invalid or expired verification token.")

    expires = user.verification_token_expires if user.verification_token_expires.tzinfo else user.verification_token_expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Invalid or expired verification token.")

    user.email_verified = True
    user.verification_token_hash = None
    user.verification_token_expires = None
    db.commit()

    return {"message": "Email verified."}


RESEND_VERIFICATION_COOLDOWN_SECONDS = 60


@router.post("/resend-verification", status_code=200)
def resend_verification(payload: ResendVerificationRequest, db: Session = Depends(get_db)):
    """
    Real gap this closes: before this route existed, a user whose
    original verification link expired (24h), landed in spam, or was
    just closed without clicking, had NO self-service way back in - the
    only path was someone manually updating the database. Not something
    a real end user should ever need a developer to fix for them.

    Same anti-enumeration shape as forgot-password: ALWAYS returns the
    identical generic message, whether the email doesn't exist, is
    already verified, or genuinely gets a fresh email - none of those
    three real states are distinguishable from the response.

    Rate limited via last_verification_email_sent_at rather than a
    request-counting scheme like login's lockout - this only needs to
    stop rapid-fire re-triggering (someone mashing "resend" or a script
    hammering an arbitrary email), not track a security-relevant
    attempt count the way wrong-password attempts do. A flat cooldown
    is the simpler, sufficient tool for that job.
    """
    user = db.query(User).filter(User.email == payload.email).first()

    generic_response = {"message": "If that email needs verification, a new link has been sent."}

    if not user or user.email_verified:
        return generic_response

    if user.last_verification_email_sent_at:
        last_sent = user.last_verification_email_sent_at
        if not last_sent.tzinfo:
            last_sent = last_sent.replace(tzinfo=timezone.utc)
        seconds_since = (datetime.now(timezone.utc) - last_sent).total_seconds()
        if seconds_since < RESEND_VERIFICATION_COOLDOWN_SECONDS:
            # Deliberately still the generic message, not a "wait N
            # seconds" error - revealing the cooldown timer would itself
            # confirm this email exists and is unverified, exactly the
            # enumeration this route is supposed to avoid.
            return generic_response

    _issue_verification_token(db, user)
    db.commit()

    return generic_response
