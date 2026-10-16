"""Profit: what was earned on the items sold. Plain Python, read-only, one shop at a time.

Only saved bills count (cancelled ones never do). Profit on an item is what it sold for minus
what it cost. Two rules keep it honest:

* A whole-bill discount is shared out over the items in proportion to their amounts, so the
  profit is what the shop really earned. Shipping & handling and the rupee round-off are left out.
* The cost is the one copied onto the bill when it was made. Older bills have none copied, so
  the product's cost price today is used. Items with no cost price anywhere can't have a profit
  worked out; they are listed, and counted apart, rather than guessed at.
"""


def share(amount, part, whole):
    """amount x part / whole, in whole paise, rounded half up (whole of 0 gives amount back)."""
    if whole <= 0:
        return amount
    return (amount * part * 2 + whole) // (whole * 2)


def profit_figures(db, shop_id, start="", end=""):
    """Per product and overall profit for bills dated start..end ('YYYY-MM-DD', blank = no limit)."""
    sql = ("SELECT l.bill_id, l.product_id, l.name, l.code, l.quantity, l.line_amount, "
           "CASE WHEN l.cost > 0 THEN l.cost ELSE COALESCE(p.cost_price, 0) END AS unit_cost, "
           "b.total, b.shipping, b.round_off "
           "FROM bill_lines l JOIN bills b ON b.id = l.bill_id "
           "LEFT JOIN products p ON p.id = l.product_id "
           "WHERE b.shop_id = ? AND b.status = 'Saved'")
    params = [shop_id]
    if start:
        sql += " AND substr(b.created_at, 1, 10) >= ?"
        params.append(start)
    if end:
        sql += " AND substr(b.created_at, 1, 10) <= ?"
        params.append(end)
    lines = db.execute(sql, params).fetchall()

    subtotal = {}
    for l in lines:
        subtotal[l["bill_id"]] = subtotal.get(l["bill_id"], 0) + l["line_amount"]

    sold = {}                                   # product id -> figures from its sales
    for l in lines:
        b = l["bill_id"]
        after_whole = l["total"] - l["shipping"] - l["round_off"]
        earned = share(l["line_amount"], after_whole, subtotal[b])
        s = sold.setdefault(l["product_id"], {"qty": 0, "revenue": 0, "cost": 0,
                                              "unknown_revenue": 0, "name": l["name"],
                                              "code": l["code"]})
        s["qty"] += l["quantity"]
        if l["unit_cost"] > 0:
            s["revenue"] += earned
            s["cost"] += l["unit_cost"] * l["quantity"]
        else:
            s["unknown_revenue"] += earned

    rows = []
    products = db.execute("SELECT * FROM products WHERE shop_id = ? AND active = 1 "
                          "ORDER BY name COLLATE NOCASE", (shop_id,)).fetchall()
    listed = set()
    for p in products:
        listed.add(p["id"])
        s = sold.get(p["id"], {"qty": 0, "revenue": 0, "cost": 0, "unknown_revenue": 0})
        rows.append(make_row(p["id"], p["name"], p["code"], p["supplier"], p["cost_price"],
                             p["price"], s))
    for product_id, s in sold.items():          # removed from Inventory since, but sold
        if product_id not in listed:
            rows.append(make_row(product_id, s["name"], s["code"], "", 0, 0, s, removed=True))

    rows.sort(key=lambda r: (-r["profit"], r["name"].lower()))
    revenue = sum(r["revenue"] for r in rows)
    cost = sum(r["cost"] for r in rows)
    return {
        "rows": rows,
        "revenue": revenue, "cost": cost, "profit": revenue - cost,
        "margin": (revenue - cost) * 100 / revenue if revenue else None,
        "unknown_revenue": sum(r["unknown_revenue"] for r in rows),
        "no_cost_count": sum(1 for r in rows if r["qty"] and r["unknown_revenue"]),
        "missing_cost_products": sum(1 for r in rows if not r["cost_price"] and not r["removed"]),
    }


def make_row(product_id, name, code, supplier, cost_price, price, s, removed=False):
    profit = s["revenue"] - s["cost"]
    return {
        "id": product_id, "name": name, "code": code or "", "supplier": supplier or "",
        "cost_price": cost_price, "price": price, "removed": removed,
        "per_item": price - cost_price if cost_price and not removed else None,
        "qty": s["qty"], "revenue": s["revenue"], "cost": s["cost"], "profit": profit,
        "margin": profit * 100 / s["revenue"] if s["revenue"] else None,
        "unknown_revenue": s["unknown_revenue"],
    }
