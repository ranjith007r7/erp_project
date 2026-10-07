"""
Everything that turns a purchase order into something a vendor can read:
the common email template (one template for every vendor - only the names,
items and amounts change), the defect-notice template, and the PDFs used
when a vendor has no email and the paperwork is handed over in person.

PDFs use "Rs." because reportlab's built-in fonts have no rupee glyph.
"""
import io
import re
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
APPROVAL_LABEL = {"pending": "Pending approval", "approved": "Approved", "rejected": "Rejected"}
STATUS_LABEL = {"pending": "Awaiting delivery", "received": "Received", "defective": "Delivered defective", "cancelled": "Cancelled"}
KIND_LABEL = {"invoice": "Vendor invoice", "pod": "POD / courier copy", "defect": "Defect photo"}


def valid_email(addr: str | None) -> bool:
    return bool(addr and EMAIL_RE.match(addr.strip()))


def is_valid_image(data: bytes) -> bool:
    try:
        from PIL import Image as PILImage
        with PILImage.open(io.BytesIO(data)) as im:
            im.load()
        return True
    except Exception:
        return False


def money(v) -> str:
    return f"Rs. {Decimal(v or 0):,.2f}"


def _who(user) -> str:
    if not user:
        return "-"
    role = user.role.name if getattr(user, "role", None) else "-"
    return f"{user.name} ({user.email}, {role})"


def po_number(po) -> str:
    return po.po_number or f"PO-{str(po.id)[:8].upper()}"


def _item_lines(po) -> list[str]:
    lines = []
    for i, it in enumerate(po.items, 1):
        name = it.product.name if it.product else "Item"
        lines.append(f"  {i}. {name} - qty {it.qty} x {money(it.unit_price)} = {money(it.qty * it.unit_price)}")
    return lines


# ---------------------------------------------------------------- emails
def build_po_email(org_name: str, po) -> dict:
    vendor = po.vendor.name if po.vendor else "Vendor"
    body = "\n".join([
        f"Dear {vendor},",
        "",
        f"{org_name} would like to place the following purchase order with you. "
        "Please review it and confirm availability and the delivery date.",
        "",
        f"PO number: {po_number(po)}",
        f"PO date: {po.order_date:%d %b %Y}",
        f"Raised by: {_who(po.creator)}",
        f"Approved by: {_who(po.approver)}",
        "",
        "Items:",
        *_item_lines(po),
        "",
        f"Quoted total: {money(po.total)}",
        "",
        "Please quote the PO number on your invoice and on the courier proof of delivery.",
        "",
        "Regards,",
        org_name,
    ])
    return {
        "from_name": org_name, "to_name": vendor,
        "subject": f"Purchase Order {po_number(po)} from {org_name}",
        "body": body, "attachments": [f"{po_number(po)}.pdf"],
    }


def build_defect_email(org_name: str, po, receipt) -> dict:
    vendor = po.vendor.name if po.vendor else "Vendor"
    notes = (receipt.notes or "").strip() or "Goods were found damaged / defective on inspection."
    files = [f"{KIND_LABEL.get(f.kind, f.kind)}: {f.filename}" for f in receipt.files]
    body = "\n".join([
        f"Dear {vendor},",
        "",
        f"We received the goods against purchase order {po_number(po)} on {receipt.received_date:%d %b %Y} "
        "and, on physical inspection, found them to be in unacceptable condition. "
        "We have NOT accepted this delivery into stock.",
        "",
        f"PO number: {po_number(po)}",
        f"PO total: {money(po.total)}",
        f"Inspected by: {_who(receipt.receiver)}",
        "",
        "Items ordered:",
        *_item_lines(po),
        "",
        "Defect details:",
        f"  {notes}",
        "",
        "Attached: your original invoice, the courier proof of delivery, and photographs of the defect.",
        *[f"  - {f}" for f in files],
        "",
        "Please arrange a replacement or credit and confirm by return.",
        "",
        "Regards,",
        org_name,
    ])
    return {
        "from_name": org_name, "to_name": vendor,
        "subject": f"Defective goods - {po_number(po)} - {org_name}",
        "body": body, "attachments": [f.filename for f in receipt.files],
    }


# ------------------------------------------------------------------ PDFs
_styles = getSampleStyleSheet()
_H = ParagraphStyle("h", parent=_styles["Title"], fontSize=17, alignment=0, spaceAfter=2)
_S = ParagraphStyle("s", parent=_styles["Normal"], fontSize=9, textColor=colors.HexColor("#555555"))
_N = ParagraphStyle("n", parent=_styles["Normal"], fontSize=9, leading=12)
_B = ParagraphStyle("b", parent=_styles["Heading3"], fontSize=11, spaceBefore=8, spaceAfter=3)


def _esc(t) -> str:
    return str(t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _po_block(po) -> list:
    out = [Paragraph(f"{_esc(po_number(po))} &nbsp;-&nbsp; {APPROVAL_LABEL.get(po.approval_status, po.approval_status)}", _B),
           Paragraph(f"Date {po.order_date:%d %b %Y} | Delivery: {STATUS_LABEL.get(po.status, po.status)} | "
                     f"Raised by {_esc(_who(po.creator))} | Approved by {_esc(_who(po.approver))}", _S)]
    rows = [["#", "Item", "Qty", "Unit price", "Amount"]]
    for i, it in enumerate(po.items, 1):
        rows.append([str(i), it.product.name if it.product else "Item", str(it.qty),
                     money(it.unit_price), money(it.qty * it.unit_price)])
    rows.append(["", "", "", "Total", money(po.total)])
    t = Table(rows, colWidths=[8 * mm, 85 * mm, 15 * mm, 33 * mm, 33 * mm], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -2), 0.3, colors.HexColor("#cccccc")),
        ("FONTNAME", (3, -1), (-1, -1), "Helvetica-Bold"), ("LINEABOVE", (3, -1), (-1, -1), 0.6, colors.black),
    ]))
    out += [Spacer(1, 3), t, Spacer(1, 6)]
    return out


def _doc(buf, title):
    return SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                             topMargin=15 * mm, bottomMargin=15 * mm, title=title)


def po_pdf(org_name: str, po) -> bytes:
    buf = io.BytesIO()
    story = [Paragraph(f"Purchase Order {_esc(po_number(po))}", _H),
             Paragraph(f"From: {_esc(org_name)} &nbsp;&nbsp; To: {_esc(po.vendor.name if po.vendor else '')}", _N)]
    if po.vendor and po.vendor.address:
        story.append(Paragraph(_esc(po.vendor.address), _S))
    story += _po_block(po)
    story.append(Paragraph("Please quote the PO number on your invoice and courier proof of delivery.", _S))
    _doc(buf, f"PO {po_number(po)}").build(story)
    return buf.getvalue()


def vendor_pdf(org_name: str, vendor, pos: list, scope: str) -> bytes:
    buf = io.BytesIO()
    label = {"pending": "Pending approval only", "approved": "Approved only", "all": "All purchase orders"}[scope]
    story = [Paragraph(f"Purchase orders - {_esc(vendor.name)}", _H),
             Paragraph(f"From: {_esc(org_name)} | Selection: {label} | {len(pos)} order(s)", _N)]
    if vendor.address:
        story.append(Paragraph(_esc(vendor.address), _S))
    story.append(Spacer(1, 6))
    for po in pos:
        story.append(KeepTogether(_po_block(po)))
    total = sum((Decimal(p.total or 0) for p in pos), Decimal(0))
    story.append(Paragraph(f"<b>Grand total of listed orders: {money(total)}</b>", _N))
    _doc(buf, f"POs {vendor.name}").build(story)
    return buf.getvalue()


def defect_pdf(org_name: str, po, receipt) -> bytes:
    """Printable defect notice for vendors with no email: message + defect photos."""
    mail = build_defect_email(org_name, po, receipt)
    buf = io.BytesIO()
    story = [Paragraph("Defective Goods Notice", _H),
             Paragraph(f"From: {_esc(org_name)} &nbsp;&nbsp; To: {_esc(mail['to_name'])}", _N), Spacer(1, 6)]
    for line in mail["body"].split("\n"):
        story.append(Paragraph(_esc(line).replace("  ", "&nbsp;&nbsp;") or "&nbsp;", _N))
    imgs = [f for f in receipt.files if f.kind == "defect" and f.content_type.startswith("image/")]
    if imgs:
        story.append(Paragraph("Defect photographs", _B))
    for f in imgs:
        try:
            if not is_valid_image(f.content):
                raise ValueError("unreadable image")
            im = Image(io.BytesIO(f.content))
            w, h = im.imageWidth, im.imageHeight
            scale = min(170 * mm / w, 110 * mm / h, 1)
            im.drawWidth, im.drawHeight = w * scale, h * scale
            story += [KeepTogether([im, Paragraph(_esc(f.filename), _S)]), Spacer(1, 6)]
        except Exception:
            story.append(Paragraph(f"(could not render {_esc(f.filename)})", _S))
    _doc(buf, f"Defect notice {po_number(po)}").build(story)
    return buf.getvalue()
