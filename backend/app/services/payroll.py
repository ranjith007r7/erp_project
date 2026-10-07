"""
Payroll maths and the leave-policy legend, in one place so the HR route that
processes a run and the Finance screen that previews it can never disagree.
"""
import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import Session

from app.models.hr import LeaveType, LeaveRequest, EmployeePayrollProfile

# Common Indian-industry norms (Shops & Establishments / typical private-sector
# policy). Orgs can edit them; these only seed what is missing.
DEFAULT_LEAVE_TYPES = [
    # code, name, days/year, per month, paid, note
    ("CL", "Casual Leave", 12, "1", True, "1 day per month; short personal needs"),
    ("SL", "Sick Leave", 12, "1", True, "1 day per month; medical certificate usually needed beyond 2 days"),
    ("EL", "Earned / Privilege Leave", 15, "1.25", True, "Accrues with days worked; can be carried forward or encashed"),
    ("ML", "Maternity Leave", 182, None, True, "26 weeks, per the Maternity Benefit Act"),
    ("PL", "Paternity Leave", 15, None, True, "Around childbirth"),
    ("MRG", "Marriage Leave", 5, None, True, "Once, on the employee's own marriage"),
    ("BL", "Bereavement Leave", 3, None, True, "Death of an immediate family member"),
    ("CO", "Compensatory Off", None, None, True, "Day off in lieu of working a holiday or weekend"),
    ("LOP", "Loss of Pay (Unpaid)", None, None, False, "Leave beyond entitlement or without approval. Salary is cut for these days"),
]


def get_leave_types(db: Session, org_id) -> list[LeaveType]:
    """Self-healing, like get_account(): any default the org is missing is created on the spot."""
    have = {t.code: t for t in db.query(LeaveType).filter(LeaveType.org_id == org_id).all()}
    for code, name, per_year, per_month, paid, note in DEFAULT_LEAVE_TYPES:
        if code not in have:
            t = LeaveType(org_id=org_id, code=code, name=name, days_per_year=per_year,
                          per_month=Decimal(per_month) if per_month else None, paid=paid, note=note)
            db.add(t)
            have[code] = t
    db.flush()
    order = [c[0] for c in DEFAULT_LEAVE_TYPES]
    return sorted(have.values(), key=lambda t: order.index(t.code) if t.code in order else 99)


def lop_days_from_approved_leave(db: Session, employee, month: int, year: int) -> Decimal:
    """Approved leave of an UNPAID type (e.g. Loss of Pay) falling in that month: the suggested LOP days."""
    unpaid = {t.name.lower() for t in get_leave_types(db, employee.org_id) if not t.paid} | \
             {t.code.lower() for t in get_leave_types(db, employee.org_id) if not t.paid}
    first, last = date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
    total = 0
    for lr in db.query(LeaveRequest).filter(LeaveRequest.employee_id == employee.id, LeaveRequest.status == "approved").all():
        if (lr.leave_type or "").strip().lower() not in unpaid:
            continue
        start, end = max(lr.start_date, first), min(lr.end_date, last)
        if end >= start:
            total += (end - start).days + 1
    return Decimal(total)


def _money(v) -> Decimal:
    return Decimal(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def compute_payslip(salary, profile: EmployeePayrollProfile | None, lop_days, month: int, year: int) -> dict:
    """
    PF / insurance / TDS are percentages of the monthly salary. Unpaid leave is
    salary / days-in-that-month per day (so 1 day off in a 30-day month costs
    1/30 of the salary). Deductions never exceed the salary.
    """
    gross = _money(salary)
    pf_pct = Decimal(profile.pf_percent) if profile else Decimal(0)
    ins_pct = Decimal(profile.insurance_percent) if profile else Decimal(0)
    tds_pct = Decimal(profile.tds_percent) if profile else Decimal(0)
    lop = Decimal(lop_days or 0)
    days_in_month = calendar.monthrange(year, month)[1]

    pf = _money(gross * pf_pct / 100)
    ins = _money(gross * ins_pct / 100)
    tds = _money(gross * tds_pct / 100)
    leave = min(_money(gross / days_in_month * lop), gross - (pf + ins + tds))  # net pay never goes below 0
    total = pf + ins + tds + leave
    return {
        "gross": gross, "pf_percent": pf_pct, "insurance_percent": ins_pct, "tds_percent": tds_pct,
        "pf_amount": pf, "insurance_amount": ins, "tds_amount": tds,
        "lop_days": lop, "leave_deduction": leave,
        "deductions": total, "net_pay": gross - total,
    }
