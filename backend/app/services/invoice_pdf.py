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


def render_invoice(doc: dict) -> bytes:
    """
    doc = {company, number, date, order_date, status ("PAID" / "PART PAID" / "CANCELLED"), customer{name, address, gstin, extra},
           lines[{name, hsn, qty, rate, taxable, cgst_percent, sgst_percent, cgst, sgst, total}],
           discount{percent, amount} | None, taxable, cgst, sgst, total (net payable), gross (before discount, GST incl.),
           paid, balance, payments[{date, method, reference, amount}], refunds[{date, method, reference, amount, charge}], notes[]}
    Vendor prices never appear: only what the customer is charged.
    """
    co = doc["company"]
    cust = doc["customer"]
    number = doc["number"]
    story = []
    left = [Paragraph(_esc(co["name"]), _CO)] + [Paragraph(_esc(a), _N) for a in co["address"]]
    left += [Paragraph(_esc(" | ".join(co["contact"])), _S)] if co["contact"] else []
    left += [Paragraph("<b>" + _esc("   ".join(co["ids"])) + "</b>", _N)] if co["ids"] else []
    right = [Paragraph("TAX INVOICE", _T),
             Paragraph(f"<b>Invoice No:</b> {_esc(number)}", _R),
             Paragraph(f"<b>Date:</b> {doc['date']:%d %b %Y}", _R)]
    if doc.get("order_date"):
        right.append(Paragraph(f"<b>Order date:</b> {doc['order_date']:%d %b %Y}", _R))
    right.append(Paragraph(f"<b>Status:</b> {doc['status']}", _R))
    head = Table([[left, right]], colWidths=[110 * mm, 70 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, 0), 1, INK),
                              ("BOTTOMPADDING", (0, 0), (-1, 0), 6), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story += [head, Spacer(1, 8)]

    bill = [Paragraph("BILL TO", _H), Paragraph(f"<b>{_esc(cust['name'])}</b>", _N)]
    for line in (cust.get("address") or "").split("\n"):
        if line.strip():
            bill.append(Paragraph(_esc(line.strip()), _N))
    if cust.get("gstin"):
        bill.append(Paragraph(f"GSTIN: {_esc(cust['gstin'])}", _N))
    ship = [Paragraph("SUPPLY", _H), Paragraph("Intra-state supply (CGST + SGST)", _N)]
    parties = Table([[bill, ship]], colWidths=[110 * mm, 70 * mm])
    parties.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [parties, Spacer(1, 8)]

    rows = [["#", "Item", "HSN", "Qty", "Price\nexcl. GST", "CGST", "SGST", "Price\nincl. GST"]]
    for i, ln in enumerate(doc["lines"], 1):
        rows.append([str(i), Paragraph(_esc(ln["name"]), _N), ln.get("hsn") or "-", str(ln["qty"]),
                     f"{ln['taxable']:,.2f}", f"{ln['cgst']:,.2f}\n@{Decimal(ln['cgst_percent']):g}%",
                     f"{ln['sgst']:,.2f}\n@{Decimal(ln['sgst_percent']):g}%", f"{ln['total']:,.2f}"])
    t = Table(rows, colWidths=[7 * mm, 55 * mm, 18 * mm, 11 * mm, 25 * mm, 22 * mm, 22 * mm, 25 * mm], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INK), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.3, LINE), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story += [t, Spacer(1, 6)]

    tot = []
    bold_rows = []
    if doc.get("discount"):
        d = doc["discount"]
        tot += [["Total (GST included)", money(doc["gross"])],
                [f"Less discount ({Decimal(d['percent']):g}%)", "- " + money(d["amount"])],
                ["Net amount payable", money(doc["total"])]]
        bold_rows.append(len(tot) - 1)
        tot += [["of which: taxable value", money(doc["taxable"])], ["CGST", money(doc["cgst"])], ["SGST", money(doc["sgst"])]]
    else:
        tot += [["Taxable value", money(doc["taxable"])], ["CGST", money(doc["cgst"])], ["SGST", money(doc["sgst"])],
                ["Grand total", money(doc["total"])]]
        bold_rows.append(len(tot) - 1)
    tot += [["Received", money(doc["paid"])], ["Balance due", money(doc["balance"])]]
    tt = Table(tot, colWidths=[40 * mm, 33 * mm])
    style = [("FONTSIZE", (0, 0), (-1, -1), 8.5), ("ALIGN", (1, 0), (1, -1), "RIGHT"), ("FONTNAME", (0, len(tot) - 1), (-1, len(tot) - 1), "Helvetica-Bold")]
    for r in bold_rows:
        style += [("FONTNAME", (0, r), (-1, r), "Helvetica-Bold"), ("LINEABOVE", (0, r), (-1, r), 0.8, INK), ("LINEBELOW", (0, r), (-1, r), 0.8, INK)]
    tt.setStyle(TableStyle(style))
    words = [Paragraph("AMOUNT IN WORDS", _H), Paragraph(_esc(amount_in_words(doc["total"])), _N)]
    summary = Table([[words, tt]], colWidths=[107 * mm, 73 * mm])
    summary.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [KeepTogether([summary]), Spacer(1, 8)]

    METHOD = {"cash": "Cash", "card": "Card", "gpay": "GPay / UPI", "bank_transfer": "Bank transfer", "cheque": "Cheque"}
    if doc["payments"]:
        prow = [["Date", "Paid via", "Reference no.", "Amount"]]
        for p in doc["payments"]:
            prow.append([f"{p['date']:%d %b %Y}" if p.get("date") else "-", METHOD.get(p["method"], p["method"]), p.get("reference") or "-", money(p["amount"])])
        pt = Table(prow, colWidths=[30 * mm, 35 * mm, 70 * mm, 35 * mm], repeatRows=1, hAlign="LEFT")
        pt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e7eb")), ("FONTSIZE", (0, 0), (-1, -1), 8),
                                ("ALIGN", (3, 0), (3, -1), "RIGHT"), ("GRID", (0, 0), (-1, -1), 0.3, LINE)]))
        story += [KeepTogether([Paragraph("PAYMENTS RECEIVED", _H), Spacer(1, 2), pt]), Spacer(1, 10)]
    if doc.get("refunds"):
        rrow = [["Date", "Refunded via", "Reference no.", "Cancellation charge", "Refunded"]]
        for r in doc["refunds"]:
            rrow.append([f"{r['date']:%d %b %Y}" if r.get("date") else "-", METHOD.get(r["method"], r["method"] or "-"), r.get("reference") or "-",
                         money(r["charge"]), money(r["amount"])])
        rt = Table(rrow, colWidths=[28 * mm, 32 * mm, 50 * mm, 36 * mm, 24 * mm], repeatRows=1, hAlign="LEFT")
        rt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#fee2e2")), ("FONTSIZE", (0, 0), (-1, -1), 8),
                                ("ALIGN", (3, 0), (4, -1), "RIGHT"), ("GRID", (0, 0), (-1, -1), 0.3, LINE)]))
        story += [KeepTogether([Paragraph("REFUND AFTER CANCELLATION", _H), Spacer(1, 2), rt]), Spacer(1, 10)]
    for n in doc.get("notes") or []:
        story.append(Paragraph(_esc(n), _S))
    story.append(Spacer(1, 8))

    sign = Table([[Paragraph("This is a computer-generated invoice and needs no signature.", _S),
                   [Paragraph(f"For <b>{_esc(co['name'])}</b>", _R), Spacer(1, 22), Paragraph("Authorised signatory", _R)]]],
                 colWidths=[100 * mm, 80 * mm])
    sign.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "BOTTOM"), ("LINEABOVE", (0, 0), (-1, 0), 0.4, LINE), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story.append(KeepTogether([sign]))

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                      title=f"{number} - {co['name']}").build(story)
    return buf.getvalue()
