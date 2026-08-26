"""
HR module routes. Departments/Employees/Attendance/Leave are plain CRUD.
The interesting part is /payroll-runs/{id}/process - the same "one action,
multiple module effects, one transaction" pattern used by Sales' invoice
generation and Procurement's goods receipt: it generates a Payslip per
active Employee AND posts a single Journal Entry to Finance, together.
"""
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.api.deps import get_current_user, get_org_id, require_permission
from app.models.hr import Department, Employee, Attendance, LeaveRequest, PayrollRun, Payslip
from app.schemas.hr import (
    DepartmentCreate, DepartmentOut,
    EmployeeCreate, EmployeeOut,
    LeaveRequestCreate, LeaveRequestOut, LeaveStatusUpdate,
    AttendanceMark, AttendanceOut,
    PayrollRunCreate, PayrollRunOut,
)
from app.services.accounting import post_payroll_journal_entry
from app.services.notifications import notify_user
from app.services.audit import log_audit_event

router = APIRouter(prefix="/api/hr", tags=["hr"], dependencies=[Depends(get_current_user)])


# ---------------- Departments ----------------
@router.post("/departments", response_model=DepartmentOut, status_code=201, dependencies=[Depends(require_permission("hr", "create"))])
def create_department(payload: DepartmentCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    dept = Department(org_id=org_id, name=payload.name)
    db.add(dept)
    db.commit()
    db.refresh(dept)
    return dept


@router.get("/departments", response_model=list[DepartmentOut], dependencies=[Depends(require_permission("hr", "view"))])
def list_departments(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return db.query(Department).filter(Department.org_id == org_id).all()


# ---------------- Employees ----------------
@router.post("/employees", response_model=EmployeeOut, status_code=201, dependencies=[Depends(require_permission("hr", "create"))])
def create_employee(payload: EmployeeCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    employee = Employee(org_id=org_id, **payload.model_dump())
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return employee


@router.get("/employees", response_model=list[EmployeeOut], dependencies=[Depends(require_permission("hr", "view"))])
def list_employees(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return db.query(Employee).filter(Employee.org_id == org_id, Employee.status == "active").all()


# ---------------- Leave Requests ----------------
@router.post("/leave-requests", response_model=LeaveRequestOut, status_code=201, dependencies=[Depends(require_permission("hr", "create"))])
def create_leave_request(payload: LeaveRequestCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    employee = db.query(Employee).filter(Employee.id == payload.employee_id, Employee.org_id == org_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    leave = LeaveRequest(**payload.model_dump())
    db.add(leave)
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
def update_leave_status(leave_id: str, payload: LeaveStatusUpdate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    leave = (
        db.query(LeaveRequest)
        .join(Employee, Employee.id == LeaveRequest.employee_id)
        .filter(LeaveRequest.id == leave_id, Employee.org_id == org_id)
        .first()
    )
    if not leave:
        raise HTTPException(status_code=404, detail="Leave request not found")
    leave.status = payload.status

    # Notify the employee, if they have a login (user_id is optional on
    # Employee — plenty of employees never need one). Soft-fail by design:
    # notify_user() silently no-ops when user_id is None, same as every
    # other self-healing helper in this codebase.
    employee = db.query(Employee).filter(Employee.id == leave.employee_id).first()
    if employee:
        notify_user(
            db, org_id, employee.user_id,
            f"Your leave request ({leave.start_date} to {leave.end_date}) was {payload.status}.",
        )

    db.commit()
    db.refresh(leave)
    return leave


# ---------------- Attendance ----------------
@router.post("/attendance", response_model=AttendanceOut, status_code=201, dependencies=[Depends(require_permission("hr", "create"))])
def mark_attendance(payload: AttendanceMark, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    employee = db.query(Employee).filter(Employee.id == payload.employee_id, Employee.org_id == org_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    existing = db.query(Attendance).filter(Attendance.employee_id == payload.employee_id, Attendance.date == date.today()).first()
    if existing:
        existing.status = payload.status
        db.commit()
        db.refresh(existing)
        return existing

    record = Attendance(employee_id=payload.employee_id, status=payload.status, date=date.today())
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


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
    Generates a Payslip for every active Employee (a flat 10% deduction,
    for demo purposes - a real system would model tax slabs, PF, etc. as
    their own configurable rules, a reasonable later enhancement) and
    posts ONE Journal Entry for the run's total net pay - same
    commit-together guarantee used everywhere else in this codebase.
    """
    run = db.query(PayrollRun).filter(PayrollRun.id == run_id, PayrollRun.org_id == org_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    if run.status == "processed":
        raise HTTPException(status_code=400, detail="This payroll run has already been processed.")

    employees = db.query(Employee).filter(Employee.org_id == org_id, Employee.status == "active").all()
    if not employees:
        raise HTTPException(status_code=400, detail="No active employees to process payroll for.")

    total_net_pay = 0
    for employee in employees:
        gross = employee.salary
        deductions = gross * Decimal("0.10")
        net_pay = gross - deductions
        total_net_pay += net_pay
        db.add(Payslip(payroll_run_id=run.id, employee_id=employee.id, gross=gross, deductions=deductions, net_pay=net_pay))

    run.status = "processed"
    db.flush()

    try:
        post_payroll_journal_entry(db, org_id, str(run.id), total_net_pay)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))

    log_audit_event(db, org_id, current_user.id, "process_payroll", "PayrollRun", run.id)
    db.commit()
    db.refresh(run)
    return run
