"""
Daily / weekly / monthly activity report for an administrator, as PDF or CSV.
Built from the same numbers as the home page (home_stats.compute) plus the rows
behind them, so the download always agrees with the screen.
PDFs print "Rs." because reportlab's built-in fonts have no rupee glyph.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from app.models.finance import Payment
from app.models.organization import Organization
from app.models.procurement import PurchaseOrder
from app.models.sales import Quotation, Customer
from app.models.user import User
from app.models.workpage import WorkOrder, WorkPayment
from app.services import home_stats as hs
from app.services import workpages as wp

KIND_TO_PERIOD = {"daily": "today", "weekly": "week", "monthly": "month"}


def _m(v) -> str:
    return f"Rs. {Decimal(v or 0):,.2f}"


def build(db: Session, user: User, kind: str, on: date | None) -> dict:
    """Collect everything the report prints. Returns plain python data."""
    period = KIND_TO_PERIOD[kind]
    org_id = user.org_id
    stats = hs.compute(db, user, period, on)
    tz = hs.org_tz(db, org_id)
    first, last = stats["from"], stats["to"]
    from datetime import timedelta
    lo, hi = hs._utc(first, tz), hs._utc(last + timedelta(days=1), tz)
    org = db.get(Organization, org_id)

    works_new = db.query(WorkOrder).filter(WorkOrder.org_id == org_id, WorkOrder.created_at >= lo, WorkOrder.created_at < hi).order_by(WorkOrder.created_at).all()
    works_delivered = db.query(WorkOrder).filter(WorkOrder.org_id == org_id, WorkOrder.delivered_on >= first, WorkOrder.delivered_on <= last).all()
    works_closed = db.query(WorkOrder).filter(WorkOrder.org_id == org_id, WorkOrder.closed_at >= lo, WorkOrder.closed_at < hi).all()
    works_pending = db.query(WorkOrder).filter(WorkOrder.org_id == org_id, WorkOrder.status != "closed").order_by(WorkOrder.created_at).all()
    pos = db.query(PurchaseOrder).filter(PurchaseOrder.org_id == org_id, PurchaseOrder.created_at >= lo, PurchaseOrder.created_at < hi).order_by(PurchaseOrder.created_at).all()
    quotes = db.query(Quotation).filter(Quotation.org_id == org_id, Quotation.created_at >= lo, Quotation.created_at < hi).order_by(Quotation.created_at).all()
    cust = {c.id: c.name for c in db.query(Customer).filter(Customer.org_id == org_id)}
    wpay = db.query(WorkPayment).filter(WorkPayment.org_id == org_id, WorkPayment.created_at >= lo, WorkPayment.created_at < hi).order_by(WorkPayment.created_at).all()
    wnum = {w.id: w.work_number for w in db.query(WorkOrder).filter(WorkOrder.org_id == org_id)}
    fpay = db.query(Payment).filter(Payment.org_id == org_id, Payment.created_at >= lo, Payment.created_at < hi).all()

    def row_w(w):
        r = wp.summary_row(db, w)
        return [r["work_number"], r["client_name"], r["domain"] or "", r["status_label"], str(r["quotation_amount"]),
                str(r["vendor_amount"]), str(r["profit"]), r["handling_department"] or ""]

    return {
        "title": {"daily": "Daily report", "weekly": "Weekly report", "monthly": "Monthly report"}[kind],
        "org_name": org.name if org else "", "from": first, "to": last, "generated_by": user.name,
        "generated_at": datetime.now(timezone.utc).astimezone(tz).strftime("%d %b %Y %H:%M"),
        "kpis": [
            ("Income received", _m((stats["income"] or {}).get("total"))),
            ("Quotes processed", str((stats["quotes"] or {}).get("processed", 0))),
            ("Quotes accepted", str((stats["quotes"] or {}).get("accepted", 0))),
            ("New deals (works)", str((stats["deals"] or {}).get("new", 0))),
            ("Purchase orders raised", str((stats["purchase_orders"] or {}).get("raised", 0))),
            ("Deliveries made", str((stats["deliveries"] or {}).get("delivered", 0))),
            ("Works assigned", str((stats["works"] or {}).get("assigned", 0))),
            ("Works completed", str((stats["works"] or {}).get("completed", 0))),
            ("Works pending (all open)", str((stats["works"] or {}).get("pending", 0))),
        ],
        "tables": [
            ("Works received", ["Work", "Client", "Domain", "Status", "Quoted", "Vendor", "Profit", "Department"], [row_w(w) for w in works_new]),
            ("Works delivered", ["Work", "Client", "Domain", "Status", "Quoted", "Vendor", "Profit", "Department"], [row_w(w) for w in works_delivered]),
            ("Works closed", ["Work", "Client", "Domain", "Status", "Quoted", "Vendor", "Profit", "Department"], [row_w(w) for w in works_closed]),
            ("Purchase orders raised", ["PO", "Vendor", "Date", "Approval", "Status", "Total"],
             [[p.po_number or "", p.vendor.name if p.vendor else "", str(p.order_date), p.approval_status, p.status, str(p.total)] for p in pos]),
            ("Quotations", ["Customer", "Status", "Total"], [[cust.get(q.customer_id, ""), q.status, str(q.total)] for q in quotes]),
            ("Payments received", ["Source", "Reference", "Method", "Amount"],
             [["Work", wnum.get(p.work_id, ""), p.method, str(p.amount)] for p in wpay]
             + [["Invoice", "", p.method or "", str(p.amount)] for p in fpay]),
            ("Open works (all pending)", ["Work", "Client", "Domain", "Status", "Quoted", "Vendor", "Profit", "Department"], [row_w(w) for w in works_pending]),
        ],
    }


def to_csv(data: dict) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([data["title"], data["org_name"]])
    w.writerow(["Period", f"{data['from']} to {data['to']}"])
    w.writerow(["Generated", f"{data['generated_at']} by {data['generated_by']}"])
    w.writerow([])
    w.writerow(["Summary"])
    for k, v in data["kpis"]:
        w.writerow([k, v])
    for title, head, rows in data["tables"]:
        w.writerow([])
        w.writerow([title])
        w.writerow(head)
        w.writerows(rows or [["(none)"]])
    return ("﻿" + buf.getvalue()).encode("utf-8")   # BOM so Excel opens it as UTF-8


def to_pdf(data: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"{data['title']} - {data['org_name']}")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontSize=18, alignment=0, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading3"], fontSize=11, spaceBefore=10, spaceAfter=4)
    small = ParagraphStyle("small", parent=ss["Normal"], fontSize=8, textColor=colors.grey)
    cell = ParagraphStyle("cell", parent=ss["Normal"], fontSize=7.5, leading=9)
    story = [Paragraph(f"{data['title']} - {data['org_name']}", h1),
             Paragraph(f"Period: {data['from']} to {data['to']} &nbsp;|&nbsp; Generated {data['generated_at']} by {data['generated_by']}", small),
             Spacer(1, 6)]
    kp = Table([[Paragraph(f"<b>{v}</b>", ss["Normal"]), Paragraph(k, small)] for k, v in data["kpis"]], colWidths=[40 * mm, 60 * mm])
    kp.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.lightgrey), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story.append(kp)
    for title, head, rows in data["tables"]:
        story.append(Paragraph(title, h2))
        if not rows:
            story.append(Paragraph("None in this period.", small))
            continue
        body = [[Paragraph(f"<b>{c}</b>", cell) for c in head]] + [[Paragraph(str(c).replace("&", "&amp;").replace("<", "&lt;"), cell) for c in r] for r in rows]
        t = Table(body, repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF7")), ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                               ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(t)
    doc.build(story)
    return buf.getvalue()
