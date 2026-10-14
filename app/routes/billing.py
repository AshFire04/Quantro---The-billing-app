from flask import Blueprint, g, jsonify, render_template, request, url_for

from ..auth import login_required
from ..db import get_db
from ..services.billing import (BillError, ORDER_SOURCES, PAYMENT_MODES,
                                save_bill)

bp = Blueprint("billing", __name__)


@bp.route("/billing")
@login_required
def index():
    products = [dict(p) for p in get_db().execute(
        "SELECT id, code, name, category, price, stock FROM products "
        "WHERE shop_id = ? AND active = 1 ORDER BY name COLLATE NOCASE",
        (g.shop["id"],)).fetchall()]
    next_number = g.shop["next_invoice_number"]
    return render_template("billing.html", products=products, next_number=next_number,
                           payment_modes=PAYMENT_MODES, order_sources=ORDER_SOURCES)


@bp.route("/billing/save", methods=("POST",))
@login_required
def save():
    data = request.get_json(silent=True) or {}
    try:
        bill_id = save_bill(get_db(), g.shop["id"], data.get("items", []),
                            customer_name=str(data.get("customer", "")),
                            customer_phone=str(data.get("phone", "")),
                            place_of_sale=str(data.get("place_of_sale", "")),
                            order_source=str(data.get("order_source", "")),
                            order_source_other=str(data.get("order_source_other", "")),
                            payments=data.get("payments"),
                            customer_location=str(data.get("location", "")),
                            due_amount=str(data.get("due_amount", "")),
                            due_date=str(data.get("due_date", "")))
    except BillError as e:
        return jsonify(error=str(e)), 400
    return jsonify(url=url_for("bills.view", bill_id=bill_id, saved=1))
