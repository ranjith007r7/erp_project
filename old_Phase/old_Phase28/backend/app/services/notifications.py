"""
Same shape as app/services/accounting.py and app/services/inventory.py:
the ONE place that knows how to create a Notification, so every module
(HR, Documents, and any future one) calls into here instead of writing
its own copy of "insert a Notification row" logic.

Deliberately soft-fail: notify_user() never raises. A missing employee
login, a role name in a workflow that doesn't match any real Role row —
none of that should ever block the actual business action (approving
leave, actioning an approval step) just because the alert-side of it
couldn't find anyone to tell. The roadmap's own gaps table already flags
RBAC/roles as "structure exists, not enforced" — a workflow's
role_required string isn't guaranteed to match a real Role.name yet, so
this has to tolerate that gracefully rather than 500 on it.
"""
from sqlalchemy.orm import Session

from app.models.notification import Notification
from app.models.role import Role
from app.models.user import User


def notify_user(db: Session, org_id: str, user_id, message: str) -> None:
    """The base primitive: one notification, one specific user."""
    if not user_id:
        return
    db.add(Notification(org_id=org_id, user_id=user_id, message=message))


def notify_role(db: Session, org_id: str, role_name: str, message: str) -> None:
    """
    Notify every user in this org currently holding a role with this
    name — used for "someone with role X needs to act on this" cases
    like an approval step becoming actionable, where there's no single
    assigned approver yet, only a required role.
    """
    role = db.query(Role).filter(Role.org_id == org_id, Role.name == role_name).first()
    if not role:
        return  # no matching role in this org — nothing to notify, not an error
    users = db.query(User).filter(User.org_id == org_id, User.role_id == role.id, User.status == "active").all()
    for user in users:
        db.add(Notification(org_id=org_id, user_id=user.id, message=message))
