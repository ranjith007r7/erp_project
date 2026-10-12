"""
Amending the prices of a RECEIVED purchase order, with a trail.

A received PO is a posted document, so it is never silently overwritten. A correction keeps the original price
(PoPriceCorrection: old, new, who, when, why) and, in one transaction, carries the new price to everything that was
built from it: the PO line and total, the stock lots it created, the cost already recorded on works that took units
from those lots, and those works' vendor amount (and so profit). Quantities are never touched here.
Cross-module logic lives in services, so Procurement and Workpage stay loosely coupled.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.procurement import PurchaseOrder, PoPriceCorrection
from app.models.sales import Product
from app.models.user import User
from app.models.workpage import WorkOrder, WorkStockIssue
from app.services import stock as stock_svc, workpages
from app.services.audit import log_audit_event

q2 = workpages.q2


class CorrectionError(Exception):
    pass


def correct_prices(db: Session, org_id, po: PurchaseOrder, user: User, changes: list[tuple], reason: str) -> list[PoPriceCorrection]:
    """changes: [(po_item_id, new_unit_price)]"""
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise CorrectionError("Give the reason for the correction (for example: keyed 4000, the vendor invoice says 2500).")
    if po.status != "received":
        raise CorrectionError("Only a received purchase order can be corrected here. Before that, reject it and raise a new one.")
    by_id = {str(i.id): i for i in po.items}
    todo = []
    for item_id, price in changes:
        item = by_id.get(str(item_id))
        if not item:
            raise CorrectionError("That line is not on this purchase order.")
        new = q2(price)
        if new < 0:
            raise CorrectionError("A price cannot be negative.")
        if new != q2(item.unit_price):
            todo.append((item, new))
    if not todo:
        raise CorrectionError("No price was changed.")

    # lots this PO created, paired with its lines of the same product in order
    lots = {}
    for b in db.query(stock_svc.StockBatch).filter(stock_svc.StockBatch.org_id == org_id, stock_svc.StockBatch.po_id == po.id).order_by(stock_svc.StockBatch.created_at).all():
        lots.setdefault(b.product_id, []).append(b)
    line_order: dict = {}
    for i in po.items:
        line_order.setdefault(i.product_id, []).append(i)

    logs, works, lines_txt = [], {}, []
    for item, new in todo:
        old = q2(item.unit_price)
        logs.append(PoPriceCorrection(org_id=org_id, po_id=po.id, product_id=item.product_id, qty=item.qty, old_price=old,
                                      new_price=new, reason=reason, corrected_by=user.id))
        item.unit_price = new
        prod = db.get(Product, item.product_id)
        lines_txt.append(f"{prod.name if prod else 'item'} {old} -> {new}")
        pos_in_line = line_order[item.product_id].index(item)
        mine = lots.get(item.product_id, [])
        lot = mine[pos_in_line] if pos_in_line < len(mine) else None
        if lot is not None:
            lot.vendor_amount = new
            stamp = f"[{date.today().isoformat()} {user.name}: cost {old} -> {new} (PO price corrected)]"
            lot.note = (f"{lot.note} {stamp}" if lot.note else stamp)[:500]
            for iss in db.query(WorkStockIssue).filter(WorkStockIssue.batch_id == lot.id).all():
                iss.cost_rate = new
                works[iss.work_id] = True
    po.total = q2(sum(Decimal(i.qty) * Decimal(i.unit_price) for i in po.items))
    for lg in logs:
        db.add(lg)
    if po.work_order_id:
        works[po.work_order_id] = True
    db.flush()

    for wid in works:
        w = db.get(WorkOrder, wid)
        if not w:
            continue
        old_vendor = q2(w.vendor_amount or 0)
        issues = db.query(WorkStockIssue).filter(WorkStockIssue.work_id == w.id).all()
        if issues and all(i.batch_id for i in issues):
            w.vendor_amount = q2(sum(Decimal(i.qty) * Decimal(i.cost_rate or 0) for i in issues))
        else:
            workpages.sync_vendor_amount(db, w)
        new_vendor = q2(w.vendor_amount or 0)
        workpages.log_event(db, w, "po_price_corrected", f"{po.po_number} price corrected",
                            f"{'; '.join(lines_txt)} by {user.name}. Reason: {reason}. Vendor amount {old_vendor} -> {new_vendor}.", user,
                            {"po_number": po.po_number})
    log_audit_event(db, org_id, user.id, f"correct_po_prices {po.po_number}: " + "; ".join(lines_txt), "PurchaseOrder", po.id)
    return logs
