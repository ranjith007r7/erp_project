"""
'Dependencies' are things FastAPI runs automatically before your endpoint
code, and hands you the result. Every protected endpoint in every future
module will use get_current_user the same way — this is the ONE place
that checks "is this request's login token valid?" for the whole app.
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User
from app.models.role import Permission

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
