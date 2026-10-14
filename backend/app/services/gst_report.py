"""
Finance > GST summary.

  Output GST  = GST collected from customers, read from the books (Cr/Dr on 2210 CGST Payable and 2220 SGST Payable, so credit
                notes and refunds already reduce it).
  Input GST   = GST we paid vendors, read from the stock lots (quantity x cost x slab), by inward date. A lot flagged "not
                claimable" is shown separately: it is a real cost, not a credit.
  Net payable = Output GST - claimable Input GST (what is remitted to the government in the return).

Stock already counted in Inventory before it was priced (source "priced_existing") is not a new purchase, so it is left out.
"""
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.finance import ChartOfAccounts, JournalEntry, JournalLine
from app.models.procurement import PurchaseOrder
from app.models.sales import Product
from app.models.stock import StockBatch
from app.services import gst

q2 = gst.q2


def _month(d) -> str:
    return d.strftime("%Y-%m") if d else "unknown"


def summary(db: Session, org_id) -> dict:
    months: dict = defaultdict(lambda: {"out_cgst": Decimal(0), "out_sgst": Decimal(0), "in_cgst": Decimal(0), "in_sgst": Decimal(0),
                                         "blocked_cgst": Decimal(0), "blocked_sgst": Decimal(0)})
    rows = (db.query(JournalEntry.date, ChartOfAccounts.code, func.coalesce(JournalLine.credit, 0) - func.coalesce(JournalLine.debit, 0))
            .join(JournalLine, JournalLine.journal_entry_id == JournalEntry.id)
            .join(ChartOfAccounts, ChartOfAccounts.id == JournalLine.account_id)
            .filter(JournalEntry.org_id == org_id, ChartOfAccounts.code.in_(["2210", "2220"])).all())
    for d, code, amt in rows:
        months[_month(d)]["out_cgst" if code == "2210" else "out_sgst"] += Decimal(amt)

    pos = {p.id: p.po_number for p in db.query(PurchaseOrder.id, PurchaseOrder.po_number).filter(PurchaseOrder.org_id == org_id)}
    names = {p.id: p.name for p in db.query(Product.id, Product.name).filter(Product.org_id == org_id)}
    ledger = []
    for b in (db.query(StockBatch).filter(StockBatch.org_id == org_id, StockBatch.source != "priced_existing")
              .order_by(StockBatch.inward_date.desc(), StockBatch.created_at.desc()).all()):
        base = Decimal(b.vendor_amount or 0) * int(b.quantity_in)
        c, s_ = q2(base * Decimal(b.cgst_percent or 0) / 100), q2(base * Decimal(b.sgst_percent or 0) / 100)
        if not (c or s_):
            continue
        m = months[_month(b.inward_date)]
        if b.itc_eligible:
            m["in_cgst"] += c; m["in_sgst"] += s_
        else:
            m["blocked_cgst"] += c; m["blocked_sgst"] += s_
        ledger.append({"batch_id": b.id, "date": b.inward_date, "product_name": names.get(b.product_id), "vendor_name": b.vendor_name,
                       "po_number": pos.get(b.po_id) if b.po_id else None, "quantity": b.quantity_in, "taxable_value": q2(base),
                       "cgst": c, "sgst": s_, "total_gst": q2(c + s_), "eligible": bool(b.itc_eligible), "source": b.source})
    out_rows = []
    tot = defaultdict(lambda: Decimal(0))
    for key in sorted(months, reverse=True):
        m = {k: q2(v) for k, v in months[key].items()}
        out, cred = m["out_cgst"] + m["out_sgst"], m["in_cgst"] + m["in_sgst"]
        row = {"month": key, **m, "output_gst": q2(out), "input_credit": q2(cred), "blocked": q2(m["blocked_cgst"] + m["blocked_sgst"]),
               "net_payable": q2(out - cred)}
        out_rows.append(row)
        for k in ("output_gst", "input_credit", "blocked", "net_payable"):
            tot[k] += row[k]
    return {"months": out_rows, "ledger": ledger, "totals": {k: q2(v) for k, v in tot.items()} or
            {"output_gst": q2(0), "input_credit": q2(0), "blocked": q2(0), "net_payable": q2(0)}}
