"""Warranty registration: records appear when a work is delivered; employees fill the unit details, an approver activates
them, and the printable warranty card is generated. Permissions: module 'warranty' (view / edit to fill / approve)."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user, get_org_id, require_permission
from app.core.database import get_db
from app.models.organization import Organization, OrganizationProfile
from app.models.warranty import WarrantyRecord
from app.models.workpage import WorkOrder
from app.services import invoice_pdf, warranty as svc, warranty_docs
from app.services.audit import log_audit_event

router = APIRouter(prefix="/api/warranty", tags=["warranty"], dependencies=[Depends(get_current_user)])


class UnitIn(BaseModel):
    id: str
    model_number: Optional[str] = Field(None, max_length=120)
    serial_number: Optional[str] = Field(None, max_length=120)
    manufacture_month: Optional[str] = None
    expiry_date: Optional[str] = None


class DetailsIn(BaseModel):
    warranty_months: Optional[int] = None
    warranty_terms: Optional[str] = Field(None, max_length=1500)
    units: Optional[list[UnitIn]] = None


class ReasonIn(BaseModel):
    reason: str = Field(..., min_length=2, max_length=500)


def _load(db: Session, org_id, wid) -> WarrantyRecord:
    try:
        rec = (db.query(WarrantyRecord).options(joinedload(WarrantyRecord.work), joinedload(WarrantyRecord.product))
               .filter(WarrantyRecord.id == wid, WarrantyRecord.org_id == org_id).first())
    except Exception:
        db.rollback()
        rec = None
    if not rec:
        raise HTTPException(404, "Warranty record not found")
    return rec


def _run(db: Session, fn, *a, **kw):
    try:
        return fn(db, *a, **kw)
    except svc.WarrantyError as e:
        db.rollback()
        raise HTTPException(400, str(e))


@router.get("/meta", dependencies=[Depends(require_permission("warranty", "view"))])
def meta():
    return {"periods": [{"months": m, "label": l} for m, l in svc.PERIODS]}


@router.get("", dependencies=[Depends(require_permission("warranty", "view"))])
def list_records(status: Optional[str] = None, q: Optional[str] = None, work_id: Optional[str] = None,
                 db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    qry = (db.query(WarrantyRecord).options(joinedload(WarrantyRecord.work), joinedload(WarrantyRecord.product))
           .join(WorkOrder, WorkOrder.id == WarrantyRecord.work_id).filter(WarrantyRecord.org_id == org_id))
    if status:
        qry = qry.filter(WarrantyRecord.status == status)
    if work_id:
        qry = qry.filter(WarrantyRecord.work_id == work_id)
    if q and q.strip():
        like = f"%{q.strip()}%"
        qry = qry.filter(or_(WorkOrder.work_number.ilike(like), WorkOrder.client_name.ilike(like), WarrantyRecord.card_number.ilike(like)))
    rows = qry.order_by(WarrantyRecord.created_at.desc()).limit(300).all()
    return [svc.summary(db, r) for r in rows]


@router.get("/{wid}", dependencies=[Depends(require_permission("warranty", "view"))])
def get_record(wid: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return svc.detail(db, _load(db, org_id, wid))


@router.patch("/{wid}", dependencies=[Depends(require_permission("warranty", "edit"))])
def save(wid: str, payload: DetailsIn, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    rec = _load(db, org_id, wid)
    fields = payload.model_fields_set
    _run(db, svc.save_details, rec, warranty_months=payload.warranty_months, warranty_terms=payload.warranty_terms,
         units=[u.model_dump(exclude_unset=True) for u in (payload.units or [])], set_fields=fields)
    log_audit_event(db, org_id, current_user.id, "warranty_details_saved", "WarrantyRecord", rec.id)
    db.commit()
    return svc.detail(db, _load(db, org_id, wid))


@router.post("/{wid}/submit", dependencies=[Depends(require_permission("warranty", "edit"))])
def submit(wid: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    rec = _load(db, org_id, wid)
    _run(db, svc.submit, rec, current_user)
    log_audit_event(db, org_id, current_user.id, "warranty_submitted", "WarrantyRecord", rec.id)
    db.commit()
    return svc.detail(db, _load(db, org_id, wid))


@router.post("/{wid}/approve", dependencies=[Depends(require_permission("warranty", "approve"))])
def approve(wid: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    rec = _load(db, org_id, wid)
    _run(db, svc.approve, rec, current_user)
    log_audit_event(db, org_id, current_user.id, "warranty_approved", "WarrantyRecord", rec.id)
    db.commit()
    return svc.detail(db, _load(db, org_id, wid))


@router.post("/{wid}/reject", dependencies=[Depends(require_permission("warranty", "approve"))])
def reject(wid: str, payload: ReasonIn, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    rec = _load(db, org_id, wid)
    _run(db, svc.reject, rec, current_user, payload.reason)
    log_audit_event(db, org_id, current_user.id, "warranty_sent_back", "WarrantyRecord", rec.id)
    db.commit()
    return svc.detail(db, _load(db, org_id, wid))


@router.post("/{wid}/no-warranty", dependencies=[Depends(require_permission("warranty", "edit"))])
def no_warranty(wid: str, payload: ReasonIn, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    rec = _load(db, org_id, wid)
    _run(db, svc.mark_no_warranty, rec, payload.reason)
    log_audit_event(db, org_id, current_user.id, "warranty_not_applicable", "WarrantyRecord", rec.id)
    db.commit()
    return svc.detail(db, _load(db, org_id, wid))


@router.get("/{wid}/card-pdf", dependencies=[Depends(require_permission("warranty", "view"))])
def card_pdf(wid: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    """The printable warranty card, issued only once the warranty has been approved."""
    rec = _load(db, org_id, wid)
    if rec.status != "active" or not rec.card_number:
        raise HTTPException(409, "The warranty card is available once the warranty has been approved.")
    org = db.query(Organization).filter(Organization.id == org_id).first()
    profile = db.query(OrganizationProfile).filter(OrganizationProfile.org_id == org_id).first()
    d = svc.detail(db, rec)
    d["client"] = {"name": rec.work.client_name if rec.work else ""}
    data = warranty_docs.warranty_card_pdf(invoice_pdf.company_block(org, profile), d)
    log_audit_event(db, org_id, current_user.id, "warranty_card_printed", "WarrantyRecord", rec.id)
    db.commit()
    return Response(content=data, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{rec.card_number}.pdf"'})
