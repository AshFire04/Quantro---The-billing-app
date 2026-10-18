"""The GST breakdown printed on a bill. Plain Python, read-only.

The selling price is what the customer pays, and GST never changes it. GST is a percentage of
the amount charged for the line (its "net": after item offers and its share of the whole-bill
discount). Money is whole paise.

Order: the whole-bill discount (and bill offers) is shared over the lines in proportion to each
line's amount after its own discount, any leftover paisa going on the last line. Then, per line,
    GST = net x rate / 100, rounded half up to the paisa,   amount after GST = net - GST.
The total GST is the sum of the rounded line figures, so the printed numbers add up exactly.
Shipping & handling carries no GST, and the rupee round-off never touches these figures.
"""
from decimal import Decimal


def hundredths(rate):
    return int((Decimal(str(rate or 0)) * 100).to_integral_value())


def line_gst(net, rate):
    """GST on the amount charged for a line: net x rate / 100, rounded half up to the paisa."""
    h = hundredths(rate)
    if h <= 0 or net <= 0:
        return 0
    return (net * h * 2 + 10000) // 20000


def share_out(amounts, discount):
    """Split `discount` over `amounts` in proportion; the last line takes what is left."""
    total = sum(amounts)
    if discount <= 0 or total <= 0:
        return [0] * len(amounts)
    shares = [(discount * a * 2 + total) // (2 * total) for a in amounts[:-1]]
    return shares + [discount - sum(shares)]


def breakdown(lines, whole_discount):
    """lines: rows with line_amount and gst_rate (paise, percent). Returns (per-line, summary).

    per-line: [{"net", "gst", "rate"}]. summary: {"show", "gst", "excl", "by_rate"}, where
    `show` is False when every rate is 0 (or the bill is an older one with no GST saved).
    """
    amounts = [l["line_amount"] for l in lines]
    nets = [a - s for a, s in zip(amounts, share_out(amounts, whole_discount))]
    rates = [float(l["gst_rate"] or 0) for l in lines]
    gsts = [line_gst(n, r) for n, r in zip(nets, rates)]
    by_rate = {}
    for r, g in zip(rates, gsts):
        if r > 0:
            by_rate[r] = by_rate.get(r, 0) + g
    total_gst = sum(gsts)
    return ([{"net": n, "gst": g, "rate": r} for n, g, r in zip(nets, gsts, rates)],
            {"show": any(r > 0 for r in rates), "gst": total_gst,
             "excl": sum(nets) - total_gst, "by_rate": sorted(by_rate.items())})
