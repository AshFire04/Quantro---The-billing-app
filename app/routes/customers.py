from flask import Blueprint, g, jsonify, render_template, request

from ..auth import login_required
from ..db import get_db
from ..services.customers import find_by_phone

bp = Blueprint("customers", __name__)


@bp.route("/customers")
@login_required
def index():
    q = request.args.get("q", "").strip()
    sql = ("SELECT c.*, COUNT(b.id) AS bill_count, COALESCE(SUM(b.total), 0) AS spent, "
           "MAX(b.created_at) AS last_bill FROM customers c "
           "LEFT JOIN bills b ON b.customer_id = c.id AND b.status = 'Saved' "
           "WHERE c.shop_id = ?")
    params = [g.shop["id"]]
    if q:
        sql += " AND (c.name LIKE ? OR c.phone LIKE ? OR c.location LIKE ?)"
        params += [f"%{q}%"] * 3
    sql += " GROUP BY c.id ORDER BY c.name COLLATE NOCASE"
    db = get_db()
    has_any = db.execute("SELECT 1 FROM customers WHERE shop_id = ?",
                         (g.shop["id"],)).fetchone() is not None
    return render_template("customers.html", customers=db.execute(sql, params).fetchall(),
                           q=q, has_any=has_any)


@bp.route("/customers/lookup")
@login_required
def lookup():
    """Used by the Billing screen: a saved customer found by phone number only."""
    found = find_by_phone(get_db(), g.shop["id"], request.args.get("phone", ""))
    if found is None:
        return jsonify(found=False)
    return jsonify(found=True, name=found["name"], location=found["location"],
                   customer_type=found["customer_type"])
