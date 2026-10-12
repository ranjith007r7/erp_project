"""
The MRP / max-discount rule, in one place, used by Workpage (when stock is taken,
when the amount or discount is edited, when a payment is recorded) and by Finance
(which lists any work that breaks it).

For stock a work took from inventory, every issued line carries the MRP and the
max discount % of the batch it came from. Over the whole bill:

    ceiling = sum(qty x MRP)                        the customer can never be charged more than MRP
    floor   = sum(qty x MRP x (1 - max_discount%))  and never less than MRP less the allowed discount

so   quotation_amount <= ceiling   and   net_payable (after the work's discount %) >= floor.
Works that took no stock from inventory (bought through a purchase order) have no
such limits and always pass.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

TWO = Decimal("0.01")


def q2(v) -> Decimal:
    return Decimal(v or 0).quantize(TWO, rounding=ROUND_HALF_UP)


def limits(lines) -> dict | None:
    """lines: iterable of (qty, mrp, max_discount_percent). None when there are no lines."""
    lines = list(lines)
    if not lines:
        return None
    ceiling = sum((Decimal(q) * Decimal(m) for q, m, _ in lines), Decimal(0))
    floor = sum((Decimal(q) * Decimal(m) * (Decimal(100) - Decimal(d)) / 100 for q, m, d in lines), Decimal(0))
    allowed_pct = (Decimal(100) * (ceiling - floor) / ceiling) if ceiling else Decimal(0)
    return {"ceiling": q2(ceiling), "floor": q2(floor), "max_discount_percent": q2(allowed_pct)}


def violations(quotation_amount, discount_percent, lines) -> list[str]:
    lines = list(lines)
    lim = limits(lines)
    if not lim:
        return []
    # "26000.00 = 5 x 4000.00 + 1 x 6000.00": stock from different lots can carry different MRPs
    groups: dict = {}
    for q, m, _ in lines:
        groups[q2(m)] = groups.get(q2(m), 0) + int(q)
    parts = " + ".join(f"{n} x {m}" for m, n in sorted(groups.items()))
    quote = Decimal(quotation_amount or 0)
    net = quote - quote * Decimal(discount_percent or 0) / 100
    out = []
    if q2(quote) > lim["ceiling"]:
        out.append(f"The quotation amount {q2(quote)} is above the MRP total of the stock taken ({lim['ceiling']} = {parts}); a customer cannot be charged more than MRP."
                   + (" The units come from lots with different MRPs. If the older units really carry the new MRP, correct that lot's MRP in Stock Intake; otherwise lower the quotation." if len(groups) > 1 else ""))
    if q2(net) < lim["floor"]:
        out.append(f"After the {q2(discount_percent)}% discount the customer would pay {q2(net)}, which is below the lowest allowed price "
                   f"{lim['floor']} (MRP less the maximum discount of {lim['max_discount_percent']}% on this stock).")
    return out
