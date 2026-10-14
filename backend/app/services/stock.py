"""
Priced stock (batches): the ONE place that knows how a lot of stock comes in, is
checked, and is used up. Stock Intake, Procurement (good receipts), Workpage
(taking stock for a customer's work) and Sales (invoicing) all call here, so the
per-product total in StockLevel and the priced lots in StockBatch cannot drift apart.

Rules
- A batch has: vendor, purchase rate (vendor_amount), MRP, max discount %, inward
  date, manufacture month, expiry date. Rate, MRP and max discount are mandatory
  because employees never type amounts when they take stock: the batch supplies them.
- Stock is used first-expiry-first-out; a batch past its expiry date is never offered.
- StockLevel (inventory.py) stays the total and the movement ledger; every batch
  that adds quantity also writes an "in" movement, every issue writes an "out" movement.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.inventory import StockLevel, Warehouse
from app.models.procurement import Vendor
from app.models.sales import Product
from app.models.stock import StockBatch
from app.services.inventory import receive_stock, issue_stock
from app.services import gst

TWO = Decimal("0.01")
SOURCES = ("manual", "csv", "purchase_order", "priced_existing")


class StockError(Exception):
    """A rule was broken; the route turns this into a 400."""


def q2(v) -> Decimal:
    return Decimal(v or 0).quantize(TWO, rounding=ROUND_HALF_UP)


def month_start(d: date | None) -> date | None:
    return d.replace(day=1) if d else None


def parse_month(text: str | None) -> date | None:
    """'2026-03' (or '2026-03-15') -> 2026-03-01."""
    if not text:
        return None
    t = str(text).strip()
    try:
        if len(t) == 7:
            y, m = t.split("-")
            return date(int(y), int(m), 1)
        return date.fromisoformat(t).replace(day=1)
    except Exception:  # noqa: BLE001
        raise StockError("Month of manufacture must look like 2026-03.")


def validate_fields(*, vendor_name, vendor_amount, mrp, max_discount_percent, inward_date, manufacture_month, expiry_date, today: date | None = None):
    today = today or date.today()
    if not (vendor_name or "").strip():
        raise StockError("Vendor name is required.")
    if vendor_amount is None or Decimal(vendor_amount) < 0:
        raise StockError("Vendor amount (the rate we bought it at) is required and cannot be negative.")
    if mrp is None or Decimal(mrp) <= 0:
        raise StockError("MRP (the most it can be sold for) is required and must be more than zero.")
    md = Decimal(max_discount_percent if max_discount_percent is not None else -1)
    if md < 0 or md > 100:
        raise StockError("Max discount must be a percentage between 0 and 100.")
    if inward_date is None:
        raise StockError("Date of inward is required.")
    if inward_date > today:
        raise StockError("Date of inward cannot be in the future.")
    if manufacture_month and manufacture_month > month_start(inward_date):
        raise StockError("Month of manufacture cannot be after the month of inward.")
    if expiry_date:
        if expiry_date < inward_date:
            raise StockError("Expiry date is before the date of inward - this stock would arrive already expired.")
        if manufacture_month and expiry_date < manufacture_month:
            raise StockError("Expiry date cannot be before the month of manufacture.")


def stock_total(db: Session, org_id, product_id) -> int:
    return int(db.query(func.coalesce(func.sum(StockLevel.quantity), 0))
               .join(Product, Product.id == StockLevel.product_id)
               .filter(Product.org_id == org_id, StockLevel.product_id == product_id).scalar() or 0)


def priced_total(db: Session, org_id, product_id) -> int:
    return int(db.query(func.coalesce(func.sum(StockBatch.quantity_remaining), 0))
               .filter(StockBatch.org_id == org_id, StockBatch.product_id == product_id).scalar() or 0)


def unpriced(db: Session, org_id, product_id) -> int:
    """Units counted in Inventory that no batch (rates) explains yet."""
    return max(stock_total(db, org_id, product_id) - priced_total(db, org_id, product_id), 0)


def _vendor_id(db: Session, org_id, name: str):
    v = db.query(Vendor).filter(Vendor.org_id == org_id, func.lower(Vendor.name) == name.strip().lower()).first()
    return v.id if v else None


def product_default_mrp(product: Product | None):
    """MRP (GST included) a new lot starts at: the product's own MRP, else its list price plus GST, else None."""
    if product is None:
        return None
    if product.mrp and Decimal(product.mrp) > 0:
        return q2(product.mrp)
    if Decimal(product.unit_price or 0) > 0:
        return gst.add_exclusive(product.unit_price, product.cgst_percent, product.sgst_percent)["total"]
    return None


def create_batch(db: Session, org_id, user, *, product_id, quantity: int, vendor_name: str, vendor_amount, mrp,
                 max_discount_percent, inward_date: date | None, manufacture_month: date | None, expiry_date: date | None,
                 source: str = "manual", po_id=None, vendor_id=None, note: str | None = None,
                 already_in_inventory: bool = False, count_stock: bool = True,
                 cgst_percent=None, sgst_percent=None, itc_eligible: bool = True) -> StockBatch:
    """
    Add a priced lot.
      already_in_inventory=True : the units are already in the Inventory total (old stock being priced now);
                                  no movement is written and the quantity must not exceed the unpriced units.
      count_stock=False         : the caller has already added the units to inventory (Procurement receipt).
    """
    product = db.query(Product).filter(Product.id == product_id, Product.org_id == org_id).first()
    if not product:
        raise StockError("Product not found.")
    if int(quantity or 0) <= 0:
        raise StockError("Quantity must be at least 1.")
    quantity = int(quantity)
    if mrp is None:                    # not typed: the product's own MRP (or its list price + GST)
        mrp = product_default_mrp(product)
        if mrp is None:
            raise StockError("This product has no MRP yet. Type the MRP here, or set it once on the product (Sales > Products) so every lot inherits it.")
    if max_discount_percent is None:
        max_discount_percent = product.max_discount_percent or 0
    validate_fields(vendor_name=vendor_name, vendor_amount=vendor_amount, mrp=mrp, max_discount_percent=max_discount_percent,
                    inward_date=inward_date, manufacture_month=manufacture_month, expiry_date=expiry_date)
    if already_in_inventory:
        left = unpriced(db, org_id, product_id)
        if quantity > left:
            raise StockError(f"Only {left} unit(s) of {product.name} are in Inventory without rates; you entered {quantity}. "
                             f"Untick 'already in Inventory' to add new stock instead.")
        source = "priced_existing"
    # the lot's GST slab: typed, else the product's own
    cg = product.cgst_percent if cgst_percent is None else cgst_percent
    sg = product.sgst_percent if sgst_percent is None else sgst_percent
    if Decimal(cg or 0) < 0 or Decimal(sg or 0) < 0 or Decimal(cg or 0) + Decimal(sg or 0) > 100:
        raise StockError("CGST and SGST must be between 0 and 100 percent together.")
    batch = StockBatch(org_id=org_id, product_id=product_id, vendor_id=vendor_id or _vendor_id(db, org_id, vendor_name),
                       cgst_percent=q2(cg), sgst_percent=q2(sg), itc_eligible=bool(itc_eligible),
                       vendor_name=vendor_name.strip(), quantity_in=quantity, quantity_remaining=quantity,
                       vendor_amount=q2(vendor_amount), mrp=q2(mrp), max_discount_percent=q2(max_discount_percent),
                       inward_date=inward_date, manufacture_month=manufacture_month, expiry_date=expiry_date,
                       source=source, po_id=po_id, note=(note or "").strip() or None,
                       created_by=user.id if user else None)
    db.add(batch)
    db.flush()
    if count_stock and not already_in_inventory:
        receive_stock(db, org_id, product_id=str(product_id), qty=quantity, ref_type="stock_intake", ref_id=str(batch.id))
    return batch


def delete_batch(db: Session, org_id, batch: StockBatch):
    if batch.source == "purchase_order":
        raise StockError("A batch that came in through a purchase order cannot be deleted here.")
    if batch.quantity_remaining != batch.quantity_in:
        raise StockError("Part of this batch has already been used for a customer's work, so it cannot be deleted.")
    if batch.source != "priced_existing":
        product = db.get(Product, batch.product_id)
        try:
            issue_stock(db, org_id, str(batch.product_id), product.name if product else "product", batch.quantity_in,
                        ref_type="stock_intake_removed", ref_id=str(batch.id))
        except ValueError as e:
            raise StockError(str(e))
    db.delete(batch)


def available_batches(db: Session, org_id, product_id, on: date | None = None) -> list[StockBatch]:
    on = on or date.today()
    rows = (db.query(StockBatch).filter(StockBatch.org_id == org_id, StockBatch.product_id == product_id,
                                        StockBatch.quantity_remaining > 0).all())
    rows = [b for b in rows if not b.expiry_date or b.expiry_date >= on]
    rows.sort(key=lambda b: (b.expiry_date or date.max, b.inward_date, b.created_at or datetime.min))
    return rows


def available_qty(db: Session, org_id, product_id) -> int:
    return sum(b.quantity_remaining for b in available_batches(db, org_id, product_id))


def plan_issue(db: Session, org_id, product_id, qty: int) -> tuple[list[tuple[StockBatch, int]], int]:
    """First-expiry-first-out picks for `qty` units. Returns (picks, shortfall)."""
    need, picks = int(qty), []
    for b in available_batches(db, org_id, product_id):
        if need <= 0:
            break
        take = min(b.quantity_remaining, need)
        picks.append((b, take))
        need -= take
    return picks, max(need, 0)


def consume_best_effort(db: Session, org_id, product_id, qty: int):
    """Sales invoicing took `qty` out of the Inventory total: use up the same units from priced lots where we can."""
    picks, _ = plan_issue(db, org_id, product_id, qty)
    for b, take in picks:
        b.quantity_remaining -= take
        b.updated_at = datetime.utcnow()
    return picks


def batch_row(db: Session, b: StockBatch, product: Product | None = None, show_cost: bool = True) -> dict:
    product = product or db.get(Product, b.product_id)
    today = date.today()
    expired = bool(b.expiry_date and b.expiry_date < today)
    near = bool(b.expiry_date and not expired and (b.expiry_date - today).days <= 30)
    cost = q2(b.vendor_amount)
    mrp = q2(b.mrp)
    floor = q2(mrp * (Decimal(100) - Decimal(b.max_discount_percent or 0)) / 100)
    ms = gst.split_inclusive(mrp, b.cgst_percent, b.sgst_percent)        # MSP + CGST + SGST = MRP
    fs = gst.split_inclusive(floor, b.cgst_percent, b.sgst_percent)
    row = {
        "cgst_percent": q2(b.cgst_percent), "sgst_percent": q2(b.sgst_percent), "itc_eligible": bool(b.itc_eligible),
        "msp": ms["base"], "mrp_cgst": ms["cgst"], "mrp_sgst": ms["sgst"],
        "lowest_selling_price_excl_gst": fs["base"],
        "id": b.id, "product_id": b.product_id, "product_name": product.name if product else None,
        "sku": product.sku if product else None, "quantity_in": b.quantity_in, "quantity_remaining": b.quantity_remaining,
        "mrp": mrp, "max_discount_percent": q2(b.max_discount_percent), "lowest_selling_price": floor,
        "inward_date": b.inward_date, "manufacture_month": b.manufacture_month, "expiry_date": b.expiry_date,
        "expired": expired, "expiring_soon": near, "source": b.source, "po_id": b.po_id, "note": b.note,
        "created_at": b.created_at,
    }
    if show_cost:
        paid = gst.add_exclusive(cost, b.cgst_percent, b.sgst_percent)     # what we really paid per unit
        row.update({"vendor_name": b.vendor_name, "vendor_amount": cost,
                    "vendor_cgst": paid["cgst"], "vendor_sgst": paid["sgst"], "vendor_total_paid": paid["total"],
                    "sold_below_cost_warning": fs["base"] < cost})
    return row


def batch_from_po(db: Session, org_id, user, po, item) -> StockBatch:
    """A good Purchase Order receipt also records its lot (stock was already added by the caller). The selling side (MRP incl. GST and
    max discount) is inherited from the product master, so nothing has to be typed in Stock Intake afterwards. Only when the product has
    neither an MRP nor a list price does the lot start at its cost with 0% discount, and the note says so."""
    product = db.get(Product, item.product_id)
    cost = q2(item.unit_price)
    mrp = product_default_mrp(product)
    from_master = mrp is not None
    if mrp is None:
        mrp = max(cost, TWO)
    b = StockBatch(org_id=org_id, product_id=item.product_id, vendor_id=po.vendor_id,
                   vendor_name=po.vendor.name if po.vendor else "Vendor", quantity_in=item.qty, quantity_remaining=item.qty,
                   cgst_percent=q2(item.cgst_percent), sgst_percent=q2(item.sgst_percent),
                   vendor_amount=cost, mrp=mrp, max_discount_percent=q2(product.max_discount_percent if product else 0), inward_date=date.today(),
                   source="purchase_order", po_id=po.id, created_by=user.id if user else None,
                   note=(f"Received against {po.po_number}" if po.po_number else "Received against a purchase order")
                        + ("" if from_master else ". The product has no MRP set: set it on the product (Sales > Products) or edit this lot."))
    db.add(b)
    db.flush()
    return b
