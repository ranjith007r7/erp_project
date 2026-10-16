"""
Warranty claims. A claim is raised against ONE unit of an active warranty, filled by employees (issue + six mandatory
documents) and decided only by a user holding claims.approve. Approval either replaces the unit (a zero-value work is
opened so the normal allocate / stock / deliver flow ships it) or repairs it. An approved claim can be reported to the
vendor who supplied the unit, with the notice built from the lot the unit came from.
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.stock import StockBatch
from app.models.user import User
from app.models.warranty import WarrantyClaim, WarrantyClaimFile, WarrantyRecord, WarrantyUnit
from app.models.workpage import WorkOrder
from app.services import warranty as wsvc
from app.services.notifications import notify_role, notify_user

DOC_KINDS = [
    ("customer_invoice", "Customer's invoice copy"),
    ("warranty_copy", "Warranty copy"),
    ("model_photo", "Model number photo"),
    ("serial_photo", "Serial number photo"),
    ("defect_image", "Defect image"),
    ("supporting", "Additional supporting documents"),
]
KIND_LABEL = dict(DOC_KINDS)
IMAGE_ONLY = {"model_photo", "serial_photo", "defect_image"}
STATUS_LABEL = {"open": "Open", "pending_approval": "Waiting for approval", "replaced": "Replaced", "repaired": "Repaired", "rejected": "Rejected"}


class ClaimError(Exception):
    pass


def _next_number(db: Session, org_id) -> str:
    db.flush()
    n = db.query(WarrantyClaim).filter(WarrantyClaim.org_id == org_id).count()
    return f"CL-{n + 1:04d}"


def create(db: Session, rec: WarrantyRecord, unit_id, issue: str, user: User) -> WarrantyClaim:
    if rec.status != "active":
        raise ClaimError("A claim can only be raised against an approved (active) warranty.")
    unit = next((u for u in rec.units if str(u.id) == str(unit_id)), None)
    if not unit:
        raise ClaimError("Pick the unit the claim is for.")
    if not (issue or "").strip():
        raise ClaimError("Describe the issue.")
    busy = (db.query(WarrantyClaim).filter(WarrantyClaim.unit_id == unit.id, WarrantyClaim.status.in_(("open", "pending_approval"))).first())
    if busy:
        raise ClaimError(f"Claim {busy.claim_number} is already in progress for this unit.")
    c = WarrantyClaim(org_id=rec.org_id, claim_number=_next_number(db, rec.org_id), warranty_id=rec.id, unit_id=unit.id,
                      issue=issue.strip(), status="open", out_of_warranty=wsvc.out_of_warranty(rec), created_by=user.id)
    db.add(c)
    db.flush()
    return c


def present_kinds(c: WarrantyClaim) -> set:
    return {f.kind for f in c.files}


def missing_docs(c: WarrantyClaim) -> list[str]:
    have = present_kinds(c)
    return [label for k, label in DOC_KINDS if k not in have]


def submit(db: Session, c: WarrantyClaim, user: User):
    if c.status != "open":
        raise ClaimError("Only an open claim can be submitted for approval.")
    miss = missing_docs(c)
    if miss:
        raise ClaimError("Upload all required documents first. Missing: " + ", ".join(miss) + ".")
    c.status = "pending_approval"
    c.submitted_at = datetime.utcnow()
    flag = " It is OUT OF WARRANTY." if c.out_of_warranty else ""
    notify_role(db, c.org_id, "Admin", f"Warranty claim {c.claim_number} is waiting for your approval.{flag}")


def approve(db: Session, c: WarrantyClaim, user: User, resolution: str, note: str | None) -> WarrantyClaim | None:
    if c.status != "pending_approval":
        raise ClaimError("Only a submitted claim can be decided.")
    if resolution not in ("replace", "repair"):
        raise ClaimError("Choose whether the unit is replaced or repaired.")
    if c.out_of_warranty and not (note or "").strip():
        raise ClaimError("This claim is out of warranty: give the reason for approving it anyway (goodwill, etc.).")
    c.resolution = resolution
    c.decision_note = (note or "").strip() or None
    c.decided_by, c.decided_at = user.id, datetime.utcnow()
    work = None
    if resolution == "replace":
        work = _replacement_work(db, c, user)
        c.replacement_work_id = work.id
        c.status = "replaced"
    else:
        c.status = "repaired"
    msg = f"Claim {c.claim_number} was approved ({'replacement' if resolution == 'replace' else 'repair'})."
    if work:
        msg += f" Replacement work {work.work_number} was opened."
    notify_user(db, c.org_id, c.created_by, msg)
    return work


def reject(db: Session, c: WarrantyClaim, user: User, note: str):
    if c.status != "pending_approval":
        raise ClaimError("Only a submitted claim can be decided.")
    if not (note or "").strip():
        raise ClaimError("Give the reason for rejecting the claim.")
    c.status = "rejected"
    c.decision_note = note.strip()
    c.decided_by, c.decided_at = user.id, datetime.utcnow()
    notify_user(db, c.org_id, c.created_by, f"Claim {c.claim_number} was rejected by {user.name}: {note.strip()}")


def _replacement_work(db: Session, c: WarrantyClaim, user: User) -> WorkOrder:
    """A zero-value work for the same customer: the usual allocate -> take stock / purchase -> deliver flow ships the unit."""
    from app.services import workpages as wp
    rec = db.get(WarrantyRecord, c.warranty_id)
    src = db.get(WorkOrder, rec.work_id)
    prod_name = rec.product.name if rec.product else "product"
    unit = db.get(WarrantyUnit, c.unit_id)
    w = wp.create_work(db, c.org_id, user, client_name=src.client_name, domain=src.domain, client_details=src.client_details,
                       client_mobile=src.client_mobile, customer_id=src.customer_id,
                       description=f"Warranty replacement under claim {c.claim_number} (original work {src.work_number}): "
                                   f"{prod_name}, serial {unit.serial_number or '-'}.",
                       quotation_amount=0, vendor_amount=0, opened_title="Warranty replacement",
                       cgst_percent=0, sgst_percent=0)
    wp.set_items(db, w, user, [(rec.product_id, 1)])
    return w


# ------------------------------------------------------------------ vendor side
def _vendor_trace(db: Session, c: WarrantyClaim) -> dict:
    unit = db.get(WarrantyUnit, c.unit_id)
    batch = db.get(StockBatch, unit.batch_id) if unit and unit.batch_id else None
    po_number, vendor_email, vendor_name, vendor_id = None, None, None, None
    if batch:
        vendor_name, vendor_id = batch.vendor_name, batch.vendor_id
        if batch.po_id:
            from app.models.procurement import PurchaseOrder
            po = db.get(PurchaseOrder, batch.po_id)
            po_number = po.po_number if po else None
        if batch.vendor_id:
            from app.models.procurement import Vendor
            v = db.get(Vendor, batch.vendor_id)
            vendor_email = v.email if v else None
            vendor_name = v.name if v else vendor_name
    months = batch.vendor_warranty_months if batch else None
    in_w = None
    if batch and months and batch.inward_date:
        in_w = date.today() <= wsvc.end_date_for(batch.inward_date, months)
    return {"batch": batch, "vendor_name": vendor_name, "vendor_id": vendor_id, "vendor_email": vendor_email, "po_number": po_number,
            "vendor_warranty_months": months, "in_vendor_warranty": in_w,
            "vendor_warranty_end": wsvc.end_date_for(batch.inward_date, months) if batch and months and batch.inward_date else None}


def vendor_notice_data(db: Session, c: WarrantyClaim) -> dict:
    t = _vendor_trace(db, c)
    rec = db.get(WarrantyRecord, c.warranty_id)
    unit = db.get(WarrantyUnit, c.unit_id)
    b = t["batch"]
    files = [{"filename": f.filename, "content": f.content, "content_type": f.content_type}
             for f in c.files if f.kind in ("model_photo", "serial_photo", "defect_image", "supporting")]   # never the customer's invoice or card
    return {"claim_number": c.claim_number, "vendor_name": t["vendor_name"], "vendor_email": t["vendor_email"],
            "product_name": rec.product.name if rec.product else "Product", "model_number": unit.model_number, "serial_number": unit.serial_number,
            "manufacture_month": unit.manufacture_month.strftime("%b %Y") if unit.manufacture_month else None,
            "po_number": t["po_number"], "inward_date": b.inward_date.strftime("%d %b %Y") if b and b.inward_date else None,
            "vendor_warranty": (wsvc.period_label(t["vendor_warranty_months"]) + (f" (until {t['vendor_warranty_end']:%d %b %Y})" if t["vendor_warranty_end"] else "")) if t["vendor_warranty_months"] else None,
            "in_vendor_warranty": t["in_vendor_warranty"], "issue": c.issue, "files": files,
            "has_supporting": any(f.kind == "supporting" for f in c.files)}


def summary(db: Session, c: WarrantyClaim) -> dict:
    rec = db.get(WarrantyRecord, c.warranty_id)
    work = db.get(WorkOrder, rec.work_id) if rec else None
    unit = db.get(WarrantyUnit, c.unit_id)
    return {"id": c.id, "claim_number": c.claim_number, "status": c.status, "status_label": STATUS_LABEL.get(c.status, c.status),
            "warranty_id": c.warranty_id, "card_number": rec.card_number if rec else None,
            "work_number": work.work_number if work else None, "client_name": work.client_name if work else None,
            "product_name": rec.product.name if rec and rec.product else None, "serial_number": unit.serial_number if unit else None,
            "out_of_warranty": c.out_of_warranty, "created_at": c.created_at}


def detail(db: Session, c: WarrantyClaim) -> dict:
    d = summary(db, c)
    rec = db.get(WarrantyRecord, c.warranty_id)
    unit = db.get(WarrantyUnit, c.unit_id)
    t = _vendor_trace(db, c)
    rw = c.replacement_work
    d.update({
        "issue": c.issue, "resolution": c.resolution, "decision_note": c.decision_note,
        "decided_by_name": c.decider.name if c.decider else None, "decided_at": c.decided_at,
        "created_by_name": c.creator.name if c.creator else None, "submitted_at": c.submitted_at,
        "warranty_end": rec.end_date if rec else None, "warranty_start": rec.start_date if rec else None,
        "model_number": unit.model_number if unit else None, "manufacture_month": unit.manufacture_month if unit else None,
        "files": [{"id": f.id, "kind": f.kind, "label": KIND_LABEL.get(f.kind, f.kind), "filename": f.filename,
                   "content_type": f.content_type, "size": f.size} for f in c.files],
        "required": [{"kind": k, "label": l, "image_only": k in IMAGE_ONLY, "done": k in present_kinds(c)} for k, l in DOC_KINDS],
        "missing": missing_docs(c),
        "replacement_work": {"id": rw.id, "work_number": rw.work_number, "status": rw.status} if rw else None,
        "vendor": {"name": t["vendor_name"], "email": t["vendor_email"], "po_number": t["po_number"],
                   "warranty_months": t["vendor_warranty_months"], "warranty_end": t["vendor_warranty_end"],
                   "in_vendor_warranty": t["in_vendor_warranty"], "traced": t["batch"] is not None,
                   "notice_at": c.vendor_notice_at, "notice_to": c.vendor_notice_to, "notice_channel": c.vendor_notice_channel},
    })
    return d
