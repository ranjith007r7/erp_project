"""
HR module routes. Departments/Employees/Attendance/Leave are plain CRUD.
The interesting part is /payroll-runs/{id}/process - the same "one action,
multiple module effects, one transaction" pattern used by Sales' invoice
generation and Procurement's goods receipt: it generates a Payslip per
active Employee AND posts a single Journal Entry to Finance, together.
"""
import calendar
import csv
import io
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.api.deps import get_current_user, get_org_id, require_permission, user_has_permission
from app.models.hr import (
    Department, Employee, Attendance, LeaveRequest, PayrollRun, Payslip,
    Position, LeaveType, EmployeePayrollProfile, PayrollInput,
)
from app.models.organization import Organization
from app.models.role import Role
from app.models.user import User
from app.schemas.hr import (
    DepartmentCreate, DepartmentOut,
    PositionCreate, PositionUpdate, PositionOut,
    EmployeeCreate, EmployeeUpdate, EmployeeOut, CreateLoginIn,
    LeaveTypeOut, LeaveTypeUpdate,
    LeaveRequestCreate, LeaveRequestOut, LeaveStatusUpdate,
    AttendanceMark, AttendanceBulk, AttendanceOut,
    PayrollRunCreate, PayrollRunOut,
)
from app.services.accounting import post_payroll_journal_entry
from app.services.payroll import get_leave_types, lop_days_from_approved_leave, compute_payslip
from app.services.invites import create_invited_user
from app.services.notifications import notify_user
from app.services.audit import log_audit_event
from app.services import leave as leave_rules
from app.services.position_roles import ensure_position_role, rename_position_role

router = APIRouter(prefix="/api/hr", tags=["hr"], dependencies=[Depends(get_current_user)])


# ---------------- Departments & positions (set up by an authorised person) ----------------
# hr.approve is the "authority" action: creating departments, positions and
# their fixed salaries is deliberately NOT something a normal HR clerk (who
# holds view/create/edit) can do, so salary cannot be typed in per hire.
@router.post("/departments", response_model=DepartmentOut, status_code=201, dependencies=[Depends(require_permission("hr", "approve"))])
def create_department(payload: DepartmentCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    name = payload.name.strip()
    if db.query(Department.id).filter(Department.org_id == org_id, func.lower(Department.name) == name.lower()).first():
        raise HTTPException(400, f"A department called '{name}' already exists.")
    dept = Department(org_id=org_id, name=name)
    db.add(dept)
    db.flush()
    log_audit_event(db, org_id, current_user.id, "create_department", "Department", dept.id)
    db.commit()
    db.refresh(dept)
    return dept


@router.get("/departments", response_model=list[DepartmentOut], dependencies=[Depends(require_permission("hr", "view"))])
def list_departments(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return db.query(Department).filter(Department.org_id == org_id).order_by(Department.name).all()


def _position_out(db: Session, p: Position) -> dict:
    count = db.query(func.count(Employee.id)).filter(Employee.position_id == p.id, Employee.status == "active").scalar() or 0
    return {
        "id": p.id, "department_id": p.department_id, "department_name": p.department.name if p.department else None,
        "title": p.title, "base_salary": p.base_salary, "access_role_id": p.access_role_id,
        "access_role_name": p.access_role.name if p.access_role else None, "employee_count": count,
    }


def _check_access_role(db: Session, org_id, role_id):
    if role_id and not db.query(Role.id).filter(Role.id == role_id, Role.org_id == org_id).first():
        raise HTTPException(404, "Access role not found in this organization.")


@router.post("/positions", response_model=PositionOut, status_code=201, dependencies=[Depends(require_permission("hr", "approve"))])
def create_position(payload: PositionCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    dept = db.query(Department).filter(Department.id == payload.department_id, Department.org_id == org_id).first()
    if not dept:
        raise HTTPException(404, "Department not found")
    _check_access_role(db, org_id, payload.access_role_id)
    title = payload.title.strip()
    if db.query(Position.id).filter(Position.org_id == org_id, Position.department_id == dept.id, func.lower(Position.title) == title.lower()).first():
        raise HTTPException(400, f"'{title}' already exists in {dept.name}.")
    pos = Position(org_id=org_id, department_id=dept.id, title=title, base_salary=payload.base_salary, access_role_id=payload.access_role_id)
    db.add(pos)
    db.flush()
    ensure_position_role(db, org_id, pos)  # shows up under Settings > Roles & Permissions automatically
    log_audit_event(db, org_id, current_user.id, "create_position", "Position", pos.id)
    db.commit()
    db.refresh(pos)
    return _position_out(db, pos)


@router.get("/positions", response_model=list[PositionOut], dependencies=[Depends(require_permission("hr", "view"))])
def list_positions(department_id: str | None = None, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    q = db.query(Position).options(joinedload(Position.department), joinedload(Position.access_role)).filter(Position.org_id == org_id)
    if department_id:
        q = q.filter(Position.department_id == department_id)
    return [_position_out(db, p) for p in q.order_by(Position.title).all()]


@router.patch("/positions/{position_id}", response_model=PositionOut, dependencies=[Depends(require_permission("hr", "approve"))])
def update_position(position_id: str, payload: PositionUpdate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    pos = db.query(Position).filter(Position.id == position_id, Position.org_id == org_id).first()
    if not pos:
        raise HTTPException(404, "Position not found")
    if payload.title is not None:
        title = payload.title.strip()
        clash = db.query(Position.id).filter(Position.org_id == org_id, Position.department_id == pos.department_id,
                                             func.lower(Position.title) == title.lower(), Position.id != pos.id).first()
        if clash:
            raise HTTPException(400, f"'{title}' already exists in this department.")
        old_title = pos.title
        pos.title = title
        db.query(Employee).filter(Employee.position_id == pos.id).update({"designation": title})
        rename_position_role(db, org_id, pos, old_title)
    if payload.clear_access_role:
        pos.access_role_id = None
    elif payload.access_role_id is not None:
        _check_access_role(db, org_id, payload.access_role_id)
        pos.access_role_id = payload.access_role_id
    if not pos.access_role_id:
        ensure_position_role(db, org_id, pos)
    if payload.base_salary is not None:
        pos.base_salary = payload.base_salary
        if payload.apply_to_existing:
            db.query(Employee).filter(Employee.position_id == pos.id).update({"salary": payload.base_salary})
    log_audit_event(db, org_id, current_user.id, "update_position", "Position", pos.id)
    db.commit()
    db.refresh(pos)
    return _position_out(db, pos)


# ---------------- Leave policy legend ----------------
@router.get("/leave-types", response_model=list[LeaveTypeOut], dependencies=[Depends(require_permission("hr", "view"))])
def list_leave_types(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    types = get_leave_types(db, org_id)
    db.commit()
    return types


@router.patch("/leave-types/{type_id}", response_model=LeaveTypeOut, dependencies=[Depends(require_permission("hr", "approve"))])
def update_leave_type(type_id: str, payload: LeaveTypeUpdate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    lt = db.query(LeaveType).filter(LeaveType.id == type_id, LeaveType.org_id == org_id).first()
    if not lt:
        raise HTTPException(404, "Leave type not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(lt, k, v)
    log_audit_event(db, org_id, current_user.id, "update_leave_type", "LeaveType", lt.id)
    db.commit()
    db.refresh(lt)
    return lt


# ---------------- Employees ----------------
def _next_employee_code(db: Session, org_id) -> str:
    db.flush()
    db.query(Organization).filter(Organization.id == org_id).with_for_update().first()
    n = db.query(func.count(Employee.id)).filter(Employee.org_id == org_id).scalar() or 0
    while True:
        n += 1
        code = f"EMP-{n:04d}"
        if not db.query(Employee.id).filter(Employee.org_id == org_id, Employee.employee_code == code).first():
            return code


def _employee_out(e: Employee, users: dict | None = None) -> dict:
    u = None
    if e.user_id:
        u = (users or {}).get(e.user_id) or e.__dict__.get("_user")
    return {
        "id": e.id, "employee_code": e.employee_code, "name": e.name, "designation": e.designation,
        "department_id": e.department_id, "department_name": e.department.name if e.department else None,
        "position_id": e.position_id, "joining_date": e.joining_date, "salary": e.salary, "status": e.status,
        "user_id": e.user_id, "login_status": u.status if u else None, "login_email": u.email if u else None,
        "access_role_name": (u.role.name if u and u.role else None),
        "employment_type": e.employment_type, "phone": e.phone, "personal_email": e.personal_email,
        "date_of_birth": e.date_of_birth, "gender": e.gender, "address": e.address,
        "emergency_contact_name": e.emergency_contact_name, "emergency_contact_phone": e.emergency_contact_phone,
    }


def _users_for(db: Session, employees: list[Employee]) -> dict:
    ids = [e.user_id for e in employees if e.user_id]
    if not ids:
        return {}
    return {u.id: u for u in db.query(User).options(joinedload(User.role)).filter(User.id.in_(ids)).all()}


def _load_employee(db: Session, org_id, employee_id) -> Employee:
    e = (db.query(Employee).options(joinedload(Employee.department))
         .filter(Employee.id == employee_id, Employee.org_id == org_id).first())
    if not e:
        raise HTTPException(404, "Employee not found")
    return e


@router.post("/employees", response_model=EmployeeOut, status_code=201, dependencies=[Depends(require_permission("hr", "create"))])
def create_employee(payload: EmployeeCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    data = payload.model_dump(exclude={"position_id", "designation", "salary", "department_id"})
    position = None
    if payload.position_id:
        position = db.query(Position).filter(Position.id == payload.position_id, Position.org_id == org_id).first()
        if not position:
            raise HTTPException(404, "Position not found")
        if payload.department_id and payload.department_id != position.department_id:
            raise HTTPException(400, "That position does not belong to the chosen department.")
        data.update(department_id=position.department_id, position_id=position.id,
                    designation=position.title, salary=position.base_salary)
    else:
        # No position chosen: salary and designation would be typed by hand, which only an authoriser may do.
        if not user_has_permission(db, current_user, "hr", "approve"):
            raise HTTPException(400, "Choose a department and a role. The salary comes from the role, set up beforehand by an administrator.")
        if payload.department_id and not db.query(Department.id).filter(Department.id == payload.department_id, Department.org_id == org_id).first():
            raise HTTPException(404, "Department not found")
        data.update(department_id=payload.department_id, designation=payload.designation,
                    salary=payload.salary if payload.salary is not None else Decimal("0"))
    if payload.user_id and not db.query(User.id).filter(User.id == payload.user_id, User.org_id == org_id).first():
        raise HTTPException(404, "User not found")
    employee = Employee(org_id=org_id, employee_code=_next_employee_code(db, org_id), **data)
    db.add(employee)
    db.flush()
    log_audit_event(db, org_id, current_user.id, "create_employee", "Employee", employee.id)
    db.commit()
    employee = _load_employee(db, org_id, employee.id)
    return _employee_out(employee, _users_for(db, [employee]))


@router.get("/employees", response_model=list[EmployeeOut], dependencies=[Depends(require_permission("hr", "view"))])
def list_employees(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    employees = (db.query(Employee).options(joinedload(Employee.department))
                 .filter(Employee.org_id == org_id, Employee.status == "active")
                 .order_by(Employee.employee_code, Employee.name).all())
    users = _users_for(db, employees)
    return [_employee_out(e, users) for e in employees]


@router.get("/employees/export", dependencies=[Depends(require_permission("hr", "view"))])
def export_employees_csv(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    employees = db.query(Employee).options(joinedload(Employee.department)).filter(
        Employee.org_id == org_id, Employee.status == "active"
    ).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["employee_code", "name", "designation", "department_name", "salary"])
    for e in employees:
        writer.writerow([e.employee_code or "", e.name, e.designation or "", e.department.name if e.department else "", e.salary])

    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=employees.csv"},
    )


@router.get("/employees/{employee_id}", response_model=EmployeeOut, dependencies=[Depends(require_permission("hr", "view"))])
def get_employee(employee_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    e = _load_employee(db, org_id, employee_id)
    return _employee_out(e, _users_for(db, [e]))


@router.patch("/employees/{employee_id}", response_model=EmployeeOut, dependencies=[Depends(require_permission("hr", "edit"))])
def update_employee(employee_id: str, payload: EmployeeUpdate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    e = _load_employee(db, org_id, employee_id)
    data = payload.model_dump(exclude_unset=True)
    new_pos = data.pop("position_id", None)
    if new_pos is not None and new_pos != e.position_id:
        if not user_has_permission(db, current_user, "hr", "approve"):
            raise HTTPException(403, "Your role does not have 'approve' access to 'hr'. Changing someone's role changes their salary, so it needs approval authority.")
        position = db.query(Position).filter(Position.id == new_pos, Position.org_id == org_id).first()
        if not position:
            raise HTTPException(404, "Position not found")
        e.position_id, e.department_id, e.designation, e.salary = position.id, position.department_id, position.title, position.base_salary
    for k, v in data.items():
        setattr(e, k, v)
    log_audit_event(db, org_id, current_user.id, "update_employee", "Employee", e.id)
    db.commit()
    e = _load_employee(db, org_id, employee_id)
    return _employee_out(e, _users_for(db, [e]))


@router.post("/employees/{employee_id}/create-login", response_model=EmployeeOut, dependencies=[Depends(require_permission("core", "manage_access"))])
def create_employee_login(employee_id: str, payload: CreateLoginIn, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    """
    Gives an employee a system login with the access role their position maps
    to (Settings > Users will show it, status 'invited', until they accept the
    emailed link). Needs manage_access because it grants a role.
    """
    e = _load_employee(db, org_id, employee_id)
    if e.user_id:
        raise HTTPException(400, "This employee already has a login.")
    position = db.query(Position).filter(Position.id == e.position_id).first() if e.position_id else None
    if not position or not position.access_role_id:
        raise HTTPException(400, "This employee's position has no access role. Set one on the position (Departments & Roles) first, so the login gets the right permissions.")
    if db.query(User.id).filter(User.email == payload.email).first():
        raise HTTPException(400, "A user with this email already exists.")
    org = db.query(Organization).filter(Organization.id == org_id).first()
    user = create_invited_user(db, org_id, org.name, e.name, payload.email, position.access_role_id)
    e.user_id = user.id
    log_audit_event(db, org_id, current_user.id, "create_employee_login", "Employee", e.id)
    db.commit()
    e = _load_employee(db, org_id, employee_id)
    return _employee_out(e, _users_for(db, [e]))


MAX_EMPLOYEE_IMPORT_ROWS = 1000


@router.post("/employees/import", dependencies=[Depends(require_permission("hr", "create"))])
async def import_employees_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    org_id: str = Depends(get_org_id),
    current_user=Depends(get_current_user),
):
    """
    Same partial-success design as CRM Leads' import - a bad row never
    blocks the good ones, capped at MAX_EMPLOYEE_IMPORT_ROWS for the
    same synchronous-endpoint-abuse reason.

    One real difference from Leads: department_name is a human-readable
    lookup, not a raw column, since a CSV author has no reason to know
    a department's internal UUID. Deliberately forgiving on a miss - an
    unrecognized department name does NOT fail the row, it just leaves
    that employee unassigned to a department, matching this project's
    general preference for a partially-correct result over a rejected
    one when the ambiguity is minor and easily fixed later (reassign
    the department from the UI, no re-import needed).
    """
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(400, "Could not read this file as UTF-8 text - please export it as a plain CSV.")

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or "name" not in reader.fieldnames:
        raise HTTPException(400, "CSV must have a 'name' column header. Optional columns: designation, department_name, salary.")

    rows = list(reader)
    if len(rows) > MAX_EMPLOYEE_IMPORT_ROWS:
        raise HTTPException(400, f"This file has {len(rows)} rows - the limit is {MAX_EMPLOYEE_IMPORT_ROWS} per import.")

    departments_by_name = {
        d.name.strip().lower(): d.id
        for d in db.query(Department).filter(Department.org_id == org_id).all()
    }
    positions_by_key = {
        (p.department_id, p.title.strip().lower()): p
        for p in db.query(Position).filter(Position.org_id == org_id).all()
    }
    can_set_salary = user_has_permission(db, current_user, "hr", "approve")

    imported = 0
    errors: list[dict] = []
    new_employees = []

    for i, row in enumerate(rows, start=2):
        name = (row.get("name") or "").strip()
        if not name:
            errors.append({"row": i, "reason": "'name' is required and was empty"})
            continue

        salary_raw = (row.get("salary") or "0").strip()
        try:
            salary = Decimal(salary_raw) if salary_raw else Decimal("0")
        except Exception:
            errors.append({"row": i, "reason": f"'{salary_raw}' is not a valid salary number"})
            continue

        dept_name = (row.get("department_name") or "").strip()
        department_id = departments_by_name.get(dept_name.lower()) if dept_name else None
        designation = (row.get("designation") or "").strip() or None

        # A role (position) found for this department wins: salary then comes from it, not from the file.
        position = positions_by_key.get((department_id, (designation or "").lower())) if department_id and designation else None
        if position:
            salary, designation = position.base_salary, position.title
        elif not can_set_salary:
            salary = Decimal("0")  # salary typed into a file is only honoured for someone with approval authority

        new_employees.append(Employee(
            org_id=org_id,
            name=name,
            designation=designation,
            department_id=department_id,
            position_id=position.id if position else None,
            salary=salary,
        ))
        imported += 1

    if new_employees:
        for emp in new_employees:
            emp.employee_code = _next_employee_code(db, org_id)
            db.add(emp)
            db.flush()
        log_audit_event(db, org_id, current_user.id, f"bulk_import ({imported} employees)", "Employee", None)
        db.commit()

    return {"imported": imported, "failed": len(errors), "errors": errors}


# ---------------- Leave Requests ----------------
# Employees file their own leave from "My Leaves" (app/api/routes/self_service.py).
# This route is for an administrator or HR user recording leave on someone's behalf
# (a phone call, a paper form); it uses the same rules but has no back-dating limit.
@router.post("/leave-requests", response_model=LeaveRequestOut, status_code=201, dependencies=[Depends(require_permission("hr", "create"))])
def create_leave_request(payload: LeaveRequestCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    employee = db.query(Employee).filter(Employee.id == payload.employee_id, Employee.org_id == org_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    leave = leave_rules.create_leave(db, employee, payload.leave_type, payload.start_date, payload.end_date, payload.reason, self_service=False)
    log_audit_event(db, org_id, current_user.id, "file_leave_for_employee", "LeaveRequest", leave.id)
    db.commit()
    db.refresh(leave)
    return leave


@router.get("/leave-requests", response_model=list[LeaveRequestOut], dependencies=[Depends(require_permission("hr", "view"))])
def list_leave_requests(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return (
        db.query(LeaveRequest)
        .join(Employee, Employee.id == LeaveRequest.employee_id)
        .filter(Employee.org_id == org_id)
        .order_by(LeaveRequest.created_at.desc())
        .all()
    )


@router.patch("/leave-requests/{leave_id}/status", response_model=LeaveRequestOut, dependencies=[Depends(require_permission("hr", "approve"))])
def update_leave_status(leave_id: str, payload: LeaveStatusUpdate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    leave = (
        db.query(LeaveRequest)
        .join(Employee, Employee.id == LeaveRequest.employee_id)
        .filter(LeaveRequest.id == leave_id, Employee.org_id == org_id)
        .first()
    )
    if not leave:
        raise HTTPException(status_code=404, detail="Leave request not found")
    if leave.status == "cancelled":
        raise HTTPException(400, "The employee cancelled this request.")
    leave.status = payload.status
    leave.decided_by, leave.decided_at = (current_user.id, datetime.utcnow()) if payload.status != "pending" else (None, None)
    leave.decision_note = (payload.note or "").strip() or None

    # Notify the employee, if they have a login (user_id is optional on
    # Employee - plenty of employees never need one). Soft-fail by design:
    # notify_user() silently no-ops when user_id is None.
    employee = db.query(Employee).filter(Employee.id == leave.employee_id).first()
    if employee:
        extra = f" Note: {leave.decision_note}" if leave.decision_note else ""
        notify_user(
            db, org_id, employee.user_id,
            f"Your leave request ({leave.start_date} to {leave.end_date}) was {payload.status}.{extra}",
        )
    log_audit_event(db, org_id, current_user.id, f"leave_{payload.status}", "LeaveRequest", leave.id)

    db.commit()
    db.refresh(leave)
    return leave


# ---------------- Attendance (marked by an administrator only) ----------------
ATTENDANCE_BACKDATE_DAYS = 60


def _attendance_day(d: date | None) -> date:
    d = d or date.today()
    if d > date.today():
        raise HTTPException(400, "Attendance cannot be marked for a future date.")
    if d < date.today() - timedelta(days=ATTENDANCE_BACKDATE_DAYS):
        raise HTTPException(400, f"Attendance can be recorded for the last {ATTENDANCE_BACKDATE_DAYS} days only.")
    return d


def _upsert_attendance(db: Session, employee_id, day: date, status: str, user_id) -> Attendance:
    row = db.query(Attendance).filter(Attendance.employee_id == employee_id, Attendance.date == day).first()
    if row:
        row.status, row.marked_by = status, user_id
    else:
        row = Attendance(employee_id=employee_id, date=day, status=status, marked_by=user_id)
        db.add(row)
    return row


@router.post("/attendance", response_model=AttendanceOut, status_code=201, dependencies=[Depends(require_permission("core", "manage_access"))])
def mark_attendance(payload: AttendanceMark, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    employee = db.query(Employee).filter(Employee.id == payload.employee_id, Employee.org_id == org_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    day = _attendance_day(payload.date)
    row = _upsert_attendance(db, employee.id, day, payload.status, current_user.id)
    log_audit_event(db, org_id, current_user.id, "mark_attendance", "Attendance", employee.id)
    db.commit()
    db.refresh(row)
    return row


@router.post("/attendance/bulk", dependencies=[Depends(require_permission("core", "manage_access"))])
def mark_attendance_bulk(payload: AttendanceBulk, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    day = _attendance_day(payload.date)
    ids = {e.employee_id for e in payload.entries}
    valid = {e.id for e in db.query(Employee).filter(Employee.org_id == org_id, Employee.id.in_(ids)).all()}
    if ids - valid:
        raise HTTPException(404, "One or more employees were not found.")
    for e in payload.entries:
        _upsert_attendance(db, e.employee_id, day, e.status, current_user.id)
    log_audit_event(db, org_id, current_user.id, f"mark_attendance_bulk ({len(payload.entries)} employees, {day})", "Attendance", None)
    db.commit()
    return {"date": day, "saved": len(payload.entries)}


@router.get("/attendance/day", dependencies=[Depends(require_permission("hr", "view"))])
def attendance_for_day(day: date | None = Query(None, alias="date"), db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    """Every active employee with their mark for the day (or 'leave' if approved leave covers it and nobody marked them)."""
    d = day or date.today()
    emps = db.query(Employee).options(joinedload(Employee.department)).filter(Employee.org_id == org_id, Employee.status == "active").order_by(Employee.name).all()
    marks = {a.employee_id: a for a in db.query(Attendance).filter(Attendance.date == d, Attendance.employee_id.in_([e.id for e in emps])).all()}
    on_leave = leave_rules.approved_leave_on(db, [e.id for e in emps], d)
    rows = []
    for e in emps:
        m = marks.get(e.id)
        rows.append({"employee_id": e.id, "employee_code": e.employee_code, "name": e.name,
                     "department_name": e.department.name if e.department else None,
                     "status": m.status if m else None, "marked": m is not None,
                     "on_approved_leave": e.id in on_leave})
    return {"date": d, "employees": rows}


@router.get("/attendance/summary", dependencies=[Depends(require_permission("hr", "view"))])
def attendance_summary(month: int = Query(..., ge=1, le=12), year: int = Query(..., ge=2000, le=2100), db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    first, last = date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
    emps = db.query(Employee).filter(Employee.org_id == org_id, Employee.status == "active").order_by(Employee.name).all()
    counts: dict = {e.id: {"present": 0, "absent": 0, "half_day": 0, "leave": 0} for e in emps}
    for a in db.query(Attendance).filter(Attendance.employee_id.in_(list(counts) or [None]), Attendance.date >= first, Attendance.date <= last).all():
        counts[a.employee_id][a.status] += 1
    return [{"employee_id": e.id, "employee_code": e.employee_code, "name": e.name, **counts[e.id]} for e in emps]


@router.get("/attendance", response_model=list[AttendanceOut], dependencies=[Depends(require_permission("hr", "view"))])
def list_attendance(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return (
        db.query(Attendance)
        .join(Employee, Employee.id == Attendance.employee_id)
        .filter(Employee.org_id == org_id)
        .order_by(Attendance.date.desc())
        .all()
    )


# ---------------- Payroll ----------------
@router.post("/payroll-runs", response_model=PayrollRunOut, status_code=201, dependencies=[Depends(require_permission("hr", "create"))])
def create_payroll_run(payload: PayrollRunCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    existing = db.query(PayrollRun).filter(
        PayrollRun.org_id == org_id, PayrollRun.month == payload.month, PayrollRun.year == payload.year
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="A payroll run for this month already exists.")

    run = PayrollRun(org_id=org_id, month=payload.month, year=payload.year)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


@router.get("/payroll-runs", response_model=list[PayrollRunOut], dependencies=[Depends(require_permission("hr", "view"))])
def list_payroll_runs(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return (
        db.query(PayrollRun)
        .options(joinedload(PayrollRun.payslips))
        .filter(PayrollRun.org_id == org_id)
        .order_by(PayrollRun.year.desc(), PayrollRun.month.desc())
        .all()
    )


@router.post("/payroll-runs/{run_id}/process", response_model=PayrollRunOut, dependencies=[Depends(require_permission("hr", "edit"))])
def process_payroll_run(run_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    """
    One payslip per active employee, using what Finance filled in: PF /
    insurance / TDS percentages (per employee) and unpaid-leave days (per run;
    falls back to approved Loss-of-Pay leave in that month). An employee Finance
    has not filled in is paid with 0% deductions and counted in
    `employees_without_deductions` so nobody is surprised.
    ONE journal entry posts for the run: Dr Payroll Expense (gross less unpaid
    leave), Cr Cash (net), Cr Payroll Deductions Payable (PF + insurance + TDS).
    """
    run = db.query(PayrollRun).filter(PayrollRun.id == run_id, PayrollRun.org_id == org_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    if run.status == "processed":
        raise HTTPException(status_code=400, detail="This payroll run has already been processed.")

    employees = db.query(Employee).filter(Employee.org_id == org_id, Employee.status == "active").all()
    if not employees:
        raise HTTPException(status_code=400, detail="No active employees to process payroll for.")

    profiles = {p.employee_id: p for p in db.query(EmployeePayrollProfile).filter(EmployeePayrollProfile.org_id == org_id).all()}
    inputs = {i.employee_id: i for i in db.query(PayrollInput).filter(PayrollInput.payroll_run_id == run.id).all()}

    total_net = Decimal(0)
    total_expense = Decimal(0)
    total_statutory = Decimal(0)
    missing = 0
    for employee in employees:
        profile = profiles.get(employee.id)
        if profile is None:
            missing += 1
        lop = inputs[employee.id].lop_days if employee.id in inputs else lop_days_from_approved_leave(db, employee, run.month, run.year)
        c = compute_payslip(employee.salary, profile, lop, run.month, run.year)
        statutory = c["pf_amount"] + c["insurance_amount"] + c["tds_amount"]
        total_net += c["net_pay"]
        total_statutory += statutory
        total_expense += c["gross"] - c["leave_deduction"]
        db.add(Payslip(
            payroll_run_id=run.id, employee_id=employee.id, gross=c["gross"], deductions=c["deductions"], net_pay=c["net_pay"],
            pf_percent=c["pf_percent"], insurance_percent=c["insurance_percent"], tds_percent=c["tds_percent"],
            pf_amount=c["pf_amount"], insurance_amount=c["insurance_amount"], tds_amount=c["tds_amount"],
            lop_days=c["lop_days"], leave_deduction=c["leave_deduction"],
        ))

    run.status = "processed"
    db.flush()

    try:
        post_payroll_journal_entry(db, org_id, str(run.id), total_net, total_expense=total_expense, statutory_deductions=total_statutory)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))

    log_audit_event(db, org_id, current_user.id, "process_payroll", "PayrollRun", run.id)
    db.commit()
    db.refresh(run)
    out = PayrollRunOut.model_validate(run)
    out.employees_without_deductions = missing
    return out
