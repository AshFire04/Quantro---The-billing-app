from flask import (Blueprint, flash, g, jsonify, redirect, render_template, request,
                   url_for)

from ..auth import login_required
from ..db import get_db
from datetime import date

from ..services.billing import (BillError, CUSTOMER_TYPES, next_bill_label, ORDER_SOURCES, PAYMENT_MODES,
                                save_bill)
from ..services.states import DEFAULT_PLACE, PLACES
from ..services.money import paise_to_input

bp = Blueprint("billing", __name__)


def active_offers():
    """The shop's switched-on offers, in the shape the Billing screen needs."""
    return [{"id": o["id"], "name": o["name"], "pct": o["percentage"],
             "applies_to": o["applies_to"], "category": o["category"],
             "min_amount": o["min_amount"]}
            for o in get_db().execute(
                "SELECT * FROM offers WHERE shop_id = ? AND active = 1 ORDER BY id",
                (g.shop["id"],)).fetchall()]


def shop_products():
    return [dict(p) for p in get_db().execute(
        "SELECT id, code, name, category, price, stock, low_stock_level FROM products "
        "WHERE shop_id = ? AND active = 1 ORDER BY name COLLATE NOCASE",
        (g.shop["id"],)).fetchall()]


@bp.route("/billing")
@login_required
def index():
    return render_template("billing.html", products=shop_products(),
                           next_label=next_bill_label(get_db(), g.shop["id"], date.today())[2],
                           payment_modes=PAYMENT_MODES, order_sources=ORDER_SOURCES,
                           places=PLACES, default_place=DEFAULT_PLACE,
                           customer_types=CUSTOMER_TYPES,
                           editing=None, prefill=None, skipped=[], offers=active_offers())


def split_other(stored, allowed):
    """'Other: Cheque' -> ('Other', 'Cheque'); 'UPI' -> ('UPI', '')."""
    if stored.startswith("Other: "):
        return "Other", stored[len("Other: "):]
    return (stored if stored in allowed else ""), ""


@bp.route("/billing/edit/<int:bill_id>")
@login_required
def edit(bill_id):
    """Opens a copy of a saved bill on the Billing screen. Nothing changes until it is saved."""
    db = get_db()
    old = db.execute("SELECT * FROM bills WHERE id = ? AND shop_id = ?",
                     (bill_id, g.shop["id"])).fetchone()
    if old is None:
        return redirect(url_for("bills.index"))
    if old["status"] != "Saved" or old["replaced_by"] is not None:
        flash("This bill has already been cancelled or replaced, so it can't be edited")
        return redirect(url_for("bills.view", bill_id=bill_id))

    products = shop_products()
    by_id = {p["id"]: p for p in products}
    items, skipped = [], []
    for line in db.execute("SELECT * FROM bill_lines WHERE bill_id = ? ORDER BY id",
                           (bill_id,)).fetchall():
        product = by_id.get(line["product_id"])
        if product is None:
            skipped.append(line["name"])           # removed from Inventory since the sale
            continue
        # This bill's items are still out of stock; saving puts them back first, so they
        # count as available while editing.
        product["stock"] += line["quantity"]
        items.append({"product_id": line["product_id"], "quantity": line["quantity"],
                      "discount": "%g" % line["line_discount_pct"] if line["line_discount_pct"] else ""})

    payments = []
    for p in db.execute("SELECT mode, amount FROM payments WHERE bill_id = ? ORDER BY id",
                        (bill_id,)).fetchall():
        mode, other = split_other(p["mode"], PAYMENT_MODES)
        payments.append({"mode": mode, "other": other, "amount": paise_to_input(p["amount"])})
    offers = active_offers()
    still_on = {o["id"] for o in offers}
    picked = [int(i) for i in old["offer_ids"].split(",") if i and int(i) in still_on]
    source, source_other = split_other(old["order_source"], ORDER_SOURCES)
    prefill = {
        "replaces": bill_id,
        "customer": old["customer_name"], "phone": old["customer_phone"],
        "location": old["customer_location"], "place": old["place_of_sale"],
        "source": source, "source_other": source_other,
        "whole_discount": "%g" % old["whole_discount_pct"] if old["whole_discount_pct"] else "",
        "shipping": paise_to_input(old["shipping"]) if old["shipping"] else "",
        "items": items, "payments": payments, "offer_ids": picked,
        "due_amount": paise_to_input(old["due_amount"]) if old["due_amount"] else "",
        "customer_type": old["customer_type"] or "Retail",
        "order_date": old["created_at"][:10],
    }
    return render_template("billing.html", products=products,
                           next_label=next_bill_label(get_db(), g.shop["id"], date.today())[2],
                           payment_modes=PAYMENT_MODES, order_sources=ORDER_SOURCES,
                           places=PLACES, default_place=DEFAULT_PLACE,
                           customer_types=CUSTOMER_TYPES,
                           editing=old, prefill=prefill, skipped=skipped, offers=offers)


@bp.route("/billing/save", methods=("POST",))
@login_required
def save():
    data = request.get_json(silent=True) or {}
    replaces = data.get("replaces")
    try:
        if replaces is not None:
            try:
                replaces = int(replaces)
            except (TypeError, ValueError):
                raise BillError("That bill wasn't found")
        bill_id = save_bill(get_db(), g.shop["id"], data.get("items", []),
                            customer_name=str(data.get("customer", "")),
                            customer_phone=str(data.get("phone", "")),
                            place_of_sale=str(data.get("place_of_sale", "")),
                            order_source=str(data.get("order_source", "")),
                            order_source_other=str(data.get("order_source_other", "")),
                            payments=data.get("payments"),
                            customer_location=str(data.get("location", "")),
                            due_amount=str(data.get("due_amount", "")),
                            customer_type=str(data.get("customer_type", "Retail")),
                            order_date=str(data.get("order_date", "")),
                            whole_discount=data.get("whole_discount", ""),
                            shipping=data.get("shipping", ""),
                            replaces=replaces, offer_ids=data.get("offer_ids") or [])
    except BillError as e:
        return jsonify(error=str(e)), 400
    return jsonify(url=url_for("bills.view", bill_id=bill_id, saved=1))


