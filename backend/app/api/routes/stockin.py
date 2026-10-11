"""
Stock Intake: bring the stock a company already holds (or has just bought outside a
purchase order) into the ERP WITH its rates, so that nobody has to type an amount when
stock is later taken for a customer's work.

Only people given the 'stockin' permission can use it; by default that is the Admin and
the manager roles. Every batch also moves the Inventory total (unless it just prices
units that are already counted there), so Inventory, Procurement, Workpage and Finance
all read one set of numbers (app/services/stock.py).
"""
import csv
import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import get_current_user, get_org_id, require_permission
from app.models.procurement import Vendor
from app.models.sales import Product
from app.models.stock import StockBatch
from app.schemas.stockin import StockBatchIn, StockBatchUpdate
from app.services import stock as svc
from app.services.audit import log_audit_event

router = APIRouter(prefix="/api/stockin", tags=["stock-intake"], dependencies=[Depends(get_current_user)])

TEMPLATE_HEAD = ["sku", "product_name", "quantity", "vendor_name", "vendor_amount", "mrp", "max_discount_percent",
                 "date_of_inward", "month_of_manufacture", "expiry_date", "already_in_inventory"]
MAX_ROWS = 1000


def _run(db: Session, fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except svc.StockError as e:
        db.rollback()
        raise HTTPException(400, str(e))


def _batch(db: Session, org_id, batch_id) -> StockBatch:
    try:
        b = db.query(StockBatch).filter(StockBatch.id == batch_id, StockBatch.org_id == org_id).first()
    except Exception:  # noqa: BLE001 - malformed uuid
        db.rollback()
        b = None
    if not b:
        raise HTTPException(404, "Batch not found")
    return b


@router.get("/products", dependencies=[Depends(require_permission("stockin", "view"))])
def products(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    rows = db.query(Product).filter(Product.org_id == org_id).order_by(Product.name).all()
    return [{"id": p.id, "name": p.name, "sku": p.sku, "unit_price": p.unit_price} for p in rows]


@router.get("/summary", dependencies=[Depends(require_permission("stockin", "view"))])
def summary(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    """Per product: units in Inventory, units that have rates (batches), units still without rates, and stock value at cost."""
    out, today = [], date.today()
    for p in db.query(Product).filter(Product.org_id == org_id).order_by(Product.name).all():
        batches = db.query(StockBatch).filter(StockBatch.org_id == org_id, StockBatch.product_id == p.id, StockBatch.quantity_remaining > 0).all()
        on_hand = svc.stock_total(db, org_id, p.id)
        priced = sum(b.quantity_remaining for b in batches)
        usable = sum(b.quantity_remaining for b in batches if not b.expiry_date or b.expiry_date >= today)
        out.append({"product_id": p.id, "product_name": p.name, "sku": p.sku, "on_hand": on_hand, "priced": priced,
                    "unpriced": max(on_hand - priced, 0), "usable": usable, "expired": priced - usable,
                    "value_at_cost": svc.q2(sum(Decimal(b.vendor_amount) * b.quantity_remaining for b in batches))})
    vendors = sorted({v for (v,) in db.query(Vendor.name).filter(Vendor.org_id == org_id)} |
                     {v for (v,) in db.query(StockBatch.vendor_name).filter(StockBatch.org_id == org_id).distinct()})
    return {"products": out, "vendor_names": vendors,
            "totals": {"units_priced": sum(r["priced"] for r in out), "units_unpriced": sum(r["unpriced"] for r in out),
                       "value_at_cost": svc.q2(sum(r["value_at_cost"] for r in out))}}


@router.get("/batches", dependencies=[Depends(require_permission("stockin", "view"))])
def list_batches(product_id: str | None = None, q: str | None = None, only_available: bool = False,
                 db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    base = db.query(StockBatch).filter(StockBatch.org_id == org_id)
    if product_id:
        base = base.filter(StockBatch.product_id == product_id)
    if only_available:
        base = base.filter(StockBatch.quantity_remaining > 0)
    if q and q.strip():
        like = f"%{q.strip()}%"
        base = base.join(Product, Product.id == StockBatch.product_id).filter((Product.name.ilike(like)) | (Product.sku.ilike(like)) | (StockBatch.vendor_name.ilike(like)))
    rows = base.order_by(StockBatch.inward_date.desc(), StockBatch.created_at.desc()).all()
    prods = {p.id: p for p in db.query(Product).filter(Product.org_id == org_id)}
    return [svc.batch_row(db, b, prods.get(b.product_id)) for b in rows]


@router.post("/batches", status_code=201, dependencies=[Depends(require_permission("stockin", "create"))])
def create_batch(payload: StockBatchIn, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    month = _run(db, svc.parse_month, payload.manufacture_month)
    b = _run(db, svc.create_batch, db, org_id, current_user, product_id=payload.product_id, quantity=payload.quantity,
             vendor_name=payload.vendor_name, vendor_amount=payload.vendor_amount, mrp=payload.mrp,
             max_discount_percent=payload.max_discount_percent, inward_date=payload.inward_date or date.today(),
             manufacture_month=month, expiry_date=payload.expiry_date, source="manual", note=payload.note,
             already_in_inventory=payload.already_in_inventory)
    log_audit_event(db, org_id, current_user.id, "stock_intake", "StockBatch", b.id)
    db.commit()
    return svc.batch_row(db, b)


@router.patch("/batches/{batch_id}", dependencies=[Depends(require_permission("stockin", "edit"))])
def update_batch(batch_id: str, payload: StockBatchUpdate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    """Correct rates, dates, vendor or note. Quantity is never edited here (it has stock movements behind it).
    Works that already took units keep the rates they were billed with."""
    b = _batch(db, org_id, batch_id)
    ch = payload.model_dump(exclude_unset=True)
    if "manufacture_month" in ch:
        ch["manufacture_month"] = _run(db, svc.parse_month, ch["manufacture_month"])
    new = {"vendor_name": b.vendor_name, "vendor_amount": b.vendor_amount, "mrp": b.mrp, "max_discount_percent": b.max_discount_percent,
           "inward_date": b.inward_date, "manufacture_month": b.manufacture_month, "expiry_date": b.expiry_date}
    new.update({k: v for k, v in ch.items() if k in new})
    _run(db, svc.validate_fields, **new)
    for k, v in new.items():
        setattr(b, k, svc.q2(v) if k in ("vendor_amount", "mrp", "max_discount_percent") else (v.strip() if k == "vendor_name" else v))
    if "note" in ch:
        b.note = (ch["note"] or "").strip() or None
    b.updated_at = datetime.utcnow()
    log_audit_event(db, org_id, current_user.id, "update_stock_batch", "StockBatch", b.id)
    db.commit()
    return svc.batch_row(db, b)


@router.delete("/batches/{batch_id}", status_code=204, dependencies=[Depends(require_permission("stockin", "delete"))])
def delete_batch(batch_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    """Undo a wrong entry: only an untouched, hand-entered batch. Takes its units back out of Inventory."""
    b = _batch(db, org_id, batch_id)
    _run(db, svc.delete_batch, db, org_id, b)
    log_audit_event(db, org_id, current_user.id, "delete_stock_batch", "StockBatch", batch_id)
    db.commit()


# ------------------------------------------------------------------ CSV
@router.get("/import-template", dependencies=[Depends(require_permission("stockin", "view"))])
def import_template():
    sample = ["DSK-002", "Standing Desk", "8", "Bharat Timber & Steel Supplies", "22000", "34999", "10", "2026-09-30", "2026-08", "", "no"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(TEMPLATE_HEAD)
    w.writerow(sample)
    return Response(("﻿" + buf.getvalue()).encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="stock_intake_template.csv"'})


def _d(text: str | None, what: str) -> date | None:
    t = (text or "").strip()
    if not t:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    raise svc.StockError(f"{what} '{t}' is not a date (use 2026-09-30 or 30/09/2026).")


def _m(text: str | None) -> date | None:
    t = (text or "").strip()
    if not t:
        return None
    if "/" in t and len(t.split("/")) == 2:      # 03/2026
        mm, yy = t.split("/")
        t = f"{yy}-{int(mm):02d}"
    return svc.parse_month(t)


@router.post("/import", dependencies=[Depends(require_permission("stockin", "create"))])
async def import_csv(file: UploadFile = File(...), db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    """Add many batches at once. Partial success: good rows are saved, bad rows are listed with the reason.
    Products are matched by SKU, then by exact name; the product must already exist."""
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(400, "Could not read this file as UTF-8 text - export it as a plain CSV.")
    reader = csv.DictReader(io.StringIO(text))
    need = {"quantity", "vendor_name", "vendor_amount", "mrp", "max_discount_percent"}
    if not reader.fieldnames or not need.issubset(set(reader.fieldnames)) or not ({"sku", "product_name"} & set(reader.fieldnames)):
        raise HTTPException(400, "CSV needs the columns: sku or product_name, quantity, vendor_name, vendor_amount, mrp, max_discount_percent "
                                 "(and optionally date_of_inward, month_of_manufacture, expiry_date, already_in_inventory). Download the template.")
    rows = list(reader)
    if len(rows) > MAX_ROWS:
        raise HTTPException(400, f"This file has {len(rows)} rows - the limit is {MAX_ROWS} per import.")
    done, errors = 0, []
    for i, r in enumerate(rows, start=2):
        try:
            sku, pname = (r.get("sku") or "").strip(), (r.get("product_name") or "").strip()
            prod = None
            if sku:
                prod = db.query(Product).filter(Product.org_id == org_id, func.lower(Product.sku) == sku.lower()).first()
            if not prod and pname:
                prod = db.query(Product).filter(Product.org_id == org_id, func.lower(Product.name) == pname.lower()).first()
            if not prod:
                raise svc.StockError(f"Product '{sku or pname}' was not found; add it in Inventory first.")
            try:
                qty = int(Decimal((r.get("quantity") or "").strip()))
                vamt, mrp = Decimal((r.get("vendor_amount") or "").replace(",", "").strip()), Decimal((r.get("mrp") or "").replace(",", "").strip())
                md = Decimal((r.get("max_discount_percent") or "").strip())
            except (InvalidOperation, ValueError):
                raise svc.StockError("quantity, vendor_amount, mrp and max_discount_percent must all be numbers (they are all required).")
            flag = (r.get("already_in_inventory") or "").strip().lower() in ("yes", "y", "true", "1")
            with db.begin_nested():
                svc.create_batch(db, org_id, current_user, product_id=prod.id, quantity=qty, vendor_name=r.get("vendor_name") or "",
                                 vendor_amount=vamt, mrp=mrp, max_discount_percent=md,
                                 inward_date=_d(r.get("date_of_inward"), "date_of_inward") or date.today(),
                                 manufacture_month=_m(r.get("month_of_manufacture")), expiry_date=_d(r.get("expiry_date"), "expiry_date"),
                                 source="csv", already_in_inventory=flag)
            done += 1
        except svc.StockError as e:
            errors.append({"row": i, "reason": str(e)})
    if done:
        log_audit_event(db, org_id, current_user.id, f"bulk_stock_intake ({done} batches)", "StockBatch", None)
    db.commit()
    return {"imported": done, "failed": len(errors), "errors": errors}
