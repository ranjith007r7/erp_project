"""
Procurement module routes. The mirror image of Sales: instead of a
Quotation->SalesOrder->Invoice chain going OUT to a customer, this is a
PurchaseOrder->GoodsReceipt chain bringing stock IN from a vendor.

Real-world flow implemented here:
  1. A buyer raises a PO                      (approval_status = pending)
  2. A procurement approver approves/rejects  (procurement.approve)
  3. The approved PO goes to the vendor: emailed (preview, then send) or
     exported as a PDF to hand over for vendors without email
  4. Goods arrive; the receiver physically inspects them and records either
       - good: uploads vendor invoice + courier POD -> stock increases
       - bad : uploads invoice + POD + defect photos -> stock does NOT
               increase, PO becomes "defective", and a defect notice goes to
               the vendor by email (preview, then send) or is printed
Stock only ever increases through a GOOD receipt.
"""
from datetime import date, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload, selectinload, load_only

from app.core.config import settings
from app.core.database import get_db
from app.api.deps import get_current_user, get_org_id, require_permission
from app.services import workpages
from app.models.organization import Organization
from app.models.procurement import (
    Vendor, PurchaseOrder, PurchaseOrderItem, GoodsReceipt, GoodsReceiptFile, ProcurementEmailLog,
)
from app.models.sales import Product
from app.schemas.procurement import (
    VendorCreate, VendorUpdate, VendorOut,
    PurchaseOrderCreate, PurchaseOrderOut, EmailPreviewOut, SendEmailIn, SendEmailOut,
)
from app.services.inventory import receive_stock
from app.services.notifications import notify_role, notify_user
from app.services.audit import log_audit_event
from app.services.email import send_email
from app.services import procurement_docs as docs

router = APIRouter(prefix="/api/procurement", tags=["procurement"], dependencies=[Depends(get_current_user)])

ALLOWED_PROOF_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/webp"}
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}


# ---------------------------------------------------------------- helpers
def _clean_email(value: str | None) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    if not docs.valid_email(value):
        raise HTTPException(400, f"'{value}' is not a valid email address.")
    return value


def _org_name(db: Session, org_id) -> str:
    org = db.query(Organization).filter(Organization.id == org_id).first()
    return org.name if org else "Our company"


def _load_po(db: Session, org_id, po_id) -> PurchaseOrder:
    po = (
        db.query(PurchaseOrder)
        .options(
            selectinload(PurchaseOrder.items).joinedload(PurchaseOrderItem.product),
            joinedload(PurchaseOrder.vendor), joinedload(PurchaseOrder.creator),
            joinedload(PurchaseOrder.approver),
            selectinload(PurchaseOrder.receipts).selectinload(GoodsReceipt.files).load_only(
                GoodsReceiptFile.id, GoodsReceiptFile.kind, GoodsReceiptFile.filename,
                GoodsReceiptFile.content_type, GoodsReceiptFile.size, GoodsReceiptFile.receipt_id,
                GoodsReceiptFile.created_at),
        )
        .filter(PurchaseOrder.id == po_id, PurchaseOrder.org_id == org_id)
        .first()
    )
    if not po:
        raise HTTPException(404, "Purchase order not found")
    return po


def _receipt_with_content(db: Session, org_id, receipt_id) -> GoodsReceipt:
    r = db.query(GoodsReceipt).filter(GoodsReceipt.id == receipt_id, GoodsReceipt.org_id == org_id).first()
    if not r:
        raise HTTPException(404, "Goods receipt not found")
    return r


def _out(po: PurchaseOrder) -> dict:
    return {
        "id": po.id, "po_number": po.po_number, "vendor_id": po.vendor_id,
        "vendor_name": po.vendor.name if po.vendor else None,
        "order_date": po.order_date, "status": po.status, "approval_status": po.approval_status,
        "total": po.total,
        "created_by_name": po.creator.name if po.creator else None,
        "created_by_email": po.creator.email if po.creator else None,
        "approved_by_name": po.approver.name if po.approver else None,
        "approved_at": po.approved_at, "work_order_id": po.work_order_id,
        "items": [{
            "id": i.id, "product_id": i.product_id, "product_name": i.product.name if i.product else None,
            "qty": i.qty, "unit_price": i.unit_price, "line_total": i.qty * i.unit_price,
        } for i in po.items],
        "receipts": [{
            "id": r.id, "condition": r.condition, "notes": r.notes, "received_date": r.received_date,
            "received_by_name": r.receiver.name if r.receiver else None,
            "files": [{"id": f.id, "kind": f.kind, "filename": f.filename,
                       "content_type": f.content_type, "size": f.size} for f in r.files],
        } for r in po.receipts],
    }


def _next_po_number(db: Session, org_id) -> str:
    # Serialise numbering per org: lock the org row for this transaction.
    db.query(Organization).filter(Organization.id == org_id).with_for_update().first()
    n = db.query(func.count(PurchaseOrder.id)).filter(PurchaseOrder.org_id == org_id).scalar() or 0
    while True:
        n += 1
        num = f"PO-{n:04d}"
        if not db.query(PurchaseOrder.id).filter(PurchaseOrder.org_id == org_id, PurchaseOrder.po_number == num).first():
            return num


def _require_approved(po: PurchaseOrder, what: str):
    if po.approval_status != "approved":
        raise HTTPException(400, f"This purchase order is '{po.approval_status}'. Only an approved purchase order can be {what}.")


def _log_email(db, org_id, po, kind, channel, to_email, subject, status, user, receipt_id=None):
    db.add(ProcurementEmailLog(org_id=org_id, po_id=po.id, receipt_id=receipt_id, kind=kind, channel=channel,
                               to_email=to_email, subject=subject, status=status, created_by=user.id))
    workpages.safe(db, workpages.on_procurement_notice, po, kind, channel, status, to_email, user)


async def _read_proof(upload: UploadFile | None, label: str, allowed: set[str]) -> tuple[str, bytes, str]:
    if upload is None or not upload.filename:
        raise HTTPException(400, f"{label} is required. Upload it before confirming.")
    data = await upload.read()
    if not data:
        raise HTTPException(400, f"{label} is empty.")
    if len(data) > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise HTTPException(400, f"{label} exceeds the {settings.MAX_UPLOAD_SIZE_MB}MB upload limit.")
    ctype = (upload.content_type or "").lower()
    if ctype not in allowed:
        kinds = "PDF, PNG, JPG or WEBP" if "application/pdf" in allowed else "PNG, JPG or WEBP image"
        raise HTTPException(400, f"{label} must be a {kinds} file.")
    name = upload.filename.replace("/", "_").replace("\\", "_")
    return name, data, ctype


# ---------------------------------------------------------------- Vendors
@router.post("/vendors", response_model=VendorOut, status_code=201, dependencies=[Depends(require_permission("procurement", "create"))])
def create_vendor(payload: VendorCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    data = payload.model_dump()
    data["email"] = _clean_email(data.get("email"))
    vendor = Vendor(org_id=org_id, **data)
    db.add(vendor)
    db.commit()
    db.refresh(vendor)
    return vendor


@router.patch("/vendors/{vendor_id}", response_model=VendorOut, dependencies=[Depends(require_permission("procurement", "edit"))])
def update_vendor(vendor_id: str, payload: VendorUpdate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id, Vendor.org_id == org_id).first()
    if not vendor:
        raise HTTPException(404, "Vendor not found")
    data = payload.model_dump(exclude_unset=True)
    if "email" in data:
        data["email"] = _clean_email(data["email"])
    for k, v in data.items():
        setattr(vendor, k, v)
    db.commit()
    db.refresh(vendor)
    return vendor


@router.get("/vendors", response_model=list[VendorOut], dependencies=[Depends(require_permission("procurement", "view"))])
def list_vendors(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return db.query(Vendor).filter(Vendor.org_id == org_id).order_by(Vendor.name).all()


# -------------------------------------------------------- Purchase orders
@router.post("/purchase-orders", response_model=PurchaseOrderOut, status_code=201, dependencies=[Depends(require_permission("procurement", "create"))])
def create_purchase_order(payload: PurchaseOrderCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    vendor = db.query(Vendor).filter(Vendor.id == payload.vendor_id, Vendor.org_id == org_id).first()
    if not vendor:
        raise HTTPException(404, "Vendor not found")

    try:
        work_id = workpages.check_linkable(db, org_id, payload.work_order_id)
    except workpages.WorkError as e:
        raise HTTPException(400, str(e))

    po = PurchaseOrder(org_id=org_id, vendor_id=payload.vendor_id, order_date=date.today(),
                       created_by=current_user.id, approval_status="pending",
                       po_number=_next_po_number(db, org_id), work_order_id=work_id)
    total = 0
    for item in payload.items:
        product = db.query(Product).filter(Product.id == item.product_id, Product.org_id == org_id).first()
        if not product:
            raise HTTPException(404, f"Product {item.product_id} not found")
        total += item.qty * item.unit_price
        po.items.append(PurchaseOrderItem(product_id=item.product_id, qty=item.qty, unit_price=item.unit_price))
    po.total = total
    db.add(po)
    db.flush()
    notify_role(db, org_id, "Admin", f"{po.po_number} for {vendor.name} is waiting for your approval.")
    workpages.safe(db, workpages.on_po_created, po, current_user)
    log_audit_event(db, org_id, current_user.id, "create_purchase_order", "PurchaseOrder", po.id)
    db.commit()
    return _out(_load_po(db, org_id, po.id))


@router.get("/purchase-orders", response_model=list[PurchaseOrderOut], dependencies=[Depends(require_permission("procurement", "view"))])
def list_purchase_orders(
    vendor_id: str | None = None,
    approval: str = Query("all", pattern="^(all|pending|approved|rejected)$"),
    db: Session = Depends(get_db), org_id: str = Depends(get_org_id),
):
    q = db.query(PurchaseOrder.id).filter(PurchaseOrder.org_id == org_id)
    if vendor_id:
        q = q.filter(PurchaseOrder.vendor_id == vendor_id)
    if approval != "all":
        q = q.filter(PurchaseOrder.approval_status == approval)
    ids = [r[0] for r in q.order_by(PurchaseOrder.order_date.desc(), PurchaseOrder.created_at.desc()).all()]
    return [_out(_load_po(db, org_id, i)) for i in ids]


@router.post("/purchase-orders/{po_id}/approve", response_model=PurchaseOrderOut, dependencies=[Depends(require_permission("procurement", "approve"))])
def approve_purchase_order(po_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    po = _load_po(db, org_id, po_id)
    if po.approval_status != "pending":
        raise HTTPException(400, f"This purchase order is already '{po.approval_status}'.")
    po.approval_status = "approved"
    po.approved_by = current_user.id
    po.approved_at = datetime.utcnow()
    notify_user(db, org_id, po.created_by, f"{po.po_number} was approved by {current_user.name}. You can now send it to the vendor.")
    workpages.safe(db, workpages.on_po_decision, po, current_user, True)
    log_audit_event(db, org_id, current_user.id, "approve_purchase_order", "PurchaseOrder", po.id)
    db.commit()
    return _out(_load_po(db, org_id, po_id))


@router.post("/purchase-orders/{po_id}/reject", response_model=PurchaseOrderOut, dependencies=[Depends(require_permission("procurement", "approve"))])
def reject_purchase_order(po_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    po = _load_po(db, org_id, po_id)
    if po.approval_status != "pending":
        raise HTTPException(400, f"This purchase order is already '{po.approval_status}'.")
    po.approval_status = "rejected"
    po.status = "cancelled"
    po.approved_by = current_user.id
    po.approved_at = datetime.utcnow()
    notify_user(db, org_id, po.created_by, f"{po.po_number} was rejected by {current_user.name}.")
    workpages.safe(db, workpages.on_po_decision, po, current_user, False)
    log_audit_event(db, org_id, current_user.id, "reject_purchase_order", "PurchaseOrder", po.id)
    db.commit()
    return _out(_load_po(db, org_id, po_id))


# ---------------------------------------------------------- PO by email
def _po_mail(db, org_id, po):
    _require_approved(po, "sent to a vendor")
    return docs.build_po_email(_org_name(db, org_id), po)


@router.get("/purchase-orders/{po_id}/email-preview", response_model=EmailPreviewOut, dependencies=[Depends(require_permission("procurement", "view"))])
def po_email_preview(po_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    po = _load_po(db, org_id, po_id)
    mail = _po_mail(db, org_id, po)
    return {**mail, "to_email": po.vendor.email if po.vendor else None}


@router.post("/purchase-orders/{po_id}/send-email", response_model=SendEmailOut, dependencies=[Depends(require_permission("procurement", "edit"))])
def po_send_email(po_id: str, payload: SendEmailIn, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    to_email = _clean_email(payload.to_email)
    if not to_email:
        raise HTTPException(400, "Enter the vendor's email address.")
    po = _load_po(db, org_id, po_id)
    org_name = _org_name(db, org_id)
    mail = _po_mail(db, org_id, po)
    body = mail["body"]
    if payload.note and payload.note.strip():
        body = payload.note.strip() + "\n\n" + body
    pdf = docs.po_pdf(org_name, po)
    status = send_email(to_email, mail["subject"], body, from_name=org_name, reply_to=current_user.email,
                        attachments=[(f"{docs.po_number(po)}.pdf", pdf, "application/pdf")])
    _log_email(db, org_id, po, "po", "email", to_email, mail["subject"], status, current_user)
    log_audit_event(db, org_id, current_user.id, "send_purchase_order_email", "PurchaseOrder", po.id)
    db.commit()
    msg = ("Email sent to the vendor." if status == "sent" else
           "Email provider did not deliver it, so it was recorded in the server log only. "
           "Export the PDF to hand it over, or configure the email service.")
    return {"status": status, "to_email": to_email, "subject": mail["subject"], "message": msg}


# ------------------------------------------------------------------ PDFs
def _pdf(data: bytes, filename: str) -> Response:
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/purchase-orders/{po_id}/pdf", dependencies=[Depends(require_permission("procurement", "view"))])
def po_pdf(po_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    po = _load_po(db, org_id, po_id)
    _require_approved(po, "exported for a vendor")
    _log_email(db, org_id, po, "po", "print", None, f"PDF {docs.po_number(po)}", "printed", current_user)
    db.commit()
    return _pdf(docs.po_pdf(_org_name(db, org_id), po), f"{docs.po_number(po)}.pdf")


@router.get("/vendors/{vendor_id}/purchase-orders/pdf", dependencies=[Depends(require_permission("procurement", "view"))])
def vendor_po_pdf(vendor_id: str, scope: str = Query("all", pattern="^(pending|approved|all)$"),
                  db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id, Vendor.org_id == org_id).first()
    if not vendor:
        raise HTTPException(404, "Vendor not found")
    q = db.query(PurchaseOrder.id).filter(PurchaseOrder.org_id == org_id, PurchaseOrder.vendor_id == vendor.id)
    if scope != "all":
        q = q.filter(PurchaseOrder.approval_status == scope)
    ids = [r[0] for r in q.order_by(PurchaseOrder.order_date, PurchaseOrder.created_at).all()]
    if not ids:
        raise HTTPException(404, f"No {scope if scope != 'all' else ''} purchase orders for {vendor.name}.".replace("  ", " "))
    pos = [_load_po(db, org_id, i) for i in ids]
    return _pdf(vendor_pdf_bytes(db, org_id, vendor, pos, scope), f"{vendor.name.replace(' ', '_')}_{scope}_POs.pdf")


def vendor_pdf_bytes(db, org_id, vendor, pos, scope):
    return docs.vendor_pdf(_org_name(db, org_id), vendor, pos, scope)


# --------------------------------------------------------- Goods receiving
def _save_receipt(db, org_id, po, user, condition, notes, files: list[tuple[str, str, bytes, str]]) -> GoodsReceipt:
    receipt = GoodsReceipt(org_id=org_id, po_id=po.id, received_date=date.today(), condition=condition,
                           notes=(notes or "").strip() or None, received_by=user.id)
    for kind, name, data, ctype in files:
        receipt.files.append(GoodsReceiptFile(org_id=org_id, kind=kind, filename=name,
                                              content_type=ctype, size=len(data), content=data))
    db.add(receipt)
    db.flush()
    return receipt


def _guard_receivable(po: PurchaseOrder):
    _require_approved(po, "received")
    if po.status == "received":
        raise HTTPException(400, "This purchase order has already been received.")
    if po.status == "cancelled":
        raise HTTPException(400, "This purchase order is cancelled.")


@router.post("/purchase-orders/{po_id}/receive-good", response_model=PurchaseOrderOut, dependencies=[Depends(require_permission("procurement", "edit"))])
async def receive_good(
    po_id: str, invoice: UploadFile | None = File(None), pod: UploadFile | None = File(None), notes: str | None = Form(None),
    db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user),
):
    """The only way stock goes up. Needs the vendor invoice AND the courier POD first."""
    po = _load_po(db, org_id, po_id)
    _guard_receivable(po)
    f_inv = await _read_proof(invoice, "The vendor's original invoice", ALLOWED_PROOF_TYPES)
    f_pod = await _read_proof(pod, "The POD / courier copy", ALLOWED_PROOF_TYPES)

    for item in po.items:
        receive_stock(db, org_id, product_id=str(item.product_id), qty=item.qty,
                      ref_type="purchase_order", ref_id=str(po.id))
    _save_receipt(db, org_id, po, current_user, "good", notes, [("invoice", *f_inv), ("pod", *f_pod)])
    po.status = "received"
    notify_role(db, org_id, "Admin", f"{po.po_number} from {po.vendor.name if po.vendor else 'a vendor'} was received in good condition - stock updated.")
    workpages.safe(db, workpages.on_po_received, po, current_user)
    log_audit_event(db, org_id, current_user.id, "receive_purchase_order", "PurchaseOrder", po.id)
    db.commit()
    return _out(_load_po(db, org_id, po_id))


@router.post("/purchase-orders/{po_id}/receive-bad", response_model=PurchaseOrderOut, dependencies=[Depends(require_permission("procurement", "edit"))])
async def receive_bad(
    po_id: str, invoice: UploadFile | None = File(None), pod: UploadFile | None = File(None),
    defect: list[UploadFile] = File(default=[]), notes: str | None = Form(None),
    db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user),
):
    """Goods arrived damaged: nothing goes into stock; proof is stored for the vendor notice."""
    po = _load_po(db, org_id, po_id)
    _guard_receivable(po)
    f_inv = await _read_proof(invoice, "The vendor's original invoice", ALLOWED_PROOF_TYPES)
    f_pod = await _read_proof(pod, "The POD / courier copy", ALLOWED_PROOF_TYPES)
    real = [u for u in defect if u and u.filename]
    if not real:
        raise HTTPException(400, "At least one defect image is required. Upload it before confirming.")
    if len(real) > 6:
        raise HTTPException(400, "Upload at most 6 defect images.")
    f_def = [await _read_proof(u, "The defect image", ALLOWED_IMAGE_TYPES) for u in real]
    for name, data, _ in f_def:
        if not docs.is_valid_image(data):
            raise HTTPException(400, f"The defect image '{name}' is not a readable image file.")

    files = [("invoice", *f_inv), ("pod", *f_pod)] + [("defect", *d) for d in f_def]
    _save_receipt(db, org_id, po, current_user, "bad", notes, files)
    po.status = "defective"
    notify_role(db, org_id, "Admin", f"{po.po_number} from {po.vendor.name if po.vendor else 'a vendor'} arrived DEFECTIVE and was not added to stock.")
    workpages.safe(db, workpages.on_po_defective, po, current_user, (notes or "").strip() or None)
    log_audit_event(db, org_id, current_user.id, "receive_purchase_order_defective", "PurchaseOrder", po.id)
    db.commit()
    return _out(_load_po(db, org_id, po_id))


# --------------------------------------------------------- Defect notices
def _bad_receipt(db, org_id, receipt_id):
    receipt = _receipt_with_content(db, org_id, receipt_id)
    if receipt.condition != "bad":
        raise HTTPException(400, "This receipt was not recorded as defective.")
    po = _load_po(db, org_id, receipt.po_id)
    return po, receipt


@router.get("/receipts/{receipt_id}/defect-preview", response_model=EmailPreviewOut, dependencies=[Depends(require_permission("procurement", "view"))])
def defect_preview(receipt_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    po, receipt = _bad_receipt(db, org_id, receipt_id)
    mail = docs.build_defect_email(_org_name(db, org_id), po, receipt)
    return {**mail, "to_email": po.vendor.email if po.vendor else None}


@router.post("/receipts/{receipt_id}/send-defect-email", response_model=SendEmailOut, dependencies=[Depends(require_permission("procurement", "edit"))])
def defect_send(receipt_id: str, payload: SendEmailIn, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    to_email = _clean_email(payload.to_email)
    if not to_email:
        raise HTTPException(400, "Enter the vendor's email address, or use 'No email ID' to print the notice.")
    po, receipt = _bad_receipt(db, org_id, receipt_id)
    org_name = _org_name(db, org_id)
    mail = docs.build_defect_email(org_name, po, receipt)
    body = mail["body"]
    if payload.note and payload.note.strip():
        body = payload.note.strip() + "\n\n" + body
    atts = [(f.filename, f.content, f.content_type) for f in receipt.files]
    status = send_email(to_email, mail["subject"], body, from_name=org_name, reply_to=current_user.email, attachments=atts)
    _log_email(db, org_id, po, "defect", "email", to_email, mail["subject"], status, current_user, receipt.id)
    log_audit_event(db, org_id, current_user.id, "send_defect_notice_email", "PurchaseOrder", po.id)
    db.commit()
    msg = ("Defect notice emailed to the vendor with the invoice, POD and photos attached." if status == "sent" else
           "Email provider did not deliver it, so it was recorded in the server log only. Print the notice to hand it over.")
    return {"status": status, "to_email": to_email, "subject": mail["subject"], "message": msg}


@router.post("/receipts/{receipt_id}/print-notice", dependencies=[Depends(require_permission("procurement", "edit"))])
def defect_print(receipt_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    """No-email vendors: the same template + defect photos as a printable PDF. Logged as 'printed'."""
    po, receipt = _bad_receipt(db, org_id, receipt_id)
    data = docs.defect_pdf(_org_name(db, org_id), po, receipt)
    _log_email(db, org_id, po, "defect", "print", None, f"Defect notice {docs.po_number(po)}", "printed", current_user, receipt.id)
    log_audit_event(db, org_id, current_user.id, "print_defect_notice", "PurchaseOrder", po.id)
    db.commit()
    return _pdf(data, f"Defect_Notice_{docs.po_number(po)}.pdf")


@router.get("/receipt-files/{file_id}", dependencies=[Depends(require_permission("procurement", "view"))])
def download_receipt_file(file_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    f = db.query(GoodsReceiptFile).filter(GoodsReceiptFile.id == file_id, GoodsReceiptFile.org_id == org_id).first()
    if not f:
        raise HTTPException(404, "File not found")
    return Response(content=f.content, media_type=f.content_type,
                    headers={"Content-Disposition": f'inline; filename="{f.filename}"'})
