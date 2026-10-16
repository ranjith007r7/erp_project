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
import json
from datetime import date, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload, selectinload, load_only

from app.core.config import settings
from app.core.database import get_db
from app.api.deps import get_current_user, get_org_id, require_permission
from app.services import workpages, po_correction
from app.models.organization import Organization
from app.models.procurement import (
    Vendor, PurchaseOrder, PurchaseOrderItem, GoodsReceipt, GoodsReceiptFile, GoodsReceiptLine, ProcurementEmailLog,
)
from app.models.sales import Product
from app.schemas.procurement import (
    VendorCreate, VendorUpdate, VendorOut,
    PurchaseOrderCreate, PurchaseOrderOut, PriceCorrectionIn, EmailPreviewOut, SendEmailIn, SendEmailOut,
)
from app.services.inventory import receive_stock
from app.services import stock as stock_svc
from app.services.notifications import notify_role, notify_user
from app.services.audit import log_audit_event
from app.services.email import send_email
from app.services import procurement_docs as docs, gst

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
            selectinload(PurchaseOrder.corrections),
            selectinload(PurchaseOrder.receipts).selectinload(GoodsReceipt.lines).joinedload(GoodsReceiptLine.item).joinedload(PurchaseOrderItem.product),
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
        "total": po.total, "cgst_amount": po.cgst_amount, "sgst_amount": po.sgst_amount, "grand_total": po.grand_total,
        "created_by_name": po.creator.name if po.creator else None,
        "created_by_email": po.creator.email if po.creator else None,
        "approved_by_name": po.approver.name if po.approver else None,
        "approved_at": po.approved_at, "work_order_id": po.work_order_id,
        "items": [{
            "id": i.id, "product_id": i.product_id, "product_name": i.product.name if i.product else None,
            "qty": i.qty, "unit_price": i.unit_price, "line_total": i.qty * i.unit_price,
            "cgst_percent": i.cgst_percent, "sgst_percent": i.sgst_percent,
            "received_qty": i.received_qty or 0, "outstanding_qty": i.outstanding_qty, "warranty_months": i.warranty_months,
            "cgst_amount": gst.line_tax(i.qty, i.unit_price, i.cgst_percent, i.sgst_percent)[1],
            "sgst_amount": gst.line_tax(i.qty, i.unit_price, i.cgst_percent, i.sgst_percent)[2],
        } for i in po.items],
        "corrections": [{
            "product_name": c.product.name if c.product else None, "qty": c.qty, "old_price": c.old_price, "new_price": c.new_price,
            "reason": c.reason, "corrected_by_name": c.corrector.name if c.corrector else None, "created_at": c.created_at,
        } for c in po.corrections],
        "receipts": [{
            "id": r.id, "condition": r.condition, "notes": r.notes, "received_date": r.received_date,
            "received_by_name": r.receiver.name if r.receiver else None,
            "lines": [{"product_name": l.item.product.name if l.item and l.item.product else None,
                       "qty_good": l.qty_good, "qty_defective": l.qty_defective} for l in r.lines],
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

    try:
        workpages.validate_po_lines(db, org_id, work_id, [(i.product_id, i.qty) for i in payload.items])
    except workpages.WorkError as e:
        raise HTTPException(400, str(e))

    po = PurchaseOrder(org_id=org_id, vendor_id=payload.vendor_id, order_date=date.today(),
                       created_by=current_user.id, approval_status="pending",
                       po_number=_next_po_number(db, org_id), work_order_id=work_id)
    for item in payload.items:
        product = db.query(Product).filter(Product.id == item.product_id, Product.org_id == org_id).first()
        if not product:
            raise HTTPException(404, f"Product {item.product_id} not found")
        cg = product.cgst_percent if item.cgst_percent is None else item.cgst_percent
        sg = product.sgst_percent if item.sgst_percent is None else item.sgst_percent
        po.items.append(PurchaseOrderItem(product_id=item.product_id, qty=item.qty, unit_price=item.unit_price,
                                          cgst_percent=cg, sgst_percent=sg, warranty_months=item.warranty_months))
    gst.set_po_totals(po)
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


@router.post("/purchase-orders/{po_id}/correct-prices", response_model=PurchaseOrderOut,
             dependencies=[Depends(require_permission("procurement", "correct_price"))])
def correct_po_prices(po_id: str, payload: PriceCorrectionIn, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    """Amend the unit prices of a RECEIVED purchase order. Needs the separate `correct_price` permission (Admin always has it).
    Keeps the old price, who, when and why; carries the new price to the PO total, its stock lots, and the works that used them."""
    po = _load_po(db, org_id, po_id)
    try:
        po_correction.correct_prices(db, org_id, po, current_user, [(l.item_id, l.unit_price) for l in payload.items], payload.reason)
    except po_correction.CorrectionError as e:
        raise HTTPException(400, str(e))
    notify_role(db, org_id, "Admin", f"{po.po_number} prices were corrected by {current_user.name}: {payload.reason.strip()}")
    db.commit()
    return _out(_load_po(db, org_id, po.id))


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
    """The only way stock goes up. Needs the vendor invoice AND the courier POD first. Receives every unit still outstanding on the
    order (after a partial bad-condition receipt that is just the replacement units)."""
    po = _load_po(db, org_id, po_id)
    _guard_receivable(po)
    f_inv = await _read_proof(invoice, "The vendor's original invoice", ALLOWED_PROOF_TYPES)
    f_pod = await _read_proof(pod, "The POD / courier copy", ALLOWED_PROOF_TYPES)

    todo = [i for i in po.items if i.outstanding_qty > 0]
    if not todo:
        raise HTTPException(400, "Nothing is outstanding on this purchase order.")
    replacement = any((i.received_qty or 0) > 0 for i in po.items)     # the units still owed after a partial receipt
    receipt = _save_receipt(db, org_id, po, current_user, "good", notes, [("invoice", *f_inv), ("pod", *f_pod)])
    for item in todo:
        n = item.outstanding_qty
        receive_stock(db, org_id, product_id=str(item.product_id), qty=n,
                      ref_type="purchase_order", ref_id=str(po.id))
        stock_svc.batch_from_po(db, org_id, current_user, po, item, qty=n)   # the priced lot behind these units
        item.received_qty = item.qty
        db.add(GoodsReceiptLine(org_id=org_id, receipt_id=receipt.id, po_item_id=item.id, qty_good=n, qty_defective=0))
    po.status = "received"
    notify_role(db, org_id, "Admin", f"{po.po_number} from {po.vendor.name if po.vendor else 'a vendor'} was received in good condition - stock updated.")
    workpages.safe(db, workpages.on_po_received, po, current_user)
    log_audit_event(db, org_id, current_user.id, "receive_purchase_order", "PurchaseOrder", po.id)
    db.commit()
    return _out(_load_po(db, org_id, po_id))


@router.post("/purchase-orders/{po_id}/receive-bad", response_model=PurchaseOrderOut, dependencies=[Depends(require_permission("procurement", "edit"))])
async def receive_bad(
    po_id: str, invoice: UploadFile | None = File(None), pod: UploadFile | None = File(None),
    defect: list[UploadFile] = File(default=[]), notes: str | None = Form(None), lines: str | None = Form(None),
    db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user),
):
    """Goods arrived damaged. `lines` (JSON [{"item_id", "defective_qty"}]) says how many units of each line are defective: those are
    returned for replacement and stay outstanding on this PO, while the REST of the outstanding units are accepted into stock now
    (invoice + POD are mandatory either way). Without `lines`, every outstanding unit is treated as defective (nothing enters stock)."""
    po = _load_po(db, org_id, po_id)
    _guard_receivable(po)
    open_items = [i for i in po.items if i.outstanding_qty > 0]
    if not open_items:
        raise HTTPException(400, "Nothing is outstanding on this purchase order.")
    bad_qty = {i.id: i.outstanding_qty for i in open_items}            # default: everything outstanding is defective
    if lines:
        try:
            raw = json.loads(lines)
            assert isinstance(raw, list)
        except Exception:
            raise HTTPException(400, "The defective quantities could not be read.")
        by_id = {str(i.id): i for i in open_items}
        bad_qty = {i.id: 0 for i in open_items}
        for r in raw:
            it = by_id.get(str((r or {}).get("item_id")))
            try:
                q = int((r or {}).get("defective_qty"))
            except (TypeError, ValueError):
                raise HTTPException(400, "Each defective quantity must be a whole number.")
            if not it:
                raise HTTPException(400, "A line in the defective list is not an outstanding line of this purchase order.")
            if q < 0 or q > it.outstanding_qty:
                raise HTTPException(400, f"{it.product.name if it.product else 'Item'}: defective quantity must be between 0 and {it.outstanding_qty} (what is still outstanding).")
            bad_qty[it.id] = q
        if sum(bad_qty.values()) < 1:
            raise HTTPException(400, "Enter at least one defective unit, or use 'Goods are in good condition'.")
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
    receipt = _save_receipt(db, org_id, po, current_user, "bad", notes, files)
    accepted, returned = [], []
    for item in open_items:
        bad = bad_qty[item.id]
        good = item.outstanding_qty - bad
        name = item.product.name if item.product else "item"
        if good > 0:        # the good part goes through the same stock path as a good receipt
            receive_stock(db, org_id, product_id=str(item.product_id), qty=good, ref_type="purchase_order", ref_id=str(po.id))
            stock_svc.batch_from_po(db, org_id, current_user, po, item, qty=good)
            item.received_qty = (item.received_qty or 0) + good
            accepted.append(f"{name} x {good}")
        if bad > 0:
            returned.append(f"{name} x {bad}")
        db.add(GoodsReceiptLine(org_id=org_id, receipt_id=receipt.id, po_item_id=item.id, qty_good=good, qty_defective=bad))
    po.status = "defective"
    pn, vn = po.po_number, (po.vendor.name if po.vendor else "a vendor")
    if accepted:
        notify_role(db, org_id, "Admin", f"{pn} from {vn} arrived PARTLY defective: {', '.join(accepted)} added to stock; {', '.join(returned)} returned for replacement.")
    else:
        notify_role(db, org_id, "Admin", f"{pn} from {vn} arrived DEFECTIVE and was not added to stock.")
    detail = (f"{', '.join(accepted)} accepted into stock; {', '.join(returned)} returned to the vendor for replacement. " if accepted else "") + ((notes or "").strip())
    workpages.safe(db, workpages.on_po_defective, po, current_user, detail.strip() or None)
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
