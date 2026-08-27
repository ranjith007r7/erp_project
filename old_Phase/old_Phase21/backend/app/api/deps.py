"""
'Dependencies' are things FastAPI runs automatically before your endpoint
code, and hands you the result. Every protected endpoint in every future
module will use get_current_user the same way — this is the ONE place
that checks "is this request's login token valid?" for the whole app.
"""
from fastapi import Depends, HTTPException, Header, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User
from app.models.role import Permission, Role

# This tells FastAPI's auto-generated /docs page where to send a login
# request from the "Authorize" button — it doesn't do any work itself.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_access_token(token)
    if payload is None:
        raise credentials_error

    user_id = payload.get("sub")
    if user_id is None:
        raise credentials_error

    user = db.query(User).filter(User.id == user_id).first()
    if user is None or user.status != "active":
        raise credentials_error

    return user


def get_org_id(current_user: User = Depends(get_current_user)) -> str:
    """
    Every CRM/Sales/etc. route needs to filter its queries down to the
    logged-in user's own organization - never showing one client's data
    to another. Rather than repeat `str(current_user.org_id)` in every
    single route, every module imports this one helper instead.
    """
    return str(current_user.org_id)


# Every action every seeded Admin role gets at signup (app/api/routes/auth.py).
# Kept here too so the self-healing path below grants the exact same set,
# not a partial one.
ALL_ACTIONS = ["view", "create", "edit", "delete", "approve"]
ADMIN_ROLE_NAME = "Admin"

# --- The "who controls access" capability (added after a real security
# finding, not planned from the start - see MANUAL.md's writeup) ---
#
# Deliberately NOT one of the five actions above, and deliberately never
# added to ALL_ACTIONS. Granting/revoking a Permission and reassigning a
# User's role are fundamentally different in kind from editing a sales
# quotation - conflating them under a shared "edit" checkbox is exactly
# what let core.edit alone grant full privilege escalation. This is its
# own dedicated gate: only holding module="core", action="manage_access"
# lets a role touch the permission system at all, full stop, regardless
# of what create/edit/delete/approve checkboxes it happens to have.
MANAGE_ACCESS_MODULE = "core"
MANAGE_ACCESS_ACTION = "manage_access"


def require_permission(module: str, action: str):
    """
    A dependency FACTORY, not a dependency itself - call it with the
    module/action a route needs (e.g. require_permission("hr", "approve"))
    and it returns the actual FastAPI dependency to attach. This is what
    lets one function serve every route in every module instead of
    writing a bespoke permission check per route.

    Self-healing case, same philosophy as get_account()/get_default_
    warehouse(): signup seeds the Admin role with every action for every
    module that existed AT SIGNUP TIME. Two real modules (custom_fields,
    notifications) were built in later phases and never got added to
    that seed list - so any org that signed up before this phase would
    have an Admin role with ZERO permission rows for those two modules,
    and enforcing permissions strictly would lock every existing admin
    out of features they're supposed to have full access to. Rather than
    write a one-time data-migration script (which only fixes orgs that
    exist today, not the next module added the same way), this checks:
    if the role is named "Admin" and has genuinely zero rows for this
    module at all, treat that as "this module didn't exist yet when the
    org signed up" and grant full access to it on the spot - not just
    this one request, but permanently, by writing the missing rows.
    A non-Admin role with zero rows for a module is NOT the same case -
    that's a deliberately restricted role, so it's just denied normally.
    """
    def dependency(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ) -> None:
        role = current_user.role
        if not role:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="No role assigned to this user.")

        # Dedicated self-heal for manage_access specifically. The generic
        # "zero rows for this module -> grant everything" self-heal below
        # does NOT fire for "core", because every existing Admin role
        # already has rows there (the original 5 actions from signup) -
        # this is a NEW action added to an EXISTING module, a different
        # shape of gap than the "whole module didn't exist yet" case.
        # Without this, every org that existed before this fix would be
        # permanently locked out of ever granting manage_access to
        # anyone, including their own real Admin - nobody could reach
        # the routes that grant it, because those routes now REQUIRE it.
        if module == MANAGE_ACCESS_MODULE and action == MANAGE_ACCESS_ACTION and role.name == ADMIN_ROLE_NAME:
            already_has_it = db.query(Permission).filter(
                Permission.role_id == role.id, Permission.module == MANAGE_ACCESS_MODULE,
                Permission.action == MANAGE_ACCESS_ACTION,
            ).first()
            if not already_has_it:
                db.add(Permission(role_id=role.id, module=MANAGE_ACCESS_MODULE, action=MANAGE_ACCESS_ACTION))
                db.commit()
                return

        existing_for_module = db.query(Permission).filter(
            Permission.role_id == role.id, Permission.module == module
        ).count()

        if role.name == ADMIN_ROLE_NAME and existing_for_module == 0:
            for a in ALL_ACTIONS:
                db.add(Permission(role_id=role.id, module=module, action=a))
            db.commit()
            return

        has_permission = db.query(Permission).filter(
            Permission.role_id == role.id, Permission.module == module, Permission.action == action
        ).first()
        if not has_permission:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail=f"Your role '{role.name}' does not have '{action}' access to '{module}'.",
            )

    return dependency


def org_has_admin_equivalent_user(db: Session, org_id: str) -> bool:
    """
    True if at least one ACTIVE user in this org currently holds
    manage_access, via whatever role they have. Used as a guard, called
    AFTER a mutation has been tentatively applied to the session (via
    db.flush(), not yet committed) so this query sees the hypothetical
    post-change state - see roles.py's grant/revoke/role-change routes
    for how this gets used to reject (not just warn about) any action
    that would leave the org with nobody able to manage access at all.
    """
    count = (
        db.query(User)
        .join(Role, User.role_id == Role.id)
        .join(Permission, Permission.role_id == Role.id)
        .filter(
            User.org_id == org_id,
            User.status == "active",
            Permission.module == MANAGE_ACCESS_MODULE,
            Permission.action == MANAGE_ACCESS_ACTION,
        )
        .count()
    )
    return count > 0


def verify_cron_secret(x_cron_secret: str = Header(default="")) -> None:
    """
    Gates the scheduled-job endpoints (app/api/routes/scheduled_jobs.py).
    Deliberately NOT get_current_user - these run triggered by GitHub
    Actions on a timer, with no human logged in and no org to scope to
    (the jobs themselves loop across every org). A constant-time
    comparison isn't used here on purpose: this guards two low-value,
    non-financial-transaction endpoints (send a reminder, send a report),
    not account takeover - the added complexity isn't proportionate here,
    unlike password/token comparisons elsewhere in this codebase.
    """
    if not settings.CRON_SECRET or x_cron_secret != settings.CRON_SECRET:
        raise HTTPException(status_code=401, detail="Invalid or missing cron secret.")
