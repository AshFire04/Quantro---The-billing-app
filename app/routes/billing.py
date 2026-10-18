from flask import (Blueprint, flash, g, jsonify, redirect, render_template, request,
                   url_for)

from ..auth import login_required
from ..db import get_db
from datetime import date

from ..services import choices
from ..services.billing import (BillError, CUSTOMER_TYPES, next_bill_label,
                                save_bill)
from ..services.states import DEFAULT_PLACE, PLACES
from ..services.money import paise_to_input

bp = Blueprint("billing", __name__)


def active_offers():
    """The shop's switched-on offers, in the shape the Billing screen needs."""
    return [{"id": o["id"], "name": o["name"], "pct": o["percentage"],
             "applies_to": o["applies_to"], "category": o["category"],
             "min_amount": o["min_amount"], "exclude": o["exclude_category"]}
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
                           payment_modes=choices.with_other(get_db(), g.shop["id"], "method"),
                           order_sources=choices.with_other(get_db(), g.shop["id"], "source"),
                           places=PLACES, default_place=DEFAULT_PLACE,
                           customer_types=CUSTOMER_TYPES,
                           editing=None, prefill=None, skipped=[], offers=active_offers(),
                           default_source=choices.default_of(get_db(), g.shop["id"], "source"),
                           default_method=choices.default_of(get_db(), g.shop["id"], "method"))


def split_other(stored, allowed):
    """'Other: Cheque' -> ('Other', 'Cheque'); 'UPI' -> ('UPI', '').

    A name the shop has since removed from its list comes back as 'Other' with that name typed in.
    """
    if stored.startswith("Other: "):
        return "Other", stored[len("Other: "):]
    if stored in allowed or not stored:
        return stored, ""
    return "Other", stored


@bp.route("/billing/edit/<int:bill_id>")
@login_required
def edit(bill_id):
    """Opens a copy of a saved bill on the Billing screen. Nothing changes until it is saved."""
    db = get_db()
    old = db.execute("SELECT * FROM bills WHERE id = ? AND shop_id = ?",
                     (bill_id, g.shop["id"])).fetchone()
    if old is None:
        return redirect(url_for("bills.index"))
    is_draft = old["status"] == "Draft"
    if not is_draft and (old["status"] != "Saved" or old["replaced_by"] is not None):
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
        # A saved bill's items are still out of stock; saving puts them back first, so they
        # count as available while editing. A draft holds no stock, so nothing is added.
        if not is_draft:
            product["stock"] += line["quantity"]
        items.append({"product_id": line["product_id"], "quantity": line["quantity"],
                      "discount": "%g" % line["line_discount_pct"] if line["line_discount_pct"] else ""})

    pay_modes = choices.with_other(db, g.shop["id"], "method")
    source_choices = choices.with_other(db, g.shop["id"], "source")
    payments = []
    for p in db.execute("SELECT mode, amount FROM payments WHERE bill_id = ? ORDER BY id",
                        (bill_id,)).fetchall():
        mode, other = split_other(p["mode"], pay_modes)
        payments.append({"mode": mode, "other": other, "amount": paise_to_input(p["amount"])})
    offers = active_offers()
    still_on = {o["id"] for o in offers}
    picked = [int(i) for i in old["offer_ids"].split(",") if i and int(i) in still_on]
    source, source_other = split_other(old["order_source"], source_choices)
    # A whole-bill discount that came from a ticked offer is left blank, so the offer (and the
    # category it leaves out) works it out again instead of it being treated as typed by hand.
    named = [n.strip() for n in old["offers_applied"].split(",")]
    from_offer = any(o["applies_to"] == "bill" and o["name"] in named and o["pct"] == old["whole_discount_pct"]
                     for o in offers if o["id"] in picked)
    prefill = {
        "replaces": None if is_draft else bill_id,
        "draft_id": bill_id if is_draft else None,
        "customer": old["customer_name"], "phone": old["customer_phone"],
        "customer_id": old["customer_id"],
        "location": old["customer_location"], "place": old["place_of_sale"],
        "source": source, "source_other": source_other,
        "whole_discount": ("" if from_offer else "%g" % old["whole_discount_pct"])
                          if old["whole_discount_pct"] else "",
        "shipping": paise_to_input(old["shipping"]) if old["shipping"] else "",
        "items": items, "payments": payments, "offer_ids": picked,
        "due_amount": paise_to_input(old["due_amount"]) if old["due_amount"] else "",
        "customer_type": old["customer_type"] or "Retail",
        "order_date": old["created_at"][:10],
    }
    return render_template("billing.html", products=products,
                           next_label=next_bill_label(get_db(), g.shop["id"], date.today())[2],
                           payment_modes=choices.with_other(get_db(), g.shop["id"], "method"),
                           order_sources=choices.with_other(get_db(), g.shop["id"], "source"),
                           places=PLACES, default_place=DEFAULT_PLACE,
                           customer_types=CUSTOMER_TYPES,
                           editing=old, prefill=prefill, skipped=skipped, offers=offers,
                           default_source="", default_method="")


@bp.route("/billing/save", methods=("POST",))
@login_required
def save():
    data = request.get_json(silent=True) or {}
    replaces, draft_id = data.get("replaces"), data.get("draft_id")
    draft = data.get("draft") is True
    try:
        try:
            replaces = None if replaces is None else int(replaces)
            draft_id = None if draft_id is None else int(draft_id)
        except (TypeError, ValueError):
            raise BillError("That bill wasn't found")
        bill_id = save_bill(get_db(), g.shop["id"], data.get("items", []),
                            customer_name=str(data.get("customer", "")),
                            customer_phone=str(data.get("phone", "")),
                            customer_id=data.get("customer_id"),
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
                            replaces=replaces, offer_ids=data.get("offer_ids") or [],
                            draft=draft, draft_id=draft_id)
    except BillError as e:
        return jsonify(error=str(e)), 400
    return jsonify(url=url_for("bills.view", bill_id=bill_id, saved="draft" if draft else 1))


