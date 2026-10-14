"""
Builds the tax invoice document (see invoice_pdf.render_invoice) from live records, for BOTH kinds of sale:
  - a direct Sales order: its Sales invoice, sales-order lines, and the Finance payments against the invoice;
  - a Workpage work: the work's items and amounts, and the payments recorded on the work.
One number series (INV-0001 ...) covers both. Vendor prices never reach the document.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.models.finance import Payment, Refund
from app.models.organization import Organization, OrganizationProfile
from app.models.sales import Customer, Invoice, Product, SalesOrder, SalesOrderItem
from app.models.workpage import WorkOrder
from app.services import gst, invoice_pdf


class InvoiceError(Exception):
    pass


def next_invoice_number(db: Session, org_id) -> str:
    """INV-0001, 0002 ... per organization across Sales invoices and work invoices. The org row is locked so two
    simultaneous invoices cannot share a number."""
    db.query(Organization).filter(Organization.id == org_id).with_for_update().first()
    n = (db.query(func.count(Invoice.id)).filter(Invoice.org_id == org_id).scalar() or 0) + \
        (db.query(func.count(WorkOrder.id)).filter(WorkOrder.org_id == org_id, WorkOrder.invoice_number.isnot(None)).scalar() or 0)
    while True:
        n += 1
        number = f"INV-{n:04d}"
        if not db.query(Invoice.id).filter(Invoice.org_id == org_id, Invoice.invoice_number == number).first() and \
           not db.query(WorkOrder.id).filter(WorkOrder.org_id == org_id, WorkOrder.invoice_number == number).first():
            return number


def _company(db: Session, org_id) -> dict:
    org = db.query(Organization).filter(Organization.id == org_id).first()
    profile = db.query(OrganizationProfile).filter(OrganizationProfile.org_id == org_id).first()
    return invoice_pdf.company_block(org, profile)


def _refund_rows(db: Session, work_id) -> list[dict]:
    return [{"date": r.refund_date, "method": r.method, "reference": r.transaction_id, "amount": r.refund_amount, "charge": r.charge_amount}
            for r in db.query(Refund).filter(Refund.work_id == work_id, Refund.status == "completed").order_by(Refund.completed_at)]


# ------------------------------------------------------------- Sales order
def sales_invoice_pdf(db: Session, org_id, inv: Invoice) -> bytes:
    payments = db.query(Payment).filter(Payment.invoice_id == inv.id).order_by(Payment.created_at).all()
    if not payments:
        raise InvoiceError("The tax invoice is issued once a payment has been recorded against this invoice. Record the payment in Finance first.")
    order = (db.query(SalesOrder).options(joinedload(SalesOrder.items).joinedload(SalesOrderItem.product))
             .filter(SalesOrder.id == inv.order_id, SalesOrder.org_id == org_id).first())
    customer = db.query(Customer).filter(Customer.id == inv.customer_id, Customer.org_id == org_id).first()
    lines = []
    for it in order.items:
        taxable, cg, sg = gst.line_tax(it.qty, it.unit_price, it.cgst_percent, it.sgst_percent)
        lines.append({"name": it.product.name if it.product else "Item", "hsn": it.product.hsn_code if it.product else None, "qty": it.qty,
                      "rate": Decimal(it.unit_price), "taxable": taxable, "cgst_percent": it.cgst_percent, "sgst_percent": it.sgst_percent,
                      "cgst": cg, "sgst": sg, "total": taxable + cg + sg})
    paid = gst.q2(sum((Decimal(p.amount) for p in payments), Decimal(0)))
    total = gst.q2(inv.amount)
    work = db.query(WorkOrder).filter(WorkOrder.org_id == org_id, WorkOrder.sales_order_id == inv.order_id, WorkOrder.work_type == "sales_order").first()
    cancelled = inv.status == "cancelled"
    when = inv.created_at.date() if inv.created_at else order.order_date
    doc = {"company": _company(db, org_id), "number": inv.invoice_number or f"INV-{str(inv.id)[:8].upper()}", "date": when, "order_date": order.order_date,
           "status": "CANCELLED" if cancelled else ("PAID" if paid >= total else "PART PAID"),
           "customer": {"name": customer.name, "address": customer.billing_address, "gstin": customer.gst_number},
           "lines": lines, "discount": None, "gross": total, "taxable": gst.q2(inv.subtotal), "cgst": gst.q2(inv.cgst_amount), "sgst": gst.q2(inv.sgst_amount),
           "total": total, "paid": paid, "balance": Decimal(0) if cancelled else max(total - paid, Decimal(0)),
           "payments": [{"date": p.date, "method": p.method, "reference": p.transaction_id, "amount": p.amount} for p in payments],
           "refunds": _refund_rows(db, work.id) if work else [],
           "notes": ["This invoice was cancelled and a credit note issued; see the refund below."] if cancelled else []}
    return invoice_pdf.render_invoice(doc)


# ------------------------------------------------------------------ work
def work_invoice_pdf(db: Session, w: WorkOrder) -> bytes:
    """Tax invoice of a Workpage work. Needs a payment; the number is given on first generation and never changes."""
    from app.services import workpages as wp
    if wp.is_sales_order(w):
        inv = wp.sales_invoice(db, w)
        if inv is None:
            raise InvoiceError("The invoice of this Sales order has not been generated in Sales yet.")
        return sales_invoice_pdf(db, w.org_id, inv)
    payments = list(w.payments)
    if not payments:
        raise InvoiceError("The tax invoice is issued once a payment has been recorded on this work.")
    if not w.invoice_number:
        w.invoice_number = next_invoice_number(db, w.org_id)
        w.invoiced_on = date.today()
        wp.log_event(db, w, "invoice", f"Tax invoice {w.invoice_number} generated", "Issued after the first payment was recorded.", None)
        db.flush()
    taxable_net, (cg_amt, sg_amt), net = wp.taxable_net(w), wp.gst_amounts(w), wp.net_payable(w)
    cg_p, sg_p = Decimal(w.cgst_percent or 0), Decimal(w.sgst_percent or 0)
    # What is being sold: the listed items, priced from the quotation amount in proportion to their max selling price (MSP, excl. GST)
    items = wp._items(db, w)
    issues = {}
    for i in wp._all_issues(db, w):
        if i.batch_id and Decimal(i.mrp or 0) > 0:
            issues.setdefault(i.product_id, []).append(i)
    weighted = []
    for it in items:
        prod = db.get(Product, it.product_id)
        if it.product_id in issues:
            wt = sum((Decimal(i.qty) * gst.split_inclusive(i.mrp, i.cgst_percent, i.sgst_percent)["base"] for i in issues[it.product_id]), Decimal(0))
        else:
            wt = Decimal(it.qty) * Decimal(prod.unit_price or 0) if prod else Decimal(0)
        weighted.append((it, prod, wt))
    list_total = gst.q2(w.quotation_amount)
    if weighted and sum(x[2] for x in weighted) <= 0:
        weighted = [(it, prod, Decimal(it.qty)) for it, prod, _ in weighted]
    lines, left, wsum = [], list_total, sum((x[2] for x in weighted), Decimal(0))
    for idx, (it, prod, wt) in enumerate(weighted):
        amount = left if idx == len(weighted) - 1 else gst.q2(list_total * wt / wsum)
        left -= amount
        cg, sg = gst.q2(amount * cg_p / 100), gst.q2(amount * sg_p / 100)
        lines.append({"name": prod.name if prod else "Item", "hsn": prod.hsn_code if prod else None, "qty": it.qty, "rate": gst.q2(amount / it.qty) if it.qty else amount,
                      "taxable": amount, "cgst_percent": cg_p, "sgst_percent": sg_p, "cgst": cg, "sgst": sg, "total": amount + cg + sg})
    if not lines:
        cg, sg = gst.q2(list_total * cg_p / 100), gst.q2(list_total * sg_p / 100)
        lines.append({"name": (w.description or "Supply as per quotation"), "hsn": None, "qty": 1, "rate": list_total, "taxable": list_total,
                      "cgst_percent": cg_p, "sgst_percent": sg_p, "cgst": cg, "sgst": sg, "total": list_total + cg + sg})
    gross = sum((ln["total"] for ln in lines), Decimal(0))
    disc_pct = Decimal(w.discount_percent or 0)
    discount = {"percent": disc_pct, "amount": gst.q2(gross - net)} if disc_pct > 0 else None
    cust = db.get(Customer, w.customer_id) if w.customer_id else None
    details = (cust.billing_address if cust and cust.billing_address else (w.client_details or ""))
    if w.client_mobile and w.client_mobile not in details:
        details = (details + "\n" if details else "") + f"Mobile: {w.client_mobile}"
    paid = wp.received_amount(w)
    cancelled = w.status == "cancelled"
    doc = {"company": _company(db, w.org_id), "number": w.invoice_number, "date": w.invoiced_on or date.today(), "order_date": w.created_at.date() if w.created_at else None,
           "status": "CANCELLED" if cancelled else ("PAID" if paid >= net else "PART PAID"),
           "customer": {"name": cust.name if cust else w.client_name, "address": details, "gstin": cust.gst_number if cust else None},
           "lines": lines, "discount": discount, "gross": gst.q2(gross), "taxable": taxable_net, "cgst": cg_amt, "sgst": sg_amt, "total": net,
           "paid": paid, "balance": Decimal(0) if cancelled else max(net - paid, Decimal(0)),
           "payments": [{"date": p.paid_on, "method": p.method, "reference": p.transaction_id, "amount": p.amount} for p in payments],
           "refunds": _refund_rows(db, w.id),
           "notes": ["This work was cancelled; see the refund below."] if cancelled else []}
    return invoice_pdf.render_invoice(doc)
