"""The figures on the Home page. Plain Python, read-only, and always for one shop.

Cancelled bills never count as sales. Money is whole paise, like everywhere else.
"""
from datetime import date, timedelta

MAX_PIE_SLICES = 5          # more categories than this are grouped as "Other categories"


def pie_slices(pairs):
    """[(label, value), ...] -> [{label, value, pct, color}, ...] for the biggest first.

    Zero-value entries are dropped; extra small ones are grouped so a pie stays readable.
    """
    pairs = sorted((p for p in pairs if p[1] > 0), key=lambda p: -p[1])
    if len(pairs) > MAX_PIE_SLICES:
        rest = sum(v for _, v in pairs[MAX_PIE_SLICES - 1:])
        pairs = pairs[:MAX_PIE_SLICES - 1] + [("Other categories", rest)]
    total = sum(v for _, v in pairs)
    return [{"label": label, "value": value, "pct": value * 100 / total, "color": i}
            for i, (label, value) in enumerate(pairs)]


def target_progress(sold, target):
    """How far the month's sales are towards the owner's target. None if no target is set."""
    if target <= 0:
        return None
    return {"sold": sold, "target": target, "left": max(target - sold, 0),
            "pct": min(sold * 100 / target, 100), "reached": sold >= target}


def home_figures(db, shop_id, today=None):
    today = today or date.today()
    day = today.isoformat()
    month_start = today.replace(day=1).isoformat()

    def sales_between(start, end):
        """Total of saved bills dated from start to end (both inclusive, 'YYYY-MM-DD')."""
        return db.execute(
            "SELECT COALESCE(SUM(total), 0) FROM bills WHERE shop_id = ? AND status != 'Cancelled' "
            "AND substr(created_at, 1, 10) BETWEEN ? AND ?", (shop_id, start, end)).fetchone()[0]

    bills_today = db.execute(
        "SELECT COUNT(*) FROM bills WHERE shop_id = ? AND status != 'Cancelled' "
        "AND substr(created_at, 1, 10) = ?", (shop_id, day)).fetchone()[0]
    due = db.execute(
        "SELECT COALESCE(SUM(due_amount), 0), COUNT(*) FROM bills "
        "WHERE shop_id = ? AND status != 'Cancelled' AND due_amount > 0", (shop_id,)).fetchone()

    week = []
    for back in range(6, -1, -1):
        d = today - timedelta(days=back)
        week.append({"label": "Today" if back == 0 else d.strftime("%a"),
                     "amount": sales_between(d.isoformat(), d.isoformat())})
    peak = max(w["amount"] for w in week)
    for w in week:
        w["height"] = round(w["amount"] * 100 / peak) if peak else 0

    running_low = db.execute(
        "SELECT name, stock, low_stock_level FROM products WHERE shop_id = ? AND active = 1 "
        "AND stock <= low_stock_level ORDER BY stock * 1.0 / MAX(low_stock_level, 1), name",
        (shop_id,)).fetchall()

    categories = db.execute(
        "SELECT CASE WHEN category = '' THEN 'No category' ELSE category END AS label, "
        "SUM(price * stock) AS value FROM products WHERE shop_id = ? AND active = 1 "
        "GROUP BY label", (shop_id,)).fetchall()

    target = db.execute("SELECT monthly_target FROM shops WHERE id = ?", (shop_id,)).fetchone()[0]
    return {
        "today_sales": sales_between(day, day),
        "bills_today": bills_today,
        "low_count": len(running_low),
        "running_low": running_low[:5],
        "pending_amount": due[0],
        "pending_customers": due[1],
        "week": week,
        "month_name": today.strftime("%B"),
        "target": target_progress(sales_between(month_start, day), target),
        "categories": pie_slices([(r["label"], r["value"]) for r in categories]),
        "recent": db.execute(
            "SELECT b.*, (SELECT COUNT(*) FROM bill_lines WHERE bill_id = b.id) AS item_count "
            "FROM bills b WHERE b.shop_id = ? ORDER BY b.id DESC LIMIT 5", (shop_id,)).fetchall(),
    }
