"""
The printable tax invoice (A4 PDF). Everything on it is read from live records: the company block comes from the
organization profile (legal name, address, GSTIN, PAN, contacts), the customer from the customer record, the lines
from the sales order the invoice was raised for, and the payments from Finance. Nothing is typed again.

PDFs use "Rs." because reportlab's built-in fonts have no rupee glyph.
"""
import io
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

from app.services import gst

_ss = getSampleStyleSheet()
_N = ParagraphStyle("n", parent=_ss["Normal"], fontSize=8.5, leading=11)
_S = ParagraphStyle("s", parent=_N, fontSize=7.5, textColor=colors.HexColor("#555555"))
_R = ParagraphStyle("r", parent=_N, alignment=2)
_CO = ParagraphStyle("co", parent=_ss["Title"], fontSize=17, alignment=0, spaceAfter=2, leading=20)
_T = ParagraphStyle("t", parent=_ss["Title"], fontSize=13, alignment=2, spaceAfter=2, textColor=colors.HexColor("#1f2937"))
_H = ParagraphStyle("h", parent=_N, fontName="Helvetica-Bold", fontSize=8, textColor=colors.HexColor("#6b7280"))
INK = colors.HexColor("#1f2937")
LINE = colors.HexColor("#cbd5e1")


def _esc(t) -> str:
    return str(t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def money(v) -> str:
    return f"Rs. {Decimal(v or 0):,.2f}"


_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_TENS = "x x twenty thirty forty fifty sixty seventy eighty ninety".split()


def _below_1000(n: int) -> str:
    out = []
    if n >= 100:
        out.append(_ONES[n // 100] + " hundred")
        n %= 100
    if n >= 20:
        out.append(_TENS[n // 10] + ("-" + _ONES[n % 10] if n % 10 else ""))
    elif n > 0:
        out.append(_ONES[n])
    return " ".join(out)


def amount_in_words(amount) -> str:
    """Indian numbering: 123456.50 -> 'One lakh twenty-three thousand four hundred fifty-six rupees and fifty paise only'."""
    amount = gst.q2(amount)
    rupees, paise = int(amount), int((amount - int(amount)) * 100)
    if rupees == 0 and paise == 0:
        return "Zero rupees only"
    parts = []
    for name, size in (("crore", 10_000_000), ("lakh", 100_000), ("thousand", 1000)):
        if rupees >= size:
            parts.append(_below_1000(rupees // size) + " " + name)
            rupees %= size
    if rupees:
        parts.append(_below_1000(rupees))
    words = " ".join(parts) if parts else "zero"
    text = words + " rupees" if (int(amount) or not paise) else ""
    if paise:
        text += (" and " if text else "") + _below_1000(paise) + " paise"
    return text.strip().capitalize() + " only"


def company_block(org, profile) -> dict:
    name = (profile.legal_name if profile and profile.legal_name else None) or org.name
    addr = []
    if profile:
        addr = [x for x in (profile.address_line1, profile.address_line2) if x]
        city = ", ".join(x for x in (profile.city, profile.state) if x)
        tail = " - ".join(x for x in (city, profile.postal_code) if x)
        if tail:
            addr.append(tail)
        if profile.country:
            addr.append(profile.country)
    contact = []
    if profile:
        if profile.company_phone:
            contact.append(f"Phone: {profile.company_phone}")
        if profile.company_email:
            contact.append(f"Email: {profile.company_email}")
        if profile.website:
            contact.append(profile.website)
    ids = []
    if profile:
        if profile.gstin:
            ids.append(f"GSTIN: {profile.gstin}")
        if profile.pan:
            ids.append(f"PAN: {profile.pan}")
        if profile.cin:
            ids.append(f"CIN: {profile.cin}")
    return {"name": name, "address": addr, "contact": contact, "ids": ids}


def invoice_pdf(*, org, profile, customer, invoice, order, items, payments) -> bytes:
    """items: sales-order lines (with .product). payments: Finance payments of this invoice."""
    co = company_block(org, profile)
    paid = gst.q2(sum((Decimal(p.amount) for p in payments), Decimal(0)))
    total = gst.q2(invoice.amount)
    balance = max(total - paid, Decimal(0))
    status = "PAID" if balance == 0 else "PART PAID"
    number = invoice.invoice_number or f"INV-{str(invoice.id)[:8].upper()}"
    inv_date = (invoice.created_at or order.order_date)
    inv_date = inv_date.date() if hasattr(inv_date, "date") else inv_date

    story = []
    left = [Paragraph(_esc(co["name"]), _CO)] + [Paragraph(_esc(a), _N) for a in co["address"]]
    left += [Paragraph(_esc(" | ".join(co["contact"])), _S)] if co["contact"] else []
    left += [Paragraph("<b>" + _esc("   ".join(co["ids"])) + "</b>", _N)] if co["ids"] else []
    right = [Paragraph("TAX INVOICE", _T),
             Paragraph(f"<b>Invoice No:</b> {_esc(number)}", _R),
             Paragraph(f"<b>Date:</b> {inv_date:%d %b %Y}", _R),
             Paragraph(f"<b>Order date:</b> {order.order_date:%d %b %Y}", _R),
             Paragraph(f"<b>Status:</b> {status}", _R)]
    head = Table([[left, right]], colWidths=[110 * mm, 70 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, 0), 1, INK),
                              ("BOTTOMPADDING", (0, 0), (-1, 0), 6), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story += [head, Spacer(1, 8)]

    bill = [Paragraph("BILL TO", _H), Paragraph(f"<b>{_esc(customer.name)}</b>", _N)]
    if customer.billing_address:
        bill.append(Paragraph(_esc(customer.billing_address).replace("\n", "<br/>"), _N))
    if customer.gst_number:
        bill.append(Paragraph(f"GSTIN: {_esc(customer.gst_number)}", _N))
    ship = [Paragraph("SUPPLY", _H), Paragraph("Intra-state supply (CGST + SGST)", _N)]
    parties = Table([[bill, ship]], colWidths=[110 * mm, 70 * mm])
    parties.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [parties, Spacer(1, 8)]

    rows = [["#", "Item", "HSN", "Qty", "Rate", "Taxable", "CGST", "SGST", "Amount"]]
    for i, it in enumerate(items, 1):
        taxable, cg, sg = gst.line_tax(it.qty, it.unit_price, it.cgst_percent, it.sgst_percent)
        name = it.product.name if it.product else "Item"
        rows.append([str(i), Paragraph(_esc(name), _N), (it.product.hsn_code if it.product and it.product.hsn_code else "-"),
                     str(it.qty), f"{Decimal(it.unit_price):,.2f}", f"{taxable:,.2f}",
                     f"{cg:,.2f}\n@{Decimal(it.cgst_percent):g}%", f"{sg:,.2f}\n@{Decimal(it.sgst_percent):g}%",
                     f"{taxable + cg + sg:,.2f}"])
    t = Table(rows, colWidths=[7 * mm, 49 * mm, 16 * mm, 10 * mm, 21 * mm, 22 * mm, 20 * mm, 20 * mm, 25 * mm], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INK), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.3, LINE), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story += [t, Spacer(1, 6)]

    tot = [["Taxable value", money(invoice.subtotal)], ["CGST", money(invoice.cgst_amount)], ["SGST", money(invoice.sgst_amount)],
           ["Grand total", money(total)], ["Received", money(paid)], ["Balance due", money(balance)]]
    tt = Table(tot, colWidths=[35 * mm, 38 * mm])
    tt.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 8.5), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                            ("FONTNAME", (0, 3), (-1, 3), "Helvetica-Bold"), ("LINEABOVE", (0, 3), (-1, 3), 0.8, INK),
                            ("LINEBELOW", (0, 3), (-1, 3), 0.8, INK), ("FONTNAME", (0, 5), (-1, 5), "Helvetica-Bold")]))
    words = [Paragraph("AMOUNT IN WORDS", _H), Paragraph(_esc(amount_in_words(total)), _N)]
    summary = Table([[words, tt]], colWidths=[107 * mm, 73 * mm])
    summary.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [KeepTogether([summary]), Spacer(1, 8)]

    if payments:
        prow = [["Date", "Method", "Reference", "Amount"]]
        for p in payments:
            prow.append([f"{p.date:%d %b %Y}" if p.date else "-", {"cash": "Cash", "card": "Card", "gpay": "GPay", "bank_transfer": "Bank transfer"}.get(p.method, p.method),
                         p.transaction_id or "-", money(p.amount)])
        pt = Table(prow, colWidths=[30 * mm, 35 * mm, 70 * mm, 35 * mm], repeatRows=1)
        pt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e7eb")), ("FONTSIZE", (0, 0), (-1, -1), 8),
                                ("ALIGN", (3, 0), (3, -1), "RIGHT"), ("GRID", (0, 0), (-1, -1), 0.3, LINE)]))
        story += [KeepTogether([Paragraph("PAYMENTS RECEIVED", _H), Spacer(1, 2), pt]), Spacer(1, 14)]

    sign = Table([[Paragraph("This is a computer-generated invoice and needs no signature.", _S),
                   [Paragraph(f"For <b>{_esc(co['name'])}</b>", _R), Spacer(1, 22), Paragraph("Authorised signatory", _R)]]],
                 colWidths=[100 * mm, 80 * mm])
    sign.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "BOTTOM"), ("LINEABOVE", (0, 0), (-1, 0), 0.4, LINE), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story.append(KeepTogether([sign]))

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                      title=f"{number} - {co['name']}").build(story)
    return buf.getvalue()
