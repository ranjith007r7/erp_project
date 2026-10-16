"""Printable warranty card (A4 PDF) and the vendor notice for a valid customer claim. Read from live records, nothing retyped.
PDFs use "Rs." (built-in fonts have no rupee glyph)."""
import io
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

from app.services.invoice_pdf import _N, _S, _R, _CO, _T, _H, INK, LINE, _esc, money


def _fmt(d, fmt="%d %b %Y"):
    return d.strftime(fmt) if d else "-"


def warranty_card_pdf(company: dict, d: dict) -> bytes:
    """d = services.warranty.detail() plus client block {name, details} and 'invoice_number'."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"Warranty card {d['card_number']}")
    story = []
    left = [Paragraph(_esc(company["name"]), _CO)] + [Paragraph(_esc(a), _N) for a in company["address"]]
    left += [Paragraph(_esc(" | ".join(company["contact"])), _S)] if company["contact"] else []
    left += [Paragraph("<b>" + _esc("   ".join(company["ids"])) + "</b>", _N)] if company["ids"] else []
    right = [Paragraph("WARRANTY CARD", _T), Paragraph(f"<b>Card No:</b> {_esc(d['card_number'])}", _R),
             Paragraph(f"<b>Issued:</b> {_fmt(d.get('approved_at'))}", _R)]
    head = Table([[left, right]], colWidths=[110 * mm, 70 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, 0), 1, INK),
                              ("BOTTOMPADDING", (0, 0), (-1, 0), 6), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story += [head, Spacer(1, 10)]

    cl = d["client"]
    info = [
        ["Customer", cl["name"], "Invoice No", d.get("invoice_number") or "To be issued"],
        ["Work reference", d["work_number"], "Product", d["product_name"]],
        ["Quantity", str(d["qty"]), "Amount (excl. GST)", money(d["amount"])],
        ["Warranty period", d["period_label"] or "-", "Coverage", f"{_fmt(d['start_date'])}  to  {_fmt(d['end_date'])}"],
    ]
    t = Table([[Paragraph(f"<b>{_esc(a)}</b>", _N), Paragraph(_esc(b), _N), Paragraph(f"<b>{_esc(c)}</b>", _N), Paragraph(_esc(e), _N)] for a, b, c, e in info],
              colWidths=[32 * mm, 58 * mm, 34 * mm, 56 * mm])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f5f9")), ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f1f5f9")),
                           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story += [t, Spacer(1, 10), Paragraph("PRODUCT DETAILS (PER UNIT)", _H), Spacer(1, 3)]

    rows = [["#", "Model number", "Serial number", "Manufactured", "Expiry date"]]
    for u in d["units"]:
        rows.append([str(u["position"]), u["model_number"] or "-", u["serial_number"] or "-",
                     _fmt(u["manufacture_month"], "%b %Y"), _fmt(u["expiry_date"])])
    ut = Table(rows, colWidths=[10 * mm, 55 * mm, 55 * mm, 30 * mm, 30 * mm], repeatRows=1)
    ut.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), INK), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                            ("GRID", (0, 0), (-1, -1), 0.3, LINE), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    story += [ut, Spacer(1, 10)]

    terms = (d.get("warranty_terms") or "").strip() or "Manufacturing defects only."
    story += [Paragraph("WARRANTY TERMS", _H), Spacer(1, 3)]
    for line in terms.split("\n"):
        if line.strip():
            story.append(Paragraph(_esc(line.strip()), _N))
    story += [Spacer(1, 4),
              Paragraph("To claim, present this card with the original tax invoice and the product's model and serial number. "
                        "The warranty does not cover damage caused by misuse, accident, unauthorised repair or surge, unless stated above.", _S),
              Spacer(1, 26)]
    sig = Table([[Paragraph("Customer signature", _S), Paragraph(f"For {_esc(company['name'])}<br/>Authorised signatory", _S)]], colWidths=[90 * mm, 90 * mm])
    sig.setStyle(TableStyle([("LINEABOVE", (0, 0), (0, 0), 0.5, INK), ("LINEABOVE", (1, 0), (1, 0), 0.5, INK), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story.append(KeepTogether([sig]))
    doc.build(story)
    return buf.getvalue()


# ------------------------------------------------------------------ vendor notice for a valid claim
def build_vendor_notice(org_name: str, claim: dict) -> dict:
    """claim = services.claims.vendor_notice_data(). The customer's identity and price are never included."""
    vendor = claim["vendor_name"] or "Vendor"
    in_w = claim.get("in_vendor_warranty")
    lines = [
        f"Dear {vendor},", "",
        f"One of the units we bought from you has failed in service and the customer's warranty claim has been approved "
        f"(our reference {claim['claim_number']}). The unit is "
        + ("within your warranty to us" if in_w else ("not clearly within your warranty period; please review" if in_w is False else "being reported for your review")) + ".",
        "",
        f"Product: {claim['product_name']}",
        f"Model number: {claim['model_number'] or '-'}",
        f"Serial number: {claim['serial_number'] or '-'}",
        f"Month of manufacture: {claim['manufacture_month'] or '-'}",
        f"Our purchase order: {claim['po_number'] or '-'}   (inward date {claim['inward_date'] or '-'})",
        f"Your warranty to us: {claim['vendor_warranty'] or 'not recorded'}",
        "", "Fault reported:", f"  {claim['issue']}", "",
        "Attached: photographs of the model number, the serial number and the defect" + (", and supporting documents." if claim["has_supporting"] else "."),
        "", "Please arrange a replacement or credit for this unit and confirm by return.", "", "Regards,", org_name,
    ]
    return {"from_name": org_name, "to_name": vendor, "subject": f"Warranty claim {claim['claim_number']} - {claim['product_name']} - {org_name}",
            "body": "\n".join(lines), "attachments": [f["filename"] for f in claim["files"]]}


def vendor_notice_pdf(org_name: str, claim: dict) -> bytes:
    from reportlab.platypus import Image
    from app.services.procurement_docs import is_valid_image
    mail = build_vendor_notice(org_name, claim)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"Warranty claim notice {claim['claim_number']}")
    story = [Paragraph("Warranty Claim Notice", _T), Paragraph(f"From: {_esc(org_name)} &nbsp;&nbsp; To: {_esc(mail['to_name'])}", _N), Spacer(1, 6)]
    for line in mail["body"].split("\n"):
        story.append(Paragraph(_esc(line).replace("  ", "&nbsp;&nbsp;") or "&nbsp;", _N))
    for f in claim["files"]:
        if f["content_type"].startswith("image/"):
            try:
                if not is_valid_image(f["content"]):
                    raise ValueError
                im = Image(io.BytesIO(f["content"]))
                w, h = im.imageWidth, im.imageHeight
                sc = min(150 * mm / w, 95 * mm / h, 1)
                im.drawWidth, im.drawHeight = w * sc, h * sc
                story += [Spacer(1, 6), KeepTogether([im, Paragraph(_esc(f["filename"]), _S)])]
            except Exception:
                story.append(Paragraph(f"(could not render {_esc(f['filename'])})", _S))
    doc.build(story)
    return buf.getvalue()
