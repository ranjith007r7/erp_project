"""
The MRP / max-discount rule, in one place, used by Workpage (when stock is taken,
when the amount or discount is edited, when a payment is recorded) and by Finance
(which lists any work that breaks it).

For stock a work took from inventory, every issued line carries the MRP and the
max discount % of the batch it came from. Over the whole bill:

    ceiling = sum(qty x MRP)                        the customer can never be charged more than MRP
    floor   = sum(qty x MRP x (1 - max_discount%))  and never less than MRP less the allowed discount

so   quotation_amount <= ceiling   and   net_payable (after the work's discount %) >= floor,
BOTH SIDES GST-INCLUSIVE. MRP is printed GST-inclusive, so it splits as  MSP (max selling price excl. GST) + CGST + SGST = MRP.
The amount typed on a work is the price excluding GST; with the lots' GST slab added it is compared with the MRP total.
(60000 MRP at 10% + 10% = MSP 50000 + 5000 + 5000: a work can be quoted at most 50000 excl. GST.)
Works that took no stock from inventory (bought through a purchase order) have no
such limits and always pass.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

TWO = Decimal("0.01")


def q2(v) -> Decimal:
    return Decimal(v or 0).quantize(TWO, rounding=ROUND_HALF_UP)


def _norm(lines):
    """Accept (qty, mrp, max_disc) or (qty, mrp, max_disc, cgst, sgst)."""
    out = []
    for l in lines:
        q, m, d = l[0], l[1], l[2]
        c, s_ = (l[3], l[4]) if len(l) >= 5 else (0, 0)
        out.append((int(q), Decimal(m), Decimal(d or 0), Decimal(c or 0), Decimal(s_ or 0)))
    return out


def _excl(amount: Decimal, c: Decimal, s_: Decimal) -> Decimal:
    return amount * 100 / (100 + c + s_)


def effective_gst(lines) -> tuple[Decimal, Decimal]:
    """One CGST / SGST % for a bill made of lots with different slabs: weighted by each line's MRP value."""
    ls = _norm(lines)
    w = sum((q * m for q, m, *_ in ls), Decimal(0))
    if not w:
        return Decimal(0), Decimal(0)
    return (q2(sum((q * m * c for q, m, d, c, s_ in ls), Decimal(0)) / w),
            q2(sum((q * m * s_ for q, m, d, c, s_ in ls), Decimal(0)) / w))


def limits(lines) -> dict | None:
    """lines: iterable of (qty, mrp, max_discount_percent[, cgst, sgst]). None when there are no lines.
    ceiling / floor are GST-inclusive (MRP is); the *_excl_gst figures are the same limits as a price before GST."""
    ls = _norm(lines)
    if not ls:
        return None
    ceiling = sum((q * m for q, m, d, c, s_ in ls), Decimal(0))
    floor = sum((q * m * (Decimal(100) - d) / 100 for q, m, d, c, s_ in ls), Decimal(0))
    ceiling_x = sum((q * _excl(m, c, s_) for q, m, d, c, s_ in ls), Decimal(0))
    floor_x = sum((q * _excl(m * (Decimal(100) - d) / 100, c, s_) for q, m, d, c, s_ in ls), Decimal(0))
    allowed_pct = (Decimal(100) * (ceiling - floor) / ceiling) if ceiling else Decimal(0)
    cg, sg = effective_gst(ls)
    return {"ceiling": q2(ceiling), "floor": q2(floor), "max_discount_percent": q2(allowed_pct),
            "ceiling_excl_gst": q2(ceiling_x), "floor_excl_gst": q2(floor_x), "cgst_percent": cg, "sgst_percent": sg}


def violations(quotation_amount, discount_percent, lines, fallback_gst=(0, 0)) -> list[str]:
    """quotation_amount is the price EXCLUDING GST (what is typed on the work). The GST slab comes from the lots;
    only when the lots carry none (older stock) the work's own rates (fallback_gst) are used."""
    lines = _norm(lines)
    lim = limits(lines)
    if not lim:
        return []
    cg, sg = lim["cgst_percent"], lim["sgst_percent"]
    if not (cg or sg):
        cg, sg = Decimal(fallback_gst[0] or 0), Decimal(fallback_gst[1] or 0)
    g = (100 + cg + sg) / 100
    # "26000.00 = 5 x 4000.00 + 1 x 6000.00": stock from different lots can carry different MRPs
    groups: dict = {}
    for q, m, *_ in lines:
        groups[q2(m)] = groups.get(q2(m), 0) + int(q)
    parts = " + ".join(f"{n} x {m}" for m, n in sorted(groups.items()))
    quote = Decimal(quotation_amount or 0)
    net = quote - quote * Decimal(discount_percent or 0) / 100
    quote_gross, net_gross = quote * g, net * g
    out = []
    mrp_note = (f"MRP total {lim['ceiling']} = {parts}; excluding GST that is {lim['ceiling_excl_gst']} + GST {q2(lim['ceiling'] - lim['ceiling_excl_gst'])}"
                if (cg or sg) else f"MRP total {lim['ceiling']} = {parts}")
    if q2(quote_gross) > lim["ceiling"]:
        out.append(f"The quotation amount {q2(quote)} + GST {q2(quote_gross - quote)} = {q2(quote_gross)} (GST included) is above the {mrp_note}; "
                   f"a customer cannot be charged more than MRP. The most this work can be quoted before GST is {lim['ceiling_excl_gst'] if (cg or sg) else lim['ceiling']}."
                   + (" The units come from lots with different MRPs. If the older units really carry the new MRP, correct that lot's MRP in Stock Intake; otherwise lower the quotation." if len(groups) > 1 else ""))
    if q2(net_gross) < lim["floor"]:
        out.append(f"After the {q2(discount_percent)}% discount the customer would pay {q2(net)} + GST {q2(net_gross - net)} = {q2(net_gross)} (GST included), "
                   f"which is below the lowest allowed price {lim['floor']} (MRP less the maximum discount of {lim['max_discount_percent']}% on this stock"
                   + (f"; {lim['floor_excl_gst']} before GST" if (cg or sg) else "") + ").")
    return out
