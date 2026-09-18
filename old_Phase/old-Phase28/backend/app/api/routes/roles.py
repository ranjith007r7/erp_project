"""
Role/Permission/User management.

Two DIFFERENT gates apply here, deliberately not the same one:
- Creating an empty role, or a user with NO role assigned, only needs
  ordinary core.create — harmless on its own, grants no new capability.
- Granting/revoking ANY permission, and assigning/changing ANY user's
  role (including at user-creation time), requires the separate
  core.manage_access capability - see app/api/deps.py's module
  docstring for why this had to be split out from core.edit after a
  real security finding: core.edit alone was previously enough to
  reassign any user's role, including granting yourself Admin.

Every one of those manage_access-gated mutations also runs through
org_has_admin_equivalent_user() AFTER being tentatively applied (via
db.flush(), not yet committed) - if the org would be left with zero
active users holding manage_access, the whole operation is rejected
and rolled back, not just warned about. This blocks the "last Admin
locks themselves out with no recovery path" scenario regardless of
which specific action someone used to get there.

Two ways to add a user, both gated the same way (core.manage_access):
create_user sets a real password directly (Admin-chosen); the invite
flow below sends a real email and lets the invitee set their own -
see InviteCreate/AcceptInviteRequest for why the two need different
schemas.
"""
from datetime import datetime, timedelta, timezone
import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.core.database import get_db
from app.core.security import hash_password, generate_one_time_token
from app.api.deps import get_current_user, get_org_id, require_permission, org_has_admin_equivalent_user, lock_org_for_admin_guard
from app.models.organization import Organization
from app.models.role import Role, Permission
from app.models.user import User
from app.schemas.roles import (
    RoleCreate, RoleOut, PermissionCreate, PermissionOut,
    UserCreate, UserRoleUpdate, UserManagementOut, InviteCreate, BulkRoleAssignRequest,
)
from app.services.email import send_invite_email
from app.services.audit import log_audit_event

router = APIRouter(prefix="/api/core", tags=["roles-users"], dependencies=[Depends(get_current_user)])

LAST_ADMIN_ERROR = HTTPException(
    400,
    "This action would leave the organization with no user able to manage roles and "
    "permissions. Grant 'Manage Roles & Permissions' to another active user first.",
)


# ---------------- Roles ----------------
@router.post("/roles", response_model=RoleOut, status_code=201, dependencies=[Depends(require_permission("core", "create"))])
def create_role(payload: RoleCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    existing = db.query(Role).filter(Role.org_id == org_id, Role.name == payload.name).first()
    if existing:
        raise HTTPException(400, f"A role named '{payload.name}' already exists.")
    role = Role(org_id=org_id, name=payload.name)
    db.add(role)
    db.commit()
    db.refresh(role)
    return role


@router.get("/roles", response_model=list[RoleOut], dependencies=[Depends(require_permission("core", "view"))])
def list_roles(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return db.query(Role).filter(Role.org_id == org_id).all()


@router.post("/roles/{role_id}/permissions", response_model=PermissionOut, status_code=201, dependencies=[Depends(require_permission("core", "manage_access"))])
def grant_permission(role_id: str, payload: PermissionCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    role = db.query(Role).filter(Role.id == role_id, Role.org_id == org_id).first()
    if not role:
        raise HTTPException(404, "Role not found")
    existing = db.query(Permission).filter(
        Permission.role_id == role_id, Permission.module == payload.module, Permission.action == payload.action
    ).first()
    if existing:
        return existing  # idempotent - granting the same permission twice isn't an error
    perm = Permission(role_id=role_id, module=payload.module, action=payload.action)
    db.add(perm)
    db.flush()  # populate perm.id (Python-side UUID default only resolves at flush) before logging it
    log_audit_event(db, org_id, current_user.id, "grant_permission", "Permission", perm.id)
    db.commit()
    db.refresh(perm)
    return perm


@router.get("/roles/{role_id}/permissions", response_model=list[PermissionOut], dependencies=[Depends(require_permission("core", "view"))])
def list_role_permissions(role_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    role = db.query(Role).filter(Role.id == role_id, Role.org_id == org_id).first()
    if not role:
        raise HTTPException(404, "Role not found")
    return db.query(Permission).filter(Permission.role_id == role_id).all()


@router.delete("/roles/{role_id}/permissions/{permission_id}", status_code=204, dependencies=[Depends(require_permission("core", "manage_access"))])
def revoke_permission(role_id: str, permission_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    lock_org_for_admin_guard(db, org_id)
    role = db.query(Role).filter(Role.id == role_id, Role.org_id == org_id).first()
    if not role:
        raise HTTPException(404, "Role not found")
    perm = db.query(Permission).filter(Permission.id == permission_id, Permission.role_id == role_id).first()
    if not perm:
        raise HTTPException(404, "Permission not found")

    db.delete(perm)
    db.flush()  # apply tentatively, visible to the check below, not yet committed

    if not org_has_admin_equivalent_user(db, org_id):
        db.rollback()
        raise LAST_ADMIN_ERROR

    log_audit_event(db, org_id, current_user.id, "revoke_permission", "Permission", permission_id)
    db.commit()


# ---------------- Users ----------------
@router.get("/users", response_model=list[UserManagementOut], dependencies=[Depends(require_permission("core", "view"))])
def list_users(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    users = db.query(User).options(joinedload(User.role)).filter(User.org_id == org_id).all()
    return [
        UserManagementOut(
            id=u.id, name=u.name, email=u.email, role_id=u.role_id,
            role_name=u.role.name if u.role else None, status=u.status, created_at=u.created_at,
        )
        for u in users
    ]


@router.post("/users", response_model=UserManagementOut, status_code=201, dependencies=[Depends(require_permission("core", "manage_access"))])
def create_user(payload: UserCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    """
    Requires manage_access, not just core.create - assigning a role at
    creation time is functionally identical to "create, then change
    role", and only requiring create would let someone without
    manage_access sidestep the role-change gate entirely by picking a
    role_id (e.g. Admin's) directly in the creation payload instead.
    """
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(400, "A user with this email already exists.")

    if payload.role_id:
        role = db.query(Role).filter(Role.id == payload.role_id, Role.org_id == org_id).first()
        if not role:
            raise HTTPException(404, "Role not found in this organization.")

    user = User(
        org_id=org_id,
        name=payload.name,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role_id=payload.role_id,
        # Verified immediately, unlike public self-signup. An Admin
        # creating this account directly (setting a real password for a
        # real teammate) is a fundamentally different trust situation
        # than a stranger self-signing-up with an unproven email - the
        # Admin is the one vouching for this account's legitimacy here,
        # not the email inbox. Requiring a verification click on top of
        # that would just be friction with no real security benefit.
        email_verified=True,
    )
    db.add(user)
    db.flush()  # populate user.id before logging it
    log_audit_event(db, org_id, current_user.id, "create_user", "User", user.id)
    db.commit()
    db.refresh(user)
    return UserManagementOut(
        id=user.id, name=user.name, email=user.email, role_id=user.role_id,
        role_name=user.role.name if user.role else None, status=user.status, created_at=user.created_at,
    )


@router.patch("/users/{user_id}/role", response_model=UserManagementOut, dependencies=[Depends(require_permission("core", "manage_access"))])
def update_user_role(user_id: str, payload: UserRoleUpdate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    lock_org_for_admin_guard(db, org_id)
    user = db.query(User).filter(User.id == user_id, User.org_id == org_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    if payload.role_id:
        role = db.query(Role).filter(Role.id == payload.role_id, Role.org_id == org_id).first()
        if not role:
            raise HTTPException(404, "Role not found in this organization.")

    user.role_id = payload.role_id
    db.flush()  # apply tentatively, visible to the check below, not yet committed

    if not org_has_admin_equivalent_user(db, org_id):
        db.rollback()
        raise LAST_ADMIN_ERROR

    log_audit_event(db, org_id, current_user.id, "change_user_role", "User", user.id)
    db.commit()
    db.refresh(user)
    return UserManagementOut(
        id=user.id, name=user.name, email=user.email, role_id=user.role_id,
        role_name=user.role.name if user.role else None, status=user.status, created_at=user.created_at,
    )


# ---------------- Invites ----------------
INVITE_RESEND_COOLDOWN_SECONDS = 60


def _issue_invite_token(db: Session, user: User, org_name: str) -> None:
    """
    Mirrors app/api/routes/auth.py's _issue_verification_token() shape
    exactly - overwriting invite_token_hash implicitly kills whatever
    invite link came before it, so a resend never leaves two valid
    links floating around at once.
    """
    raw_token, token_hash = generate_one_time_token()
    user.invite_token_hash = token_hash
    user.invite_token_expires = datetime.now(timezone.utc) + timedelta(hours=settings.INVITE_TOKEN_EXPIRE_HOURS)
    user.last_invite_email_sent_at = datetime.now(timezone.utc)
    send_invite_email(user.email, org_name, raw_token)


@router.post("/invites", response_model=UserManagementOut, status_code=201, dependencies=[Depends(require_permission("core", "manage_access"))])
def create_invite(payload: InviteCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(400, "A user with this email already exists.")

    if payload.role_id:
        role = db.query(Role).filter(Role.id == payload.role_id, Role.org_id == org_id).first()
        if not role:
            raise HTTPException(404, "Role not found in this organization.")

    org = db.query(Organization).filter(Organization.id == org_id).first()

    user = User(
        org_id=org_id,
        name=payload.name,
        email=payload.email,
        # An unguessable placeholder, not a usable password - see the
        # User model's docstring on why this column stays NOT NULL
        # rather than becoming nullable for this case.
        password_hash=hash_password(secrets.token_urlsafe(32)),
        role_id=payload.role_id,
        status="invited",
    )
    db.add(user)
    db.flush()  # user needs a real id before _issue_invite_token touches it
    _issue_invite_token(db, user, org.name)
    db.commit()
    db.refresh(user)

    return UserManagementOut(
        id=user.id, name=user.name, email=user.email, role_id=user.role_id,
        role_name=user.role.name if user.role else None, status=user.status, created_at=user.created_at,
    )


@router.post("/invites/{user_id}/resend", status_code=200, dependencies=[Depends(require_permission("core", "manage_access"))])
def resend_invite(user_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    """
    Admin-triggered, not self-service - unlike resend-verification, an
    invitee has no working credentials at all yet, so there's no way
    for THEM to authenticate and request this themselves. The Admin who
    sent the original invite is the one who resends it.
    """
    user = db.query(User).filter(User.id == user_id, User.org_id == org_id, User.status == "invited").first()
    if not user:
        raise HTTPException(404, "Pending invite not found for this user.")

    if user.last_invite_email_sent_at:
        last_sent = user.last_invite_email_sent_at
        if not last_sent.tzinfo:
            last_sent = last_sent.replace(tzinfo=timezone.utc)
        seconds_since = (datetime.now(timezone.utc) - last_sent).total_seconds()
        if seconds_since < INVITE_RESEND_COOLDOWN_SECONDS:
            raise HTTPException(429, "Please wait a moment before resending - an invite email was just sent.")

    org = db.query(Organization).filter(Organization.id == org_id).first()
    _issue_invite_token(db, user, org.name)
    db.commit()

    return {"message": f"Invite resent to {user.email}."}


# ---------------- Bulk role assignment ----------------
@router.post("/users/bulk-role-assign", dependencies=[Depends(require_permission("core", "manage_access"))])
def bulk_assign_role(payload: BulkRoleAssignRequest, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    """
    The RBAC-sensitive one, built deliberately carefully - this is
    exactly the class of operation that caused the real privilege-
    escalation/lockout incident earlier in this project when a single-
    item version of this same guard didn't exist yet.

    Each user's role change is its own independent flush -> check ->
    commit-or-skip cycle, using the SAME org_has_admin_equivalent_user()
    guard as the single-user PATCH route above - never one batched
    transaction that flushes everything then checks once at the end.
    That distinction matters: checking once at the end against a
    pre-batch snapshot could let a batch complete that leaves zero
    admins, if enough individual changes each look safe in isolation
    but aren't in combination. Processing sequentially against REAL,
    already-updated state after each prior item closes that gap -
    exactly the same reasoning the single-user route's guard depends on.

    Returns a per-item report, not all-or-nothing - a batch job masking
    a partial, confusing outcome is worse than an explicit list of
    exactly which users changed and which didn't, and why.
    """
    updated: list[str] = []
    skipped: list[dict] = []

    for user_id in payload.user_ids:
        # Re-acquired every iteration, not once before the loop - each
        # iteration has its OWN commit (ending that transaction and
        # releasing an xact-scoped lock), so a single lock taken before
        # the loop would only actually protect the first user processed.
        lock_org_for_admin_guard(db, org_id)
        user = db.query(User).filter(User.id == user_id, User.org_id == org_id).first()
        if not user:
            skipped.append({"user_id": user_id, "reason": "not found"})
            continue

        if payload.role_id:
            role = db.query(Role).filter(Role.id == payload.role_id, Role.org_id == org_id).first()
            if not role:
                skipped.append({"user_id": user_id, "reason": "role not found in this organization"})
                continue

        user.role_id = payload.role_id
        db.flush()

        if not org_has_admin_equivalent_user(db, org_id):
            db.rollback()
            skipped.append({"user_id": user_id, "reason": "would leave the organization with no admin-equivalent user"})
            continue

        log_audit_event(db, org_id, current_user.id, "change_user_role", "User", user.id)
        db.commit()
        updated.append(user_id)

    return {"updated": updated, "skipped": skipped}
