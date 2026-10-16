"""
Every route here is scoped to the CURRENT user, not just the current org —
unlike every other module's routes, which filter by org_id alone. A
notification is inherently personal (it says "YOUR leave request", not
"someone's leave request"), so org_id alone isn't enough scoping here;
every query below also filters by Notification.user_id == current_user.id.
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import get_current_user, get_org_id
from app.models.notification import Notification
from app.schemas.notification import NotificationOut, UnreadCountOut

ARCHIVE_DAYS = 7


def purge_expired(db: Session, org_id) -> int:
    """Read messages are kept for 7 days in the temporary archive and then deleted for good (done on every fetch)."""
    n = (db.query(Notification)
         .filter(Notification.org_id == org_id, Notification.is_read.is_(True),
                 Notification.read_at.isnot(None), Notification.read_at < datetime.utcnow() - timedelta(days=ARCHIVE_DAYS))
         .delete(synchronize_session=False))
    if n:
        db.commit()
    return n


router = APIRouter(prefix="/api/notifications", tags=["notifications"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[NotificationOut])
def list_notifications(db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    """Only NEW (unread) notifications; read ones move to /archive."""
    purge_expired(db, org_id)
    return (
        db.query(Notification)
        .filter(Notification.org_id == org_id, Notification.user_id == current_user.id, Notification.is_read.is_(False))
        .order_by(Notification.created_at.desc())
        .limit(50)
        .all()
    )


@router.get("/archive", response_model=list[NotificationOut])
def archive(db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    """The temporary archive: what was read in the last 7 days, newest read first."""
    purge_expired(db, org_id)
    return (
        db.query(Notification)
        .filter(Notification.org_id == org_id, Notification.user_id == current_user.id, Notification.is_read.is_(True))
        .order_by(Notification.read_at.desc().nullslast(), Notification.created_at.desc())
        .limit(100)
        .all()
    )


@router.get("/unread-count", response_model=UnreadCountOut)
def unread_count(db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    count = (
        db.query(Notification)
        .filter(Notification.org_id == org_id, Notification.user_id == current_user.id, Notification.is_read.is_(False))
        .count()
    )
    return {"unread_count": count}


@router.patch("/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    notif = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.org_id == org_id, Notification.user_id == current_user.id)
        .first()
    )
    if not notif:
        raise HTTPException(404, "Notification not found")
    if not notif.is_read:
        notif.is_read = True
        notif.read_at = datetime.utcnow()
    db.commit()
    db.refresh(notif)
    return notif


@router.post("/read-all", status_code=200)
def mark_all_read(db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    updated = (
        db.query(Notification)
        .filter(Notification.org_id == org_id, Notification.user_id == current_user.id, Notification.is_read.is_(False))
        .update({"is_read": True, "read_at": datetime.utcnow()})
    )
    db.commit()
    return {"status": "ok", "marked_read": updated}
