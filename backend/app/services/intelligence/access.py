"""
Who may ask the AI about what.

THE RULE (one sentence): Ask Data must never show a person more than the
normal screens would. A view is readable if the user holds `view` on at least
one of the modules whose screens already show that data (manifest.ACCESS).
Restricted views (salary, payroll) additionally need `approve` on the
`intelligence` permission, and approve NEVER substitutes for module access.

Admin is decided by role NAME, exactly like the global search does
(services/search.py), for the same reason documented there: it avoids the
self-heal permission-row writes that only fire on guarded routes.

This profile is used in three independent places, so a bug in one cannot leak data:
  1. prompts       the model is only told about views the user may read
  2. the validator a query naming any other view is refused with a clear reason
  3. the database  the same modules/restricted flag are registered for the
                   connection, and every view re-checks them itself (see the
                   uil.can_read() function in the migration), so even a query that
                   slipped past 1 and 2 returns ZERO rows

Resolved fresh on every question: revoking a tick takes effect on the very next ask.
"""
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.api.deps import ADMIN_ROLE_NAME
from app.models.role import Permission, Role
from app.services.intelligence.manifest import ALL_MODULES, MODULE_LABELS, VIEWS, VIEWS_BY_NAME

INTELLIGENCE_MODULE = "intelligence"


@dataclass(frozen=True)
class AccessProfile:
    modules: frozenset          # RBAC modules on which the user holds `view`
    restricted: bool            # holds intelligence.approve (restricted data tier)
    is_admin: bool = False

    @staticmethod
    def full() -> "AccessProfile":
        return AccessProfile(modules=ALL_MODULES, restricted=True, is_admin=True)

    @staticmethod
    def none() -> "AccessProfile":
        return AccessProfile(modules=frozenset(), restricted=False)

    def allows(self, view) -> bool:
        if not (set(view.access) & self.modules):
            return False
        return self.restricted or not view.restricted

    def allowed_names(self) -> frozenset:
        return frozenset(v.name for v in VIEWS if self.allows(v))

    def missing_for(self, view) -> list:
        """Plain-language reasons this view is unavailable to this user (empty if it is available)."""
        reasons = []
        if not (set(view.access) & self.modules):
            labels = " or ".join(MODULE_LABELS.get(m, m) for m in view.access)
            reasons.append(f"access to the {labels} module")
        if view.restricted and not self.restricted:
            reasons.append("the 'approve' permission on Ask Data (restricted data)")
        return reasons


def resolve_access(db: Session, user) -> AccessProfile:
    if not user.role_id:
        return AccessProfile.none()
    role = db.query(Role).filter(Role.id == user.role_id).first()
    if role is None:
        return AccessProfile.none()
    if role.name == ADMIN_ROLE_NAME:
        return AccessProfile.full()

    held = {(m, a) for m, a in db.query(Permission.module, Permission.action).filter(Permission.role_id == role.id)}
    return AccessProfile(
        modules=frozenset(m for m in ALL_MODULES if (m, "view") in held),
        restricted=(INTELLIGENCE_MODULE, "approve") in held,
    )


def denial_message(view_names, access: AccessProfile) -> str:
    needs = []
    for name in view_names:
        view = VIEWS_BY_NAME.get(name)
        if view is not None:
            for reason in access.missing_for(view):
                if reason not in needs:
                    needs.append(reason)
    detail = " and ".join(needs) if needs else "additional permissions"
    return (f"You don't have access to that data. It needs {detail}. "
            "Ask an administrator to update your role's permissions.")
