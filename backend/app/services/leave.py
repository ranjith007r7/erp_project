"""
Leave rules in one place: which leave types exist, how many days a person has left,
and the checks every new request must pass (employee self-service and admin-filed alike).
"""
from datetime import date, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.hr import Employee, LeaveRequest, LeaveType
from app.models.notification import Notification
from app.models.role import Permission
from app.models.user import User
from app.services.payroll import get_leave_types

MAX_SPAN_DAYS = 60
BACKDATE_DAYS = 30          # employees may file for up to this many days ago (admins: no limit)
OPEN_STATUSES = ("pending", "approved")


def resolve_type(db: Session, org_id, text: str) -> LeaveType:
    key = (text or "").strip().lower()
    for t in get_leave_types(db, org_id):
        if key in (t.code.lower(), t.name.lower()):
            return t
    raise HTTPException(400, "Unknown leave type. Pick one from the list.")


def _year_days(start: date, end: date, year: int) -> int:
    lo, hi = max(start, date(year, 1, 1)), min(end, date(year, 12, 31))
    return max((hi - lo).days + 1, 0)


def _type_keys(t: LeaveType) -> set[str]:
    return {t.code.lower(), t.name.lower()}


def used_days(db: Session, employee_id, leave_type: LeaveType, year: int, statuses=OPEN_STATUSES, exclude_id=None) -> Decimal:
    total = 0
    keys = _type_keys(leave_type)
    for lr in db.query(LeaveRequest).filter(LeaveRequest.employee_id == employee_id, LeaveRequest.status.in_(statuses)).all():
        if exclude_id and lr.id == exclude_id:
            continue
        if (lr.leave_type or "").strip().lower() in keys:
            total += _year_days(lr.start_date, lr.end_date, year)
    return Decimal(total)


def balances(db: Session, employee: Employee, year: int) -> list[dict]:
    out = []
    for t in get_leave_types(db, employee.org_id):
        approved = used_days(db, employee.id, t, year, ("approved",))
        pending = used_days(db, employee.id, t, year, ("pending",))
        ent = Decimal(t.days_per_year) if t.days_per_year is not None else None
        out.append({
            "code": t.code, "name": t.name, "paid": t.paid, "note": t.note,
            "entitlement": ent, "approved": approved, "pending": pending,
            "remaining": (ent - approved - pending) if ent is not None else None,
        })
    return out


def _overlaps(db: Session, employee_id, start: date, end: date) -> bool:
    return db.query(LeaveRequest).filter(
        LeaveRequest.employee_id == employee_id, LeaveRequest.status.in_(OPEN_STATUSES),
        LeaveRequest.start_date <= end, LeaveRequest.end_date >= start).first() is not None


def create_leave(db: Session, employee: Employee, type_text: str, start: date, end: date, reason: str | None,
                 *, self_service: bool) -> LeaveRequest:
    """Validates and adds (does not commit). Raises 400 with a plain message."""
    lt = resolve_type(db, employee.org_id, type_text)
    if end < start:
        raise HTTPException(400, "The end date cannot be before the start date.")
    if (end - start).days + 1 > MAX_SPAN_DAYS:
        raise HTTPException(400, f"A single request can cover at most {MAX_SPAN_DAYS} days.")
    if self_service and start < date.today() - timedelta(days=BACKDATE_DAYS):
        raise HTTPException(400, f"You can only apply for leave starting within the last {BACKDATE_DAYS} days. Ask your administrator to record older leave.")
    if employee.status != "active":
        raise HTTPException(400, "This employee is not active.")
    if _overlaps(db, employee.id, start, end):
        raise HTTPException(400, "You already have a pending or approved leave overlapping these dates.")
    if lt.days_per_year is not None:
        for year in {start.year, end.year}:
            asked = _year_days(start, end, year)
            left = Decimal(lt.days_per_year) - used_days(db, employee.id, lt, year)
            if Decimal(asked) > left:
                raise HTTPException(400, f"Not enough {lt.name} left for {year}: {left:g} day(s) remaining, {asked} requested. "
                                         f"Choose another type (for example Loss of Pay) or fewer days.")
    lr = LeaveRequest(employee_id=employee.id, leave_type=lt.name, start_date=start, end_date=end,
                      reason=(reason or "").strip() or None, status="pending")
    db.add(lr)
    db.flush()
    return lr


def approver_user_ids(db: Session, org_id) -> list:
    """Active users who can approve leave: administrators and anyone with hr.approve."""
    role_ids = {r for (r,) in db.query(Permission.role_id).filter(
        ((Permission.module == "hr") & (Permission.action == "approve")) | ((Permission.module == "core") & (Permission.action == "manage_access"))).all()}
    if not role_ids:
        return []
    return [u.id for u in db.query(User).filter(User.org_id == org_id, User.status == "active", User.role_id.in_(role_ids)).all()]


def notify_approvers(db: Session, org_id, message: str, skip_user_id=None) -> None:
    for uid in approver_user_ids(db, org_id):
        if uid != skip_user_id:
            db.add(Notification(org_id=org_id, user_id=uid, message=message))


def approved_leave_on(db: Session, employee_ids: list, day: date) -> set:
    """Employees with an approved leave covering `day` (shown as 'leave' when nobody marked them)."""
    if not employee_ids:
        return set()
    rows = db.query(LeaveRequest.employee_id).filter(
        LeaveRequest.employee_id.in_(employee_ids), LeaveRequest.status == "approved",
        LeaveRequest.start_date <= day, LeaveRequest.end_date >= day).all()
    return {r[0] for r in rows}
