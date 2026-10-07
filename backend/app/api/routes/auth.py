"""
Auth endpoints: signup, login (with rate limiting), password reset,
email verification, and accepting an invite. All real email sends go
through app/services/email.py, which delivers via Resend when
RESEND_API_KEY is configured or falls back to logging when it isn't.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    hash_password, verify_password, create_access_token,
    generate_one_time_token, hash_token, create_purpose_token, decode_purpose_token,
)
from app.models.organization import Organization
from app.models.role import Role, Permission
from app.models.user import User
from app.models.reports import ReportSubscription
from app.schemas.auth import (
    OrganizationSignup, LoginRequest, TokenResponse, UserOut,
    ForgotPasswordRequest, ResetPasswordRequest, VerifyEmailRequest, ResendVerificationRequest,
    AcceptInviteRequest, LoginResponse, TotpVerifyIn, TotpSetupStartIn, TotpSetupOut, TotpSetupConfirmIn,
    TotpEnrolledOut, SignupConfigOut,
)
from app.api.deps import get_current_user, get_current_user_unverified_ok, user_has_permission
from app.services import totp
from app.services.signup_guard import check_signup_allowed, access_code_required
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
def signup(payload: OrganizationSignup, request: Request, db: Session = Depends(get_db)):
    check_signup_allowed(db, request, payload.access_code)
    return create_organization(payload, db)


def create_organization(payload: OrganizationSignup, db: Session) -> TokenResponse:
    """The sign-up itself, without the abuse checks (those belong to the public HTTP route; seed scripts call this directly)."""
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
               "finance", "hr", "projects", "documents", "reports", "custom_fields", "intelligence"]
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
    db.flush()  # need admin_user.id for the subscription row below

    # Preserves today's exact behavior for brand-new orgs: the org's
    # creator gets the weekly digest by default, same as before this
    # feature existed - they can unsubscribe anytime from Reports.
    # Existing orgs get backfilled once by a real grandfather script,
    # not by this signup code (which only ever runs for NEW orgs).
    db.add(ReportSubscription(org_id=org.id, user_id=admin_user.id))

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
    return TokenResponse(access_token=token, email_verification_required=settings.REQUIRE_VERIFIED_EMAIL_FOR_API)


@router.get("/signup-config", response_model=SignupConfigOut)
def signup_config():
    """Public: lets the sign-up page know whether to ask for an access code."""
    return SignupConfigOut(access_code_required=access_code_required())


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()

    # Deliberately vague error message - never reveal whether the email
    # or the password was the wrong part, that helps attackers guess.
    invalid_error = HTTPException(status_code=401, detail="Incorrect email or password.")

    # Checked BEFORE password verification, deliberately, for a real
    # reason: an invited-but-not-yet-accepted user's password_hash is a
    # hash of a random, unguessable placeholder (see roles.py's
    # create_invite) - verify_password() would ALWAYS fail for them, so
    # if this check ran after password verification, they'd just get
    # the generic "incorrect email or password" forever with no way to
    # know why. This does mean an invited/disabled account's status is
    # revealed regardless of the password entered - a narrower
    # disclosure than public enumeration risks like forgot-password
    # (this only reveals pending-invite/disabled status for a specific
    # email within a specific org, not "does any account anywhere on
    # the internet exist for this address"), and worth it for the real
    # usability gap it closes.
    if user and user.status == "invited":
        raise HTTPException(
            status_code=403,
            detail="This account hasn't been activated yet. Check your email for an invitation link.",
        )
    if user and user.status == "disabled":
        raise HTTPException(status_code=403, detail="This account has been disabled.")

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

    # Which door did they use? Checked only AFTER the password is right, so it
    # never tells a stranger anything about an account they cannot log in to.
    is_admin = user_has_permission(db, user, "core", "manage_access")
    if payload.portal == "admin" and not is_admin:
        raise HTTPException(status_code=403, detail="This is an employee account. Use the Employee sign-in page.")
    if payload.portal == "employee" and is_admin:
        raise HTTPException(status_code=403, detail="This is an administrator account. Use the Admin sign-in page.")

    if payload.portal == "admin" and (settings.ADMIN_2FA_REQUIRED or user.totp_enabled):
        # Not signed in yet: the counter is NOT cleared here, otherwise someone who
        # knows the password could reset it by logging in again between code guesses.
        if user.totp_enabled:
            return LoginResponse(requires_totp=True, challenge_token=create_purpose_token(user.id, "totp"))
        return LoginResponse(requires_totp_setup=True, challenge_token=create_purpose_token(user.id, "totp_setup"))

    return LoginResponse(access_token=_finish_login(db, user, payload.portal))


def _finish_login(db: Session, user: User, portal: str) -> str:
    # Successful login clears any prior failed attempts / lockout.
    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()

    role_name = user.role.name if user.role else None
    return create_access_token({
        "sub": str(user.id),
        "org_id": str(user.org_id),
        "role": role_name,
        "portal": portal,
    })


def _user_from_challenge(db: Session, token: str, purpose: str) -> User:
    user_id = decode_purpose_token(token, purpose)
    user = db.query(User).filter(User.id == user_id).first() if user_id else None
    if not user or user.status != "active":
        raise HTTPException(status_code=401, detail="This sign-in step has expired. Please sign in again.")
    return user


def _check_not_locked(user: User) -> None:
    now = datetime.now(timezone.utc)
    if user.locked_until:
        locked_until = user.locked_until if user.locked_until.tzinfo else user.locked_until.replace(tzinfo=timezone.utc)
        if locked_until > now:
            raise HTTPException(status_code=429, detail=f"Too many failed attempts. Try again in {max(1, int((locked_until - now).total_seconds()) // 60)} minute(s).")


def _register_failure(db: Session, user: User) -> None:
    user.failed_login_attempts += 1
    if user.failed_login_attempts >= settings.MAX_FAILED_LOGIN_ATTEMPTS:
        user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
    db.commit()


@router.post("/totp/verify", response_model=TokenResponse)
def totp_verify(payload: TotpVerifyIn, db: Session = Depends(get_db)):
    """Second step of an admin sign-in: the 6-digit code from the authenticator app, or one recovery code."""
    user = _user_from_challenge(db, payload.challenge_token, "totp")
    _check_not_locked(user)
    secret = totp.decrypt_secret(user.totp_secret_enc) if user.totp_secret_enc else None
    if not user.totp_enabled or not secret:
        raise HTTPException(status_code=400, detail="Authenticator is not set up for this account. Ask another administrator to reset it.")

    code = payload.code.strip()
    step = totp.verify_code(secret, code, user.totp_last_step) if code.replace(" ", "").isdigit() else None
    if step is not None:
        user.totp_last_step = step
    else:
        remaining = totp.consume_recovery_code(user.recovery_codes_hash, code)
        if remaining is None:
            _register_failure(db, user)
            raise HTTPException(status_code=401, detail="That code is not correct.")
        user.recovery_codes_hash = remaining   # single use
    return TokenResponse(access_token=_finish_login(db, user, "admin"))


@router.post("/totp/setup/start", response_model=TotpSetupOut)
def totp_setup_start(payload: TotpSetupStartIn, db: Session = Depends(get_db)):
    """An admin without an authenticator yet (just passed the password step) asks for a new secret to scan."""
    user = _user_from_challenge(db, payload.challenge_token, "totp_setup")
    if user.totp_enabled:
        raise HTTPException(status_code=400, detail="An authenticator is already set up. Sign in again.")
    secret = totp.new_secret()
    user.totp_secret_enc = totp.encrypt_secret(secret)
    db.commit()
    return TotpSetupOut(secret=secret, otpauth_uri=totp.provisioning_uri(secret, user.email))


@router.post("/totp/setup/confirm", response_model=TotpEnrolledOut)
def totp_setup_confirm(payload: TotpSetupConfirmIn, db: Session = Depends(get_db)):
    """Proves the app works by entering its first code; only then is 2FA switched on and recovery codes shown (once)."""
    user = _user_from_challenge(db, payload.challenge_token, "totp_setup")
    _check_not_locked(user)
    if user.totp_enabled or not user.totp_secret_enc:
        raise HTTPException(status_code=400, detail="Start the authenticator setup first.")
    secret = totp.decrypt_secret(user.totp_secret_enc)
    step = totp.verify_code(secret, payload.code) if secret else None
    if step is None:
        _register_failure(db, user)
        raise HTTPException(status_code=401, detail="That code is not correct. Check the time on your phone and try the next code.")
    codes, stored = totp.generate_recovery_codes()
    user.totp_enabled = True
    user.totp_last_step = step
    user.recovery_codes_hash = stored
    return TotpEnrolledOut(access_token=_finish_login(db, user, "admin"), recovery_codes=codes)


class _SecurityOut(BaseModel):
    totp_enabled: bool
    recovery_codes_left: int
    two_factor_required: bool


class _RegenIn(BaseModel):
    password: str
    code: str


@router.get("/security", response_model=_SecurityOut)
def my_security(current_user: User = Depends(get_current_user)):
    return _SecurityOut(totp_enabled=current_user.totp_enabled, recovery_codes_left=totp.recovery_codes_left(current_user.recovery_codes_hash),
                        two_factor_required=settings.ADMIN_2FA_REQUIRED)


@router.post("/totp/recovery-codes", response_model=list[str])
def regenerate_recovery_codes(payload: _RegenIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """New set of recovery codes (the old ones stop working). Needs the password and a current authenticator code."""
    if not current_user.totp_enabled:
        raise HTTPException(status_code=400, detail="Authenticator is not enabled for this account.")
    if not verify_password(payload.password, current_user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect password.")
    secret = totp.decrypt_secret(current_user.totp_secret_enc) if current_user.totp_secret_enc else None
    step = totp.verify_code(secret, payload.code, current_user.totp_last_step) if secret else None
    if step is None:
        raise HTTPException(status_code=401, detail="That authenticator code is not correct.")
    current_user.totp_last_step = step
    codes, stored = totp.generate_recovery_codes()
    current_user.recovery_codes_hash = stored
    db.commit()
    return codes


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user_unverified_ok), db: Session = Depends(get_db)):
    return UserOut(
        id=str(current_user.id),
        name=current_user.name,
        email=current_user.email,
        org_id=str(current_user.org_id),
        status=current_user.status,
        email_verified=current_user.email_verified,
        is_admin=user_has_permission(db, current_user, "core", "manage_access"),
        role_name=current_user.role.name if current_user.role else None,
        org_name=db.query(Organization.name).filter(Organization.id == current_user.org_id).scalar(),
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


@router.post("/accept-invite", response_model=TokenResponse, status_code=200)
def accept_invite(payload: AcceptInviteRequest, db: Session = Depends(get_db)):
    """
    Public - the invitee has no credentials at all yet, so this can't
    require auth. Looks up purely by the token's hash, same pattern as
    reset-password/verify-email, and returns the same generic
    invalid/expired message either way - no distinction between "wrong
    token", "already accepted", or "expired", so a guessed token can't
    be used to fingerprint which case it hit.

    Accepting the invite counts as email verification too, deliberately
    - clicking a real emailed link already proves inbox ownership, so a
    SEPARATE verification email/click right after would just be
    redundant friction with no additional security benefit.
    """
    hashed = hash_token(payload.token)
    user = db.query(User).filter(User.invite_token_hash == hashed, User.status == "invited").first()

    invalid_error = HTTPException(status_code=400, detail="Invalid or expired invite link.")

    if not user or not user.invite_token_expires:
        raise invalid_error

    expires = user.invite_token_expires if user.invite_token_expires.tzinfo else user.invite_token_expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        raise invalid_error

    user.password_hash = hash_password(payload.password)
    user.status = "active"
    user.email_verified = True
    user.invite_token_hash = None
    user.invite_token_expires = None
    db.commit()
    db.refresh(user)

    if user_has_permission(db, user, "core", "manage_access") and settings.ADMIN_2FA_REQUIRED:
        return TokenResponse(access_token="")   # no session: the new admin signs in on the Admin page and sets up the authenticator
    return TokenResponse(access_token=_finish_login(db, user, "employee"))
