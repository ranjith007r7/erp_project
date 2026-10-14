"""
GST arithmetic, in one place. Prices everywhere in the system are EXCLUSIVE of GST; CGST and SGST are percentages
of the taxable value (qty x unit price), each rounded to paise per line. Intra-state supply only (CGST + SGST), as specified.
"""
from decimal import Decimal, ROUND_HALF_UP

ZERO = Decimal("0.00")


def q2(v) -> Decimal:
    return Decimal(v or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def pct(v) -> Decimal:
    return Decimal(v or 0)


def line_tax(qty, unit_price, cgst_percent, sgst_percent) -> tuple[Decimal, Decimal, Decimal]:
    """(taxable value, CGST amount, SGST amount) of one line."""
    taxable = q2(Decimal(qty) * Decimal(unit_price or 0))
    return taxable, q2(taxable * pct(cgst_percent) / 100), q2(taxable * pct(sgst_percent) / 100)


def summarize(lines) -> dict:
    """lines: iterable of (qty, unit_price, cgst_percent, sgst_percent) -> subtotal, cgst, sgst, total."""
    sub = cg = sg = ZERO
    for qty, price, c, s in lines:
        t, ca, sa = line_tax(qty, price, c, s)
        sub, cg, sg = sub + t, cg + ca, sg + sa
    return {"subtotal": sub, "cgst": cg, "sgst": sg, "total": sub + cg + sg}


def item_lines(items):
    return [(i.qty, i.unit_price, i.cgst_percent, i.sgst_percent) for i in items]


def set_po_totals(po) -> None:
    """po.total stays the taxable value (it is the cost basis everything else reads); GST and the payable total sit beside it."""
    t = summarize(item_lines(po.items))
    po.total, po.cgst_amount, po.sgst_amount, po.grand_total = t["subtotal"], t["cgst"], t["sgst"], t["total"]


def split_inclusive(amount, cgst_percent, sgst_percent) -> dict:
    """GST-inclusive amount (an MRP, a total paid) -> base + CGST + SGST that add back EXACTLY to the amount.
    60000 at 10% + 10% -> 50000 + 5000 + 5000."""
    amount = q2(amount)
    c, s = pct(cgst_percent), pct(sgst_percent)
    base = q2(amount * 100 / (100 + c + s))
    cg = q2(base * c / 100)
    return {"base": base, "cgst": cg, "sgst": amount - base - cg, "total": amount}


def add_exclusive(base, cgst_percent, sgst_percent) -> dict:
    """GST-exclusive base (a vendor rate) -> the same split with GST added on top: 50000 -> 50000 + 5000 + 5000 = 60000."""
    base = q2(base)
    cg, sg = q2(base * pct(cgst_percent) / 100), q2(base * pct(sgst_percent) / 100)
    return {"base": base, "cgst": cg, "sgst": sg, "total": base + cg + sg}
