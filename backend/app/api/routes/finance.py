"""
Finance module routes. Two read-only views (accounts, journal entries) plus
one real action: recording a Payment against an Invoice, which posts its
own Journal Entry through the same shared accounting service Sales uses.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.api.deps import get_current_user, get_org_id, require_permission
import re
from decimal import Decimal

from app.models.finance import ChartOfAccounts, JournalEntry, Payment
from app.models.sales import Invoice
from app.schemas.finance import (
    AccountOut, JournalEntryOut, PaymentCreate, PaymentOut, METHODS_NEEDING_REFERENCE,
    DeductionProfileIn, DeductionRow, LopIn, LeaveTypeOut, RunSummary,
)
from app.models.hr import Employee, EmployeePayrollProfile, PayrollRun, PayrollInput
from app.services.payroll import get_leave_types, lop_days_from_approved_leave
from app.services.accounting import post_payment_journal_entry
from app.services.notifications import notify_role
from app.services.audit import log_audit_event

router = APIRouter(prefix="/api/finance", tags=["finance"], dependencies=[Depends(get_current_user)])

TXN_RE = re.compile(r"^[A-Za-z0-9._\-/]{4,64}$")


@router.get("/accounts", response_model=list[AccountOut], dependencies=[Depends(require_permission("finance", "view"))])
def list_accounts(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return db.query(ChartOfAccounts).filter(ChartOfAccounts.org_id == org_id).order_by(ChartOfAccounts.code).all()


@router.get("/journal-entries", response_model=list[JournalEntryOut], dependencies=[Depends(require_permission("finance", "view"))])
def list_journal_entries(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return (
        db.query(JournalEntry)
        .options(joinedload(JournalEntry.lines))
        .filter(JournalEntry.org_id == org_id)
        .order_by(JournalEntry.date.desc(), JournalEntry.entry_number.desc())
        .all()
    )


@router.post("/payments", response_model=PaymentOut, status_code=201, dependencies=[Depends(require_permission("finance", "create"))])
def record_payment(payload: PaymentCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    """
    Records money received against an Invoice, marks the Invoice paid (or
    partially - see note below), and posts the matching Journal Entry -
    same commit-together guarantee as Sales' invoice generation.
    """
    invoice = db.query(Invoice).filter(Invoice.id == payload.invoice_id, Invoice.org_id == org_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status == "paid":
        raise HTTPException(status_code=400, detail="This invoice is already fully paid.")

    txn = (payload.transaction_id or "").strip() or None
    if payload.method in METHODS_NEEDING_REFERENCE:
        label = {"card": "card", "gpay": "GPay", "bank_transfer": "bank transfer"}[payload.method]
        if not txn:
            raise HTTPException(status_code=400, detail=f"Enter the transaction ID for the {label} payment. A {label} payment is only recorded with its transaction ID.")
        if not TXN_RE.match(txn):
            raise HTTPException(status_code=400, detail="The transaction ID must be 4-64 characters: letters, numbers, dash, underscore, dot or slash.")
        if db.query(Payment.id).filter(Payment.org_id == org_id, Payment.transaction_id == txn).first():
            raise HTTPException(status_code=400, detail=f"Transaction ID {txn} is already recorded against another payment.")
    else:
        txn = None  # cash has no reference

    payment = Payment(
        org_id=org_id,
        invoice_id=invoice.id,
        amount=payload.amount,
        method=payload.method,
        transaction_id=txn,
        recorded_by=current_user.id,
    )
    db.add(payment)
    db.flush()  # generates payment.id for the journal entry reference

    try:
        note = {"cash": "Cash", "card": "Card", "gpay": "GPay", "bank_transfer": "Bank transfer"}[payload.method]
        if txn:
            note += f", txn {txn}"
        post_payment_journal_entry(db, org_id, str(payment.id), payment.amount, note=note)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Simple model for now: any payment recorded marks the invoice fully
    # paid. Partial-payment tracking (amount_paid vs amount_due) is a
    # reasonable Phase-4-or-later refinement, not needed for the demo story.
    invoice.status = "paid"

    # Real trigger #1 of 2 for "notifications only cover a few things" -
    # invoice payment recorded is exactly the kind of event a real org
    # would want to know about without someone manually checking Finance.
    notify_role(db, org_id, "Admin", f"Payment of {payment.amount} recorded against an invoice — now marked paid.")

    log_audit_event(db, org_id, current_user.id, "record_payment", "Invoice", invoice.id)
    db.commit()
    db.refresh(payment)
    return payment


@router.get("/payments", response_model=list[PaymentOut], dependencies=[Depends(require_permission("finance", "view"))])
def list_payments(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return db.query(Payment).filter(Payment.org_id == org_id).order_by(Payment.created_at.desc()).all()


# ---------------------------------------------------------------------------
# Payroll deductions. The Finance employee decides, per employee, the PF /
# insurance / TDS percentages, and per payroll run the unpaid-leave (LOP)
# days. Payroll processing (HR module) reads these; it never invents them.
# ---------------------------------------------------------------------------
def _pct(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(Decimal("0.01"))


@router.get("/leave-types", response_model=list[LeaveTypeOut], dependencies=[Depends(require_permission("finance", "view"))])
def finance_leave_types(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    """The leave legend (shown next to the LOP field so Finance knows which leave is unpaid)."""
    types = get_leave_types(db, org_id)
    db.commit()
    return types


@router.get("/payroll-runs", response_model=list[RunSummary], dependencies=[Depends(require_permission("finance", "view"))])
def finance_payroll_runs(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    """Which payroll runs exist, so Finance can pick the one it is preparing deductions for."""
    return db.query(PayrollRun).filter(PayrollRun.org_id == org_id).order_by(PayrollRun.year.desc(), PayrollRun.month.desc()).all()


@router.get("/payroll-deductions", response_model=list[DeductionRow], dependencies=[Depends(require_permission("finance", "view"))])
def list_payroll_deductions(run_id: str | None = None, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    run = None
    if run_id:
        run = db.query(PayrollRun).filter(PayrollRun.id == run_id, PayrollRun.org_id == org_id).first()
        if not run:
            raise HTTPException(404, "Payroll run not found")
    employees = db.query(Employee).filter(Employee.org_id == org_id, Employee.status == "active").order_by(Employee.employee_code, Employee.name).all()
    profiles = {p.employee_id: p for p in db.query(EmployeePayrollProfile).filter(EmployeePayrollProfile.org_id == org_id).all()}
    inputs = {}
    if run:
        inputs = {i.employee_id: i for i in db.query(PayrollInput).filter(PayrollInput.payroll_run_id == run.id).all()}
    rows = []
    for e in employees:
        p = profiles.get(e.id)
        lop = None
        if run:
            lop = inputs[e.id].lop_days if e.id in inputs else lop_days_from_approved_leave(db, e, run.month, run.year)
        rows.append(DeductionRow(
            employee_id=e.id, employee_code=e.employee_code, name=e.name, designation=e.designation, salary=e.salary,
            configured=p is not None, pf_percent=_pct(p.pf_percent if p else 0),
            insurance_percent=_pct(p.insurance_percent if p else 0), tds_percent=_pct(p.tds_percent if p else 0),
            lop_days=lop,
        ))
    return rows


@router.put("/payroll-deductions/{employee_id}", response_model=DeductionRow, dependencies=[Depends(require_permission("finance", "edit"))])
def set_payroll_deductions(employee_id: str, payload: DeductionProfileIn, db: Session = Depends(get_db),
                           org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    employee = db.query(Employee).filter(Employee.id == employee_id, Employee.org_id == org_id).first()
    if not employee:
        raise HTTPException(404, "Employee not found")
    if payload.pf_percent + payload.insurance_percent + payload.tds_percent > 100:
        raise HTTPException(400, "PF + insurance + TDS cannot add up to more than 100% of salary.")
    profile = db.query(EmployeePayrollProfile).filter(EmployeePayrollProfile.employee_id == employee.id).first()
    if not profile:
        profile = EmployeePayrollProfile(org_id=org_id, employee_id=employee.id)
        db.add(profile)
    profile.pf_percent = payload.pf_percent
    profile.insurance_percent = payload.insurance_percent
    profile.tds_percent = payload.tds_percent
    profile.updated_by = current_user.id
    log_audit_event(db, org_id, current_user.id, "set_payroll_deductions", "Employee", employee.id)
    db.commit()
    return DeductionRow(
        employee_id=employee.id, employee_code=employee.employee_code, name=employee.name, designation=employee.designation,
        salary=employee.salary, configured=True, pf_percent=_pct(payload.pf_percent),
        insurance_percent=_pct(payload.insurance_percent), tds_percent=_pct(payload.tds_percent),
    )


@router.put("/payroll-runs/{run_id}/lop/{employee_id}", response_model=LopIn, dependencies=[Depends(require_permission("finance", "edit"))])
def set_lop_days(run_id: str, employee_id: str, payload: LopIn, db: Session = Depends(get_db),
                 org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    run = db.query(PayrollRun).filter(PayrollRun.id == run_id, PayrollRun.org_id == org_id).first()
    employee = db.query(Employee).filter(Employee.id == employee_id, Employee.org_id == org_id).first()
    if not run or not employee:
        raise HTTPException(404, "Payroll run or employee not found")
    if run.status == "processed":
        raise HTTPException(400, "This payroll run has already been processed, so its leave days can no longer change.")
    import calendar
    if payload.lop_days > calendar.monthrange(run.year, run.month)[1]:
        raise HTTPException(400, "Unpaid leave days cannot be more than the days in that month.")
    row = db.query(PayrollInput).filter(PayrollInput.payroll_run_id == run.id, PayrollInput.employee_id == employee.id).first()
    if not row:
        row = PayrollInput(payroll_run_id=run.id, employee_id=employee.id)
        db.add(row)
    row.lop_days = payload.lop_days
    log_audit_event(db, org_id, current_user.id, "set_payroll_lop_days", "PayrollRun", run.id)
    db.commit()
    return payload
