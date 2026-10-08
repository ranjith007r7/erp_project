"""
What any signed-in person can do about THEIR OWN HR record, with no hr.* permission needed:
file, see and cancel their leave, see their leave balances, and see their attendance.
The employee is always found from the signed-in user, never from anything the browser sends.
Attendance is marked by an administrator only; here it is read-only.
"""
import calendar
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.hr import Attendance, Employee, LeaveRequest
from app.models.user import User
from app.schemas.hr import LeaveRequestCreate, LeaveRequestOut
from app.services import leave as leave_rules
from app.services.audit import log_audit_event
from pydantic import BaseModel, ConfigDict

router = APIRouter(prefix="/api/me", tags=["my-hr"], dependencies=[Depends(get_current_user)])


def _my_employee(db: Session, user: User) -> Employee:
    e = db.query(Employee).filter(Employee.org_id == user.org_id, Employee.user_id == user.id).first()
    if not e:
        raise HTTPException(404, "No HR record is linked to your login yet. Ask your administrator to link it.")
    return e


class MyLeaveCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    leave_type: str
    start_date: date
    end_date: date
    reason: str | None = None


@router.get("/leaves")
def my_leaves(year: int | None = Query(None, ge=2000, le=2100), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    e = _my_employee(db, user)
    y = year or date.today().year
    reqs = db.query(LeaveRequest).filter(LeaveRequest.employee_id == e.id).order_by(LeaveRequest.created_at.desc()).all()
    return {
        "year": y,
        "employee_name": e.name,
        "balances": leave_rules.balances(db, e, y),
        "requests": [LeaveRequestOut.model_validate(r) for r in reqs],
    }


@router.post("/leaves", response_model=LeaveRequestOut, status_code=201)
def apply_leave(payload: MyLeaveCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    e = _my_employee(db, user)
    lr = leave_rules.create_leave(db, e, payload.leave_type, payload.start_date, payload.end_date, payload.reason, self_service=True)
    leave_rules.notify_approvers(db, user.org_id,
                                 f"{e.name} applied for {lr.leave_type}: {lr.start_date} to {lr.end_date} ({lr.days} day(s)).",
                                 skip_user_id=user.id)
    log_audit_event(db, user.org_id, user.id, "apply_leave", "LeaveRequest", lr.id)
    db.commit()
    db.refresh(lr)
    return lr


@router.post("/leaves/{leave_id}/cancel", response_model=LeaveRequestOut)
def cancel_leave(leave_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    e = _my_employee(db, user)
    lr = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id, LeaveRequest.employee_id == e.id).first()
    if not lr:
        raise HTTPException(404, "Leave request not found.")
    if lr.status != "pending":
        raise HTTPException(400, "Only a pending request can be cancelled. Ask your administrator about an approved one.")
    lr.status, lr.decided_at, lr.decided_by = "cancelled", datetime.utcnow(), user.id
    log_audit_event(db, user.org_id, user.id, "cancel_leave", "LeaveRequest", lr.id)
    db.commit()
    db.refresh(lr)
    return lr


@router.get("/attendance")
def my_attendance(month: int | None = Query(None, ge=1, le=12), year: int | None = Query(None, ge=2000, le=2100),
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    e = _my_employee(db, user)
    today = date.today()
    m, y = month or today.month, year or today.year
    first, last = date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
    marks = {a.date: a.status for a in db.query(Attendance).filter(Attendance.employee_id == e.id, Attendance.date >= first, Attendance.date <= last).all()}
    leaves = db.query(LeaveRequest).filter(LeaveRequest.employee_id == e.id, LeaveRequest.status == "approved",
                                           LeaveRequest.start_date <= last, LeaveRequest.end_date >= first).all()
    days = []
    for n in range((min(last, today) - first).days + 1 if first <= today else 0):
        d = date.fromordinal(first.toordinal() + n)
        status = marks.get(d)
        derived = False
        if status is None and any(l.start_date <= d <= l.end_date for l in leaves):
            status, derived = "leave", True
        days.append({"date": d, "status": status, "from_approved_leave": derived})
    counts = {k: sum(1 for x in days if x["status"] == k) for k in ("present", "absent", "half_day", "leave")}
    return {"month": m, "year": y, "days": days, "counts": counts, "not_marked": sum(1 for x in days if x["status"] is None)}
