"""
Read-only. Nothing here writes to AuditLog - see app/services/audit.py
for the one place that does. Gated by core.view, same convention as
listing roles/users - this is org administration data, not a
business-module concern.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.api.deps import get_current_user, get_org_id, require_permission
from app.models.audit_log import AuditLog
from app.models.user import User
from app.schemas.audit_log import AuditLogOut

router = APIRouter(prefix="/api/core/audit-log", tags=["audit-log"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[AuditLogOut], dependencies=[Depends(require_permission("core", "view"))])
def list_audit_log(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    """
    Capped at the 500 most recent entries, newest first - an
    ever-growing append-only log needs SOME server-side limit (same
    reasoning as notifications.py's .limit(50), just a higher number
    here since audit context needs more history). Client-side pagination
    (usePagination on the frontend) slices this set further for display,
    matching the pattern already used for Inventory's product list.
    """
    entries = (
        db.query(AuditLog)
        .options(joinedload(AuditLog.user))
        .filter(AuditLog.org_id == org_id)
        .order_by(AuditLog.created_at.desc())
        .limit(500)
        .all()
    )
    return [
        AuditLogOut(
            id=e.id, user_id=e.user_id, user_name=e.user.name if e.user else None,
            action=e.action, entity=e.entity, entity_id=e.entity_id, created_at=e.created_at,
        )
        for e in entries
    ]
