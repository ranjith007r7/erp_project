"""
Workpage routes: customer works with a colour-coded status that other modules
keep in step (see app/services/workpages.py), a full history page per work,
and payment-gated closing.
"""
import csv
import io
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.api.deps import get_current_user, get_org_id, require_permission
from app.models.hr import Department, Employee
from app.models.procurement import PurchaseOrder
from app.models.sales import Customer, Product, Quotation, SalesOrder
from app.models.workpage import WorkOrder, WorkItem
from app.schemas.workpage import WorkCreate, WorkUpdate, AllocateIn, DeliverIn, WorkPaymentIn, WorkItemsIn, StockShortIn, CancelRequestIn, CancelDecisionIn
from app.services import workpages as svc
from app.services.audit import log_audit_event

from app.schemas.crm import clean_mobile

router = APIRouter(prefix="/api/workpage", tags=["workpage"], dependencies=[Depends(get_current_user)])


def _load(db: Session, org_id, work_id) -> WorkOrder:
    try:
        w = db.query(WorkOrder).filter(WorkOrder.id == work_id, WorkOrder.org_id == org_id).first()
    except Exception:   # malformed uuid
        db.rollback()
        w = None
    if not w:
        raise HTTPException(404, "Work not found")
    return w


def _run(db: Session, fn, *a, **kw):
    try:
        return fn(db, *a, **kw)
    except svc.WorkError as e:
        db.rollback()
        raise HTTPException(400, str(e))


@router.get("/meta", dependencies=[Depends(require_permission("workpage", "view"))])
def meta(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    """Status legend, payment methods, departments and employees for the forms."""
    return {
        "statuses": [{"key": k, "label": v["label"], "color": v["color"]} for k, v in svc.STATUSES.items()],
        "payment_methods": list(svc.PAYMENT_METHODS),
        "cancel_reasons": list(svc.CANCEL_REASONS),
        "other_reason": svc.OTHER_REASON,
        "products": [{"id": p.id, "name": p.name, "sku": p.sku} for p in db.query(Product).filter(Product.org_id == org_id).order_by(Product.name).limit(1000)],
        "departments": [{"id": d.id, "name": d.name} for d in db.query(Department).filter(Department.org_id == org_id).order_by(Department.name)],
        "employees": [{"id": e.id, "name": e.name, "employee_code": e.employee_code, "department_id": e.department_id}
                      for e in db.query(Employee).filter(Employee.org_id == org_id, Employee.status == "active").order_by(Employee.name)],
    }


@router.get("/works", dependencies=[Depends(require_permission("workpage", "view"))])
def list_works(status: str | None = None, q: str | None = None, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    base = db.query(WorkOrder).options(joinedload(WorkOrder.payments)).filter(WorkOrder.org_id == org_id)
    counts: dict[str, int] = {k: 0 for k in svc.STATUSES}
    for w in base.all():
        counts[w.status] += 1
    if status:
        if status not in svc.STATUSES:
            raise HTTPException(400, "Unknown status")
        base = base.filter(WorkOrder.status == status)
    if q and q.strip():
        like = f"%{q.strip()}%"
        base = base.filter(or_(WorkOrder.client_name.ilike(like), WorkOrder.domain.ilike(like), WorkOrder.work_number.ilike(like)))
    works = base.order_by(WorkOrder.created_at.desc()).all()
    return {"counts": counts, "total": sum(counts.values()), "works": [svc.summary_row(db, w) for w in works]}


@router.get("/open-works", dependencies=[Depends(require_permission("procurement", "view"))])
def open_works(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    """For the 'which work is this PO for?' picker on Procurement; needs only procurement.view."""
    rows = db.query(WorkOrder).filter(WorkOrder.org_id == org_id, WorkOrder.status.notin_(["delivered", "closed", "cancel_pending", "cancelled"])).order_by(WorkOrder.created_at.desc()).all()
    return [{"id": w.id, "work_number": w.work_number, "client_name": w.client_name, "status_label": svc.STATUSES[w.status]["label"],
             "needs": svc.po_needs(db, w)} for w in rows]


@router.post("/works", status_code=201, dependencies=[Depends(require_permission("workpage", "create"))])
def create_work(payload: WorkCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    if payload.customer_id and not db.query(Customer.id).filter(Customer.id == payload.customer_id, Customer.org_id == org_id).first():
        raise HTTPException(404, "Customer not found")
    if payload.department_id and not db.query(Department.id).filter(Department.id == payload.department_id, Department.org_id == org_id).first():
        raise HTTPException(404, "Department not found")
    w = svc.create_work(db, org_id, current_user, client_name=payload.client_name, domain=payload.domain,
                        client_details=payload.client_details, description=payload.description,
                        quotation_amount=payload.quotation_amount, vendor_amount=payload.vendor_amount,
                        discount_percent=payload.discount_percent, department_id=payload.department_id,
                        cgst_percent=payload.cgst_percent, sgst_percent=payload.sgst_percent,
                        customer_id=payload.customer_id, client_mobile=payload.client_mobile,
                        opened_title="Work added manually")
    log_audit_event(db, org_id, current_user.id, "create_work", "WorkOrder", w.id)
    db.commit()
    return svc.detail(db, _load(db, org_id, w.id))


@router.post("/import-accepted", dependencies=[Depends(require_permission("workpage", "create"))])
def import_accepted(db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    """One-off catch-up: open a Work for every accepted quotation that has none (accepted before Workpage existed)."""
    have = {r[0] for r in db.query(WorkOrder.quotation_id).filter(WorkOrder.org_id == org_id, WorkOrder.quotation_id.isnot(None))}
    quotes = db.query(Quotation).filter(Quotation.org_id == org_id, Quotation.status == "accepted").order_by(Quotation.created_at).all()
    created = 0
    for qn in quotes:
        if qn.id in have:
            continue
        order = db.query(SalesOrder).filter(SalesOrder.org_id == org_id, SalesOrder.quotation_id == qn.id).first()
        if svc.on_quotation_accepted(db, qn, order, current_user):
            created += 1
    log_audit_event(db, org_id, current_user.id, "import_accepted_quotations", "WorkOrder", None)
    db.commit()
    return {"created": created, "already_had_work": len(quotes) - created}


@router.get("/works/{work_id}", dependencies=[Depends(require_permission("workpage", "view"))])
def get_work(work_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return svc.detail(db, _load(db, org_id, work_id))


@router.patch("/works/{work_id}", dependencies=[Depends(require_permission("workpage", "edit"))])
def update_work(work_id: str, payload: WorkUpdate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    w = _load(db, org_id, work_id)
    if w.status == "closed":
        raise HTTPException(400, "A closed work cannot be edited.")
    try:
        svc._ensure_live(w)
    except svc.WorkError as e:
        raise HTTPException(400, str(e))
    changes = payload.model_dump(exclude_unset=True)
    if svc.is_sales_order(w) and ({"quotation_amount", "discount_percent", "cgst_percent", "sgst_percent"} & set(changes)):
        raise HTTPException(400, "This is a Sales order: its amounts and GST come from the Sales order and invoice and cannot be changed here.")
    if "vendor_amount" in changes and svc._issues(db, w) and svc.q2(changes["vendor_amount"]) != svc.q2(w.vendor_amount):
        raise HTTPException(400, "The vendor amount comes from the stock batches taken from inventory and cannot be typed over.")
    money = {"quotation_amount": "Quoted amount", "vendor_amount": "Vendor amount", "discount_percent": "Client discount %",
             "cgst_percent": "CGST %", "sgst_percent": "SGST %"}
    notes = []
    for field, value in changes.items():
        old = getattr(w, field)
        if field in money:
            value = svc.q2(value)
            if svc.q2(old) != value:
                notes.append(f"{money[field]}: {svc.q2(old)} -> {value}")
        elif field in ("domain", "client_details", "description", "client_mobile"):
            value = (value or "").strip() or None
        elif field == "client_name":
            value = (value or "").strip()
            if not value:
                raise HTTPException(400, "Client name cannot be empty.")
        setattr(w, field, value)
    if w.status == "closed" or svc.received_amount(w) > svc.net_payable(w):
        db.rollback()
        raise HTTPException(400, "The payable amount cannot be lower than what has already been received.")
    viol = svc.pricing_violations(db, w)
    if viol:
        db.rollback()
        raise HTTPException(400, "Finance check: " + " ".join(viol))
    if notes:
        svc.log_event(db, w, "edited", "Amounts changed", "; ".join(notes), current_user)
    log_audit_event(db, org_id, current_user.id, "update_work", "WorkOrder", w.id)
    db.commit()
    return svc.detail(db, _load(db, org_id, work_id))


@router.post("/works/{work_id}/allocate", dependencies=[Depends(require_permission("workpage", "edit"))])
def allocate(work_id: str, payload: AllocateIn, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    w = _load(db, org_id, work_id)
    _run(db, svc.allocate, w, current_user, payload.department_id, payload.employee_id)
    log_audit_event(db, org_id, current_user.id, "allocate_work", "WorkOrder", w.id)
    db.commit()
    return svc.detail(db, _load(db, org_id, work_id))


@router.post("/works/{work_id}/deliver", dependencies=[Depends(require_permission("workpage", "edit"))])
def deliver(work_id: str, payload: DeliverIn, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    w = _load(db, org_id, work_id)
    _run(db, svc.deliver, w, current_user, payload.delivered_on, payload.note, payload.from_stock)
    log_audit_event(db, org_id, current_user.id, "deliver_work", "WorkOrder", w.id)
    db.commit()
    return svc.detail(db, _load(db, org_id, work_id))


@router.post("/works/{work_id}/payments", status_code=201, dependencies=[Depends(require_permission("workpage", "edit"))])
def add_payment(work_id: str, payload: WorkPaymentIn, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    w = _load(db, org_id, work_id)
    _run(db, svc.record_payment, w, current_user, payload.amount, payload.method, payload.transaction_id, payload.note, payload.paid_on)
    log_audit_event(db, org_id, current_user.id, "work_payment", "WorkOrder", w.id)
    db.commit()
    return svc.detail(db, _load(db, org_id, work_id))


@router.put("/works/{work_id}/items", dependencies=[Depends(require_permission("workpage", "edit"))])
def set_items(work_id: str, payload: WorkItemsIn, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    """List what the customer needs (product + quantity). Replaces the previous list."""
    w = _load(db, org_id, work_id)
    _run(db, svc.set_items, w, current_user, [(i.product_id, i.qty) for i in payload.items])
    log_audit_event(db, org_id, current_user.id, "set_work_items", "WorkOrder", w.id)
    db.commit()
    return svc.detail(db, _load(db, org_id, work_id))


@router.get("/works/{work_id}/stock-check", dependencies=[Depends(require_permission("workpage", "view"))])
def stock_check(work_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    """Is what this work needs available in inventory? Costs are shown only to people who may open Stock Intake."""
    from app.api.deps import user_has_permission
    w = _load(db, org_id, work_id)
    return svc.stock_check(db, w, show_cost=user_has_permission(db, current_user, "stockin", "view"))


@router.post("/works/{work_id}/take-from-inventory", dependencies=[Depends(require_permission("workpage", "edit"))])
def take_from_inventory(work_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    """Everything needed is in stock: issue it (rates from the batch), deliver at once, wait for the money."""
    w = _load(db, org_id, work_id)
    _run(db, svc.issue_stock_for_work, w, current_user)
    log_audit_event(db, org_id, current_user.id, "work_stock_issued", "WorkOrder", w.id)
    db.commit()
    return svc.detail(db, _load(db, org_id, work_id))


@router.post("/works/{work_id}/stock-short", dependencies=[Depends(require_permission("workpage", "edit"))])
def stock_short(work_id: str, payload: StockShortIn, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    """Inventory cannot serve it: the work waits for a purchase, with the shortage written down as the reason."""
    w = _load(db, org_id, work_id)
    _run(db, svc.mark_stock_short, w, current_user, payload.note)
    log_audit_event(db, org_id, current_user.id, "work_stock_short", "WorkOrder", w.id)
    db.commit()
    return svc.detail(db, _load(db, org_id, work_id))


@router.post("/works/import", dependencies=[Depends(require_permission("workpage", "create"))])
async def import_works(file: UploadFile = File(...), db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    """Bulk entry for quotations received outside the CRM flow (field visits, a spreadsheet). Columns:
    client_name (required), client_mobile, domain, quotation_amount, description. Each row opens an Assigned work."""
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(400, "Could not read this file as UTF-8 text - export it as a plain CSV.")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "client_name" not in reader.fieldnames:
        raise HTTPException(400, "CSV must have a 'client_name' column. Optional: client_mobile, domain, quotation_amount, description.")
    rows = list(reader)
    if len(rows) > 500:
        raise HTTPException(400, f"This file has {len(rows)} rows - the limit is 500 per import.")
    made, errors = 0, []
    for i, r in enumerate(rows, start=2):
        name = (r.get("client_name") or "").strip()
        if not name:
            errors.append({"row": i, "reason": "'client_name' is required and was empty"})
            continue
        try:
            amt = Decimal((r.get("quotation_amount") or "0").replace(",", "").strip() or "0")
            if amt < 0:
                raise ValueError
        except Exception:  # noqa: BLE001
            errors.append({"row": i, "reason": "quotation_amount must be a positive number"})
            continue
        try:
            mobile = clean_mobile(r.get("client_mobile"))
        except ValueError as e:
            errors.append({"row": i, "reason": str(e)})
            continue
        svc.create_work(db, org_id, current_user, client_name=name, domain=r.get("domain"), client_mobile=mobile,
                        description=r.get("description"), quotation_amount=amt, assign_department=False,
                        opened_title="Work imported in bulk")
        made += 1
    if made:
        log_audit_event(db, org_id, current_user.id, f"bulk_import_works ({made})", "WorkOrder", None)
    db.commit()
    return {"imported": made, "failed": len(errors), "errors": errors}


def _approvers(db: Session, org_id):
    """Users who may decide a cancellation: the Admin role plus any role ticked with workpage.cancel_approve."""
    from app.models.role import Permission, Role
    from app.models.user import User
    ids = {r.id for r in db.query(Role).filter(Role.org_id == org_id, Role.name == "Admin")}
    ids |= {p.role_id for p in db.query(Permission).filter(Permission.module == "workpage", Permission.action == "cancel_approve")}
    return db.query(User).filter(User.org_id == org_id, User.status == "active", User.role_id.in_(ids)).all() if ids else []


@router.post("/works/{work_id}/cancel-request", dependencies=[Depends(require_permission("workpage", "edit"))])
def cancel_request(work_id: str, payload: CancelRequestIn, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    """Any employee who can edit works may RAISE a cancellation; it only takes effect when an approver agrees."""
    from app.services.notifications import notify_user
    w = _load(db, org_id, work_id)
    _run(db, svc.request_cancellation, w, current_user, payload.reason, payload.remark)
    for u in _approvers(db, org_id):
        notify_user(db, org_id, u.id, f"{current_user.name} raised a cancellation for {w.work_number} ({w.client_name}): {payload.reason}. Your decision is needed.")
    log_audit_event(db, org_id, current_user.id, "cancel_work_requested", "WorkOrder", w.id)
    db.commit()
    return svc.detail(db, _load(db, org_id, work_id))


@router.post("/works/{work_id}/cancel-decision", dependencies=[Depends(require_permission("workpage", "cancel_approve"))])
def cancel_decision(work_id: str, payload: CancelDecisionIn, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    """Approve (the work becomes Cancelled and its stock returns to Inventory) or reject (it goes back to where it was)."""
    from app.services.notifications import notify_user
    w = _load(db, org_id, work_id)
    requester = w.cancel_requested_by
    _run(db, svc.decide_cancellation, w, current_user, payload.approve, payload.note)
    verdict = "approved" if payload.approve else "rejected"
    notify_user(db, org_id, requester, f"Your cancellation request for {w.work_number} ({w.client_name}) was {verdict} by {current_user.name}.")
    log_audit_event(db, org_id, current_user.id, f"cancel_work_{verdict}", "WorkOrder", w.id)
    db.commit()
    return svc.detail(db, _load(db, org_id, work_id))


@router.post("/works/{work_id}/close", dependencies=[Depends(require_permission("workpage", "approve"))])
def close_work(work_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    w = _load(db, org_id, work_id)
    _run(db, svc.close, w, current_user)
    log_audit_event(db, org_id, current_user.id, "close_work", "WorkOrder", w.id)
    db.commit()
    return svc.detail(db, _load(db, org_id, work_id))


@router.delete("/works/{work_id}", status_code=204, dependencies=[Depends(require_permission("workpage", "delete"))])
def delete_work(work_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    """Only an untouched, just-assigned work (a wrong entry) can be removed."""
    w = _load(db, org_id, work_id)
    if w.status != "assigned" or w.payments or db.query(PurchaseOrder.id).filter(PurchaseOrder.work_order_id == w.id).first():
        raise HTTPException(400, "Only a work that is still 'Assigned', with no purchase orders or payments, can be deleted.")
    log_audit_event(db, org_id, current_user.id, "delete_work", "WorkOrder", w.id)
    db.query(WorkItem).filter(WorkItem.work_id == w.id).delete()
    db.delete(w)
    db.commit()
