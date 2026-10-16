"""
Warranty registration. A delivered work is mapped here (one record per product line, one unit row per piece sold); an
employee completes the unit details, a user holding warranty.approve activates it, and the printable warranty card
(app/services/warranty_docs.py) is issued. Nothing here imports another module's routes; Workpage calls `on_work_delivered`
through its own safe() hook.
"""
import calendar
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.sales import Product
from app.models.stock import StockBatch
from app.models.user import User
from app.models.warranty import WarrantyRecord, WarrantyUnit
from app.models.workpage import WorkItem, WorkOrder, WorkStockIssue
from app.services.notifications import notify_role, notify_user

PERIODS = [(1, "1 month"), (3, "3 months"), (6, "6 months"), (12, "1 year"), (24, "2 years"), (36, "3 years"), (60, "5 years"), (120, "10 years")]
PERIOD_MONTHS = [m for m, _ in PERIODS]
PERIOD_LABEL = dict(PERIODS)
EDITABLE = ("pending_details",)


class WarrantyError(Exception):
    pass


def period_label(months) -> str:
    return PERIOD_LABEL.get(months, f"{months} months" if months else "-")


def add_months(d: date, months: int) -> date:
    """Same day N months later (clipped to the month end); the warranty ends the day before that anniversary."""
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def end_date_for(start: date, months: int) -> date:
    from datetime import timedelta
    return add_months(start, months) - timedelta(days=1)


def invoice_number(db: Session, work: WorkOrder) -> str | None:
    """The tax invoice of this work (Sales invoice for a direct sale); None until it has been generated."""
    from app.services import workpages as wp
    if wp.is_sales_order(work):
        inv = wp.sales_invoice(db, work)
        return inv.invoice_number if inv else None
    return work.invoice_number


def _next_card_number(db: Session, org_id) -> str:
    db.flush()
    n = db.query(WarrantyRecord).filter(WarrantyRecord.org_id == org_id, WarrantyRecord.card_number.isnot(None)).count()
    return f"WC-{n + 1:04d}"


# ------------------------------------------------------------------ creation (called when a work is delivered)
def on_work_delivered(db: Session, work: WorkOrder):
    """Map what was delivered into warranty records. Idempotent: running it twice never duplicates a line."""
    from app.services import workpages as wp
    db.flush()
    issues = (db.query(WorkStockIssue).filter(WorkStockIssue.work_id == work.id, WorkStockIssue.product_id.isnot(None))
              .order_by(WorkStockIssue.created_at, WorkStockIssue.id).all())
    lines: dict = {}          # product_id -> {"qty", "weight", "batches": [batch_id repeated per unit]}
    for i in issues:
        ln = lines.setdefault(i.product_id, {"qty": 0, "weight": Decimal(0), "batches": []})
        ln["qty"] += int(i.qty)
        ln["weight"] += Decimal(i.mrp or 0) * int(i.qty)
        ln["batches"] += [i.batch_id] * int(i.qty)
    if not lines:                                                   # no stock trail: fall back to the item list
        for it in db.query(WorkItem).filter(WorkItem.work_id == work.id).all():
            ln = lines.setdefault(it.product_id, {"qty": 0, "weight": Decimal(0), "batches": []})
            ln["qty"] += int(it.qty)
            ln["batches"] += [None] * int(it.qty)
    if not lines:
        return []
    total_w = sum((ln["weight"] or Decimal(ln["qty"]) for ln in lines.values()), Decimal(0)) or Decimal(1)
    taxable = Decimal(wp.taxable_net(work) or 0)
    made = []
    for pid, ln in lines.items():
        if db.query(WarrantyRecord.id).filter(WarrantyRecord.work_id == work.id, WarrantyRecord.product_id == pid).first():
            continue
        prod = db.get(Product, pid)
        share = (ln["weight"] or Decimal(ln["qty"])) / total_w
        months = prod.warranty_months if prod and prod.warranty_months in PERIOD_MONTHS else None
        rec = WarrantyRecord(org_id=work.org_id, work_id=work.id, product_id=pid, qty=ln["qty"],
                             amount=(taxable * share).quantize(Decimal("0.01")), status="pending_details",
                             warranty_months=months, warranty_terms=(prod.warranty_terms if prod else None),
                             start_date=work.delivered_on or date.today())
        db.add(rec)
        db.flush()
        for n in range(ln["qty"]):
            batch = db.get(StockBatch, ln["batches"][n]) if n < len(ln["batches"]) and ln["batches"][n] else None
            db.add(WarrantyUnit(org_id=work.org_id, warranty_id=rec.id, position=n + 1,
                                model_number=(prod.sku if prod else None) or None,
                                manufacture_month=batch.manufacture_month if batch else None,
                                expiry_date=batch.expiry_date if batch else None,
                                batch_id=batch.id if batch else None))
        made.append(rec)
    db.flush()
    if made:
        notify_role(db, work.org_id, "Admin", f"{work.work_number} was delivered: warranty details are to be filled for {len(made)} product line(s).")
    return made


def on_work_cancelled(db: Session, work: WorkOrder):
    for rec in db.query(WarrantyRecord).filter(WarrantyRecord.work_id == work.id, WarrantyRecord.status != "cancelled").all():
        rec.status = "cancelled"
        rec.updated_at = datetime.utcnow()


# ------------------------------------------------------------------ filling in, approval
def _parse_month(v):
    if v in (None, ""):
        return None
    if isinstance(v, date):
        return v.replace(day=1)
    s = str(v).strip()
    for fmt in ("%Y-%m", "%Y-%m-%d", "%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date().replace(day=1)
        except ValueError:
            continue
    raise WarrantyError(f"'{s}' is not a valid month (use YYYY-MM).")


def _parse_date(v):
    if v in (None, ""):
        return None
    if isinstance(v, date):
        return v
    try:
        return datetime.strptime(str(v).strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        raise WarrantyError(f"'{v}' is not a valid date (use YYYY-MM-DD).")


def _serial_taken(db: Session, rec: WarrantyRecord, serial: str, unit_id) -> bool:
    q = (db.query(WarrantyUnit.id).join(WarrantyRecord, WarrantyRecord.id == WarrantyUnit.warranty_id)
         .filter(WarrantyUnit.org_id == rec.org_id, WarrantyRecord.product_id == rec.product_id,
                 WarrantyRecord.status != "cancelled",
                 WarrantyUnit.serial_number.ilike(serial), WarrantyUnit.id != unit_id))
    return q.first() is not None


def save_details(db: Session, rec: WarrantyRecord, *, warranty_months=None, warranty_terms=None, units=None, set_fields=()):
    if rec.status not in EDITABLE:
        raise WarrantyError("This warranty can no longer be edited" + (": it is waiting for approval." if rec.status == "pending_approval" else "."))
    if "warranty_months" in set_fields:
        if warranty_months is not None and warranty_months not in PERIOD_MONTHS:
            raise WarrantyError("Pick the warranty period from the list.")
        rec.warranty_months = warranty_months
    if "warranty_terms" in set_fields:
        rec.warranty_terms = (warranty_terms or "").strip() or None
    by_id = {str(u.id): u for u in rec.units}
    seen = {}
    for row in units or []:
        u = by_id.get(str(row.get("id")))
        if not u:
            raise WarrantyError("A unit in the list does not belong to this warranty.")
        if "model_number" in row:
            u.model_number = (row["model_number"] or "").strip() or None
        if "serial_number" in row:
            s = (row["serial_number"] or "").strip()
            u.serial_number = s or None
        if "manufacture_month" in row:
            u.manufacture_month = _parse_month(row["manufacture_month"])
        if "expiry_date" in row:
            u.expiry_date = _parse_date(row["expiry_date"])
    # duplicate serials inside this record
    serials = [(u.serial_number or "").strip().lower() for u in rec.units if u.serial_number]
    if len(serials) != len(set(serials)):
        raise WarrantyError("Two units on this warranty have the same serial number.")
    for u in rec.units:
        if u.serial_number and _serial_taken(db, rec, u.serial_number, u.id):
            raise WarrantyError(f"Serial number {u.serial_number} is already registered for this product on another warranty.")
    rec.updated_at = datetime.utcnow()


def missing_for_submit(rec: WarrantyRecord) -> list[str]:
    miss = []
    if not rec.warranty_months:
        miss.append("warranty period")
    for u in rec.units:
        who = f"Unit {u.position}"
        for label, val in (("model number", u.model_number), ("serial number", u.serial_number), ("month of manufacture", u.manufacture_month)):
            if not val:
                miss.append(f"{who}: {label}")
    return miss


def submit(db: Session, rec: WarrantyRecord, user: User):
    if rec.status != "pending_details":
        raise WarrantyError("Only a warranty whose details are being filled can be submitted.")
    miss = missing_for_submit(rec)
    if miss:
        raise WarrantyError("Fill in everything before submitting: " + "; ".join(miss[:8]) + ("..." if len(miss) > 8 else "") + ".")
    rec.status = "pending_approval"
    rec.submitted_by, rec.submitted_at, rec.rejection_reason = user.id, datetime.utcnow(), None
    rec.updated_at = datetime.utcnow()
    work = db.get(WorkOrder, rec.work_id)
    prod = db.get(Product, rec.product_id)
    notify_role(db, rec.org_id, "Admin", f"Warranty for {prod.name if prod else 'a product'} ({work.work_number if work else ''}) is waiting for your approval.")


def approve(db: Session, rec: WarrantyRecord, user: User):
    if rec.status != "pending_approval":
        raise WarrantyError("Only a submitted warranty can be approved.")
    rec.end_date = end_date_for(rec.start_date, rec.warranty_months)
    rec.card_number = _next_card_number(db, rec.org_id)
    rec.status = "active"
    rec.approved_by, rec.approved_at = user.id, datetime.utcnow()
    rec.updated_at = datetime.utcnow()
    notify_user(db, rec.org_id, rec.submitted_by, f"Warranty card {rec.card_number} was approved by {user.name}. You can print it now.")


def reject(db: Session, rec: WarrantyRecord, user: User, reason: str):
    if rec.status != "pending_approval":
        raise WarrantyError("Only a submitted warranty can be rejected.")
    if not (reason or "").strip():
        raise WarrantyError("Give the reason, so the employee knows what to correct.")
    rec.status = "pending_details"
    rec.rejection_reason = reason.strip()
    rec.updated_at = datetime.utcnow()
    notify_user(db, rec.org_id, rec.submitted_by, f"A warranty you submitted was sent back by {user.name}: {reason.strip()}")


def mark_no_warranty(db: Session, rec: WarrantyRecord, reason: str):
    if rec.status != "pending_details":
        raise WarrantyError("Only a warranty that has not been submitted can be marked 'no warranty'.")
    if not (reason or "").strip():
        raise WarrantyError("Say why this product carries no warranty.")
    rec.status = "no_warranty"
    rec.no_warranty_reason = reason.strip()
    rec.updated_at = datetime.utcnow()


# ------------------------------------------------------------------ read model
def out_of_warranty(rec: WarrantyRecord, today: date | None = None) -> bool:
    return bool(rec.end_date and (today or date.today()) > rec.end_date)


def state_label(rec: WarrantyRecord, today: date | None = None) -> str:
    today = today or date.today()
    if rec.status == "active" and rec.end_date:
        if today > rec.end_date:
            return "Expired"
        if (rec.end_date - today).days <= 30:
            return "Expiring soon"
        return "Active"
    return {"pending_details": "Details to fill", "pending_approval": "Waiting for approval", "no_warranty": "No warranty",
            "cancelled": "Cancelled", "active": "Active"}.get(rec.status, rec.status)


def unit_row(u: WarrantyUnit) -> dict:
    return {"id": u.id, "position": u.position, "model_number": u.model_number, "serial_number": u.serial_number,
            "manufacture_month": u.manufacture_month, "expiry_date": u.expiry_date,
            "prefilled_from_stock": bool(u.batch_id and (u.manufacture_month or u.expiry_date))}


def summary(db: Session, rec: WarrantyRecord) -> dict:
    work = rec.work
    return {"id": rec.id, "work_id": rec.work_id, "work_number": work.work_number if work else None,
            "client_name": work.client_name if work else None, "product_id": rec.product_id,
            "product_name": rec.product.name if rec.product else None, "qty": rec.qty, "status": rec.status,
            "state": state_label(rec), "warranty_months": rec.warranty_months, "period_label": period_label(rec.warranty_months) if rec.warranty_months else None,
            "start_date": rec.start_date, "end_date": rec.end_date, "card_number": rec.card_number,
            "invoice_number": invoice_number(db, work) if work else None}


def detail(db: Session, rec: WarrantyRecord) -> dict:
    d = summary(db, rec)
    d.update({"amount": rec.amount, "warranty_terms": rec.warranty_terms, "rejection_reason": rec.rejection_reason,
              "no_warranty_reason": rec.no_warranty_reason, "units": [unit_row(u) for u in rec.units],
              "submitted_by_name": rec.submitter.name if rec.submitter else None,
              "approved_by_name": rec.approver.name if rec.approver else None, "approved_at": rec.approved_at,
              "periods": [{"months": m, "label": l} for m, l in PERIODS],
              "editable": rec.status in EDITABLE, "out_of_warranty": out_of_warranty(rec)})
    return d
