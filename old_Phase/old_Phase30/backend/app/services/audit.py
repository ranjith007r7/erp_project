"""
The ONE place that writes to AuditLog - matches this project's own
established "one service file per cross-cutting concern" pattern
(accounting.py, notifications.py, email.py, storage.py).

Deliberately does NOT call db.commit() itself - log_audit_event() only
calls db.add(), so the audit entry becomes part of the SAME transaction
as the actual mutation it's recording. If that mutation fails and rolls
back, the audit entry rolls back with it - an audit log entry for
something that didn't actually happen would be worse than no entry at
all, not better.

Honest scope note: this is wired into several genuinely high-value
mutation points (see each route's own comment marking where), not
literally every create/update/delete across the whole app - that would
be a much larger, separate pass. Role/permission changes and user
creation were prioritized specifically because that's the exact "who
changed what" question the privilege-escalation incident needed
answered and didn't have.
"""
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def log_audit_event(db: Session, org_id, user_id, action: str, entity: str, entity_id=None) -> None:
    db.add(AuditLog(org_id=org_id, user_id=user_id, action=action, entity=entity, entity_id=entity_id))
