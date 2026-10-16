"""Warranty claims: employees log the issue and the six mandatory documents; only a user holding claims.approve decides.
Approving a replacement opens a zero-value work; an approved claim can be reported to the vendor (email / printable notice)."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user, get_org_id, require_permission
from app.core.config import settings
from app.core.database import get_db
from app.models.organization import Organization
from app.models.warranty import WarrantyClaim, WarrantyClaimFile, WarrantyRecord
from app.models.workpage import WorkOrder
from app.services import claims as svc, warranty_docs
from app.services.audit import log_audit_event
from app.services.email import send_email
from app.services.procurement_docs import is_valid_image

router = APIRouter(prefix="/api/claims", tags=["claims"], dependencies=[Depends(get_current_user)])

ANY_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/webp"}
IMG_TYPES = {"image/png", "image/jpeg", "image/webp"}


class ClaimIn(BaseModel):
    warranty_id: str
    unit_id: str
    issue: str = Field(..., min_length=3, max_length=2000)


class IssueIn(BaseModel):
    issue: str = Field(..., min_length=3, max_length=2000)


class ApproveIn(BaseModel):
    resolution: str = Field(..., pattern="^(replace|repair)$")
    note: Optional[str] = Field(None, max_length=1000)


class RejectIn(BaseModel):
    note: str = Field(..., min_length=2, max_length=1000)


class NoticeSendIn(BaseModel):
    to_email: str = Field(..., min_length=3)
    note: Optional[str] = Field(None, max_length=1000)


def _load(db: Session, org_id, cid) -> WarrantyClaim:
    try:
        c = (db.query(WarrantyClaim).options(joinedload(WarrantyClaim.files))
             .filter(WarrantyClaim.id == cid, WarrantyClaim.org_id == org_id).first())
    except Exception:
        db.rollback()
        c = None
    if not c:
        raise HTTPException(404, "Claim not found")
    return c


def _run(db: Session, fn, *a, **kw):
    try:
        return fn(db, *a, **kw)
    except svc.ClaimError as e:
        db.rollback()
        raise HTTPException(400, str(e))


@router.get("", dependencies=[Depends(require_permission("claims", "view"))])
def list_claims(status: Optional[str] = None, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    q = db.query(WarrantyClaim).filter(WarrantyClaim.org_id == org_id)
    if status:
        q = q.filter(WarrantyClaim.status == status)
    return [svc.summary(db, c) for c in q.order_by(WarrantyClaim.created_at.desc()).limit(300).all()]


@router.post("", status_code=201, dependencies=[Depends(require_permission("claims", "create"))])
def create_claim(payload: ClaimIn, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    rec = (db.query(WarrantyRecord).options(joinedload(WarrantyRecord.units), joinedload(WarrantyRecord.product))
           .filter(WarrantyRecord.id == payload.warranty_id, WarrantyRecord.org_id == org_id).first())
    if not rec:
        raise HTTPException(404, "Warranty record not found")
    c = _run(db, svc.create, rec, payload.unit_id, payload.issue, current_user)
    log_audit_event(db, org_id, current_user.id, "warranty_claim_raised", "WarrantyClaim", c.id)
    db.commit()
    return svc.detail(db, _load(db, org_id, c.id))


@router.get("/{cid}", dependencies=[Depends(require_permission("claims", "view"))])
def get_claim(cid: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return svc.detail(db, _load(db, org_id, cid))


@router.patch("/{cid}", dependencies=[Depends(require_permission("claims", "edit"))])
def edit_issue(cid: str, payload: IssueIn, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    c = _load(db, org_id, cid)
    if c.status != "open":
        raise HTTPException(400, "A submitted claim can no longer be edited.")
    c.issue = payload.issue.strip()
    db.commit()
    return svc.detail(db, _load(db, org_id, cid))


@router.post("/{cid}/files", dependencies=[Depends(require_permission("claims", "edit"))])
async def upload(cid: str, kind: str = Form(...), files: list[UploadFile] = File(...),
                 db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    c = _load(db, org_id, cid)
    if c.status != "open":
        raise HTTPException(400, "Documents can only be added while the claim is open.")
    if kind not in svc.KIND_LABEL:
        raise HTTPException(400, "Unknown document type.")
    label = svc.KIND_LABEL[kind]
    allowed = IMG_TYPES if kind in svc.IMAGE_ONLY else ANY_TYPES
    real = [f for f in files if f and f.filename]
    if not real:
        raise HTTPException(400, f"{label}: choose a file.")
    if len(real) > 6:
        raise HTTPException(400, "Upload at most 6 files at a time.")
    for up in real:
        data = await up.read()
        if not data:
            raise HTTPException(400, f"{label}: '{up.filename}' is empty.")
        if len(data) > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
            raise HTTPException(400, f"{label}: '{up.filename}' exceeds the {settings.MAX_UPLOAD_SIZE_MB}MB limit.")
        ctype = (up.content_type or "").lower()
        if ctype not in allowed:
            raise HTTPException(400, f"{label} must be a " + ("PNG, JPG or WEBP image." if kind in svc.IMAGE_ONLY else "PDF, PNG, JPG or WEBP file."))
        if ctype.startswith("image/") and not is_valid_image(data):
            raise HTTPException(400, f"'{up.filename}' is not a readable image.")
        if kind != "supporting":     # one file per mandatory slot: a new upload replaces the old one
            for old in [f for f in c.files if f.kind == kind]:
                c.files.remove(old)
        c.files.append(WarrantyClaimFile(org_id=org_id, kind=kind, filename=up.filename.replace("/", "_").replace("\\", "_"),
                                         content_type=ctype, size=len(data), content=data))
    db.commit()
    return svc.detail(db, _load(db, org_id, cid))


@router.delete("/{cid}/files/{fid}", dependencies=[Depends(require_permission("claims", "edit"))])
def delete_file(cid: str, fid: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    c = _load(db, org_id, cid)
    if c.status != "open":
        raise HTTPException(400, "Documents can only be removed while the claim is open.")
    f = next((x for x in c.files if str(x.id) == fid), None)
    if not f:
        raise HTTPException(404, "File not found")
    c.files.remove(f)
    db.commit()
    return svc.detail(db, _load(db, org_id, cid))


@router.get("/files/{fid}", dependencies=[Depends(require_permission("claims", "view"))])
def download(fid: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    f = db.query(WarrantyClaimFile).filter(WarrantyClaimFile.id == fid, WarrantyClaimFile.org_id == org_id).first()
    if not f:
        raise HTTPException(404, "File not found")
    return Response(content=f.content, media_type=f.content_type, headers={"Content-Disposition": f'inline; filename="{f.filename}"'})


@router.post("/{cid}/submit", dependencies=[Depends(require_permission("claims", "edit"))])
def submit(cid: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    c = _load(db, org_id, cid)
    _run(db, svc.submit, c, current_user)
    log_audit_event(db, org_id, current_user.id, "warranty_claim_submitted", "WarrantyClaim", c.id)
    db.commit()
    return svc.detail(db, _load(db, org_id, cid))


@router.post("/{cid}/approve", dependencies=[Depends(require_permission("claims", "approve"))])
def approve(cid: str, payload: ApproveIn, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    c = _load(db, org_id, cid)
    _run(db, svc.approve, c, current_user, payload.resolution, payload.note)
    log_audit_event(db, org_id, current_user.id, "warranty_claim_approved", "WarrantyClaim", c.id)
    db.commit()
    return svc.detail(db, _load(db, org_id, cid))


@router.post("/{cid}/reject", dependencies=[Depends(require_permission("claims", "approve"))])
def reject(cid: str, payload: RejectIn, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    c = _load(db, org_id, cid)
    _run(db, svc.reject, c, current_user, payload.note)
    log_audit_event(db, org_id, current_user.id, "warranty_claim_rejected", "WarrantyClaim", c.id)
    db.commit()
    return svc.detail(db, _load(db, org_id, cid))


# ------------------------------------------------------------------ vendor notice
def _notice_claim(db, org_id, cid):
    c = _load(db, org_id, cid)
    if c.status not in ("replaced", "repaired"):
        raise HTTPException(409, "A vendor notice can be raised once the customer's claim has been approved.")
    return c


def _org_name(db, org_id):
    org = db.query(Organization).filter(Organization.id == org_id).first()
    return org.name if org else "Our company"


@router.get("/{cid}/vendor-notice/preview", dependencies=[Depends(require_permission("claims", "view"))])
def notice_preview(cid: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    c = _notice_claim(db, org_id, cid)
    data = svc.vendor_notice_data(db, c)
    mail = warranty_docs.build_vendor_notice(_org_name(db, org_id), data)
    return {**mail, "to_email": data["vendor_email"]}


@router.post("/{cid}/vendor-notice/send", dependencies=[Depends(require_permission("claims", "edit"))])
def notice_send(cid: str, payload: NoticeSendIn, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    c = _notice_claim(db, org_id, cid)
    to = payload.to_email.strip()
    if "@" not in to:
        raise HTTPException(400, "Enter the vendor's email address, or print the notice.")
    data = svc.vendor_notice_data(db, c)
    org = _org_name(db, org_id)
    mail = warranty_docs.build_vendor_notice(org, data)
    body = (payload.note.strip() + "\n\n" + mail["body"]) if payload.note and payload.note.strip() else mail["body"]
    status = send_email(to, mail["subject"], body, from_name=org, reply_to=current_user.email,
                        attachments=[(f["filename"], f["content"], f["content_type"]) for f in data["files"]])
    c.vendor_notice_at, c.vendor_notice_to, c.vendor_notice_channel = datetime.utcnow(), to, "email"
    log_audit_event(db, org_id, current_user.id, "warranty_vendor_notice_emailed", "WarrantyClaim", c.id)
    db.commit()
    return {"status": status, "to_email": to, "subject": mail["subject"],
            "message": "Sent." if status == "sent" else "Email is not configured: the notice was logged on the server."}


@router.post("/{cid}/vendor-notice/print", dependencies=[Depends(require_permission("claims", "edit"))])
def notice_print(cid: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    c = _notice_claim(db, org_id, cid)
    data = svc.vendor_notice_data(db, c)
    pdf = warranty_docs.vendor_notice_pdf(_org_name(db, org_id), data)
    c.vendor_notice_at, c.vendor_notice_to, c.vendor_notice_channel = datetime.utcnow(), None, "print"
    log_audit_event(db, org_id, current_user.id, "warranty_vendor_notice_printed", "WarrantyClaim", c.id)
    db.commit()
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{c.claim_number}-vendor-notice.pdf"'})
