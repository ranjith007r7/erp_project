"""
Every route here is scoped to the CURRENT user, not just the current org —
unlike every other module's routes, which filter by org_id alone. A
notification is inherently personal (it says "YOUR leave request", not
"someone's leave request"), so org_id alone isn't enough scoping here;
every query below also filters by Notification.user_id == current_user.id.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import get_current_user, get_org_id
from app.models.notification import Notification
from app.schemas.notification import NotificationOut, UnreadCountOut

router = APIRouter(prefix="/api/notifications", tags=["notifications"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[NotificationOut])
def list_notifications(db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    return (
        db.query(Notification)
        .filter(Notification.org_id == org_id, Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(50)
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
    notif.is_read = True
    db.commit()
    db.refresh(notif)
    return notif


@router.post("/read-all", status_code=200)
def mark_all_read(db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    updated = (
        db.query(Notification)
        .filter(Notification.org_id == org_id, Notification.user_id == current_user.id, Notification.is_read.is_(False))
        .update({"is_read": True})
    )
    db.commit()
    return {"status": "ok", "marked_read": updated}
