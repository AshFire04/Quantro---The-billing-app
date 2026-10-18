from flask import (Blueprint, abort, flash, g, jsonify, redirect, render_template, request,
                   url_for)

from ..auth import login_required
from .bills import owner_summary, plain_plan_lines
from ..db import get_db
from ..services import customers as people
from ..services.billing import CUSTOMER_TYPES
from ..services.money import format_date, format_rupees
from ..services.period import date_range

bp = Blueprint("customers", __name__)

SORTS = {"last": "last_bill IS NULL, last_bill DESC, c.name COLLATE NOCASE",
         "name": "c.name COLLATE NOCASE",
         "high": "spent DESC, c.name COLLATE NOCASE",
         "low": "spent ASC, c.name COLLATE NOCASE"}


def card(c):
    """A customer as the Billing screen and pickers need them (JSON)."""
    return {"id": c["id"], "name": c["name"], "phone": c["phone"],
            "location": c["location"], "customer_type": c["customer_type"],
            "legacy": bool(c["legacy"]), "bill_count": c["bill_count"],
            "last_bill": format_date(c["last_bill"]) if c["last_bill"] else "",
            "total": format_rupees(c["spent"])}


def own_customer(customer_id):
    customer = people.get(get_db(), g.shop["id"], customer_id)
    if customer is None:
        abort(404)
    return customer


@bp.route("/customers")
@login_required
def index():
    q = request.args.get("q", "").strip()
    sort = request.args.get("sort", "last")
    ctype = request.args.get("type", "")
    ctype = ctype if ctype in CUSTOMER_TYPES else ""
    start, end = date_range(request.args)
    db = get_db()
    has_any = db.execute("SELECT 1 FROM customers WHERE shop_id = ?",
                         (g.shop["id"],)).fetchone() is not None
    customers = people.listing(db, g.shop["id"], q, SORTS.get(sort, SORTS["last"]),
                               start=start, end=end, customer_type=ctype)
    return render_template("customers.html", q=q, has_any=has_any, sort=sort, ctype=ctype,
                           date_from=start, date_to=end, customers=customers,
                           customer_types=CUSTOMER_TYPES)


@bp.route("/customers/lookup")
@login_required
def lookup():
    """Billing: the customer who owns a mobile number (found by that number only)."""
    digits, error = people.normalize_phone(request.args.get("phone", ""))
    if error:
        return jsonify(found=False, error=error)
    if not digits:
        return jsonify(found=False)
    found = people.listing(get_db(), g.shop["id"], digits)
    found = [c for c in found if c["phone"] == digits]
    return jsonify(found=True, **card(found[0])) if found else jsonify(found=False)


@bp.route("/customers/search")
@login_required
def search():
    """Billing and the pickers: customers matching a name or phone, most recent first."""
    found = people.listing(get_db(), g.shop["id"], request.args.get("q", ""),
                           "last_bill IS NULL, last_bill DESC, c.name COLLATE NOCASE", limit=8)
    return jsonify(customers=[card(c) for c in found])


@bp.route("/customers/<int:customer_id>", methods=("GET", "POST"))
@login_required
def detail(customer_id):
    db = get_db()
    customer = own_customer(customer_id)
    values = {"name": customer["name"], "phone": customer["phone"],
              "location": customer["location"], "customer_type": customer["customer_type"]}
    if request.method == "POST":
        f = request.form
        values = {k: f.get(k, "") for k in values}
        action = f.get("action", "")
        try:
            digits, error = people.normalize_phone(values["phone"])
            if error:
                raise people.CustomerError(error)
            owner = people.find_by_phone(db, g.shop["id"], digits)
            if owner is not None and owner["id"] != customer_id and action != "no":
                plan = people.plan_for_customer(db, g.shop["id"], customer, owner)
                if action != "yes":
                    return render_template(
                        "customer_confirm.html", owner=owner, owner_text=owner_summary(owner),
                        lines=plain_plan_lines(plan, owner), fields=values,
                        form_action=url_for("customers.detail", customer_id=customer_id),
                        back_url=url_for("customers.detail", customer_id=customer_id))
                back = url_for("customers.detail", customer_id=owner["id"])
                token = people.combine(db, g.shop["id"], owner["id"], plan, back)
                return redirect(url_for("customers.detail", customer_id=owner["id"], undo=token))
            if action != "no":
                people.update(db, g.shop["id"], customer_id, values["name"], values["phone"],
                              values["location"], values["customer_type"])
                flash("Customer saved. Bills already made keep what was printed on them.", "ok")
                return redirect(url_for("customers.detail", customer_id=customer_id))
        except people.CustomerError as e:
            flash(str(e))
    stats = people.listing(db, g.shop["id"], "")
    stats = next((c for c in stats if c["id"] == customer_id), customer)
    bills = db.execute("SELECT * FROM bills WHERE customer_id = ? AND shop_id = ? "
                       "ORDER BY created_at DESC, id DESC", (customer_id, g.shop["id"])).fetchall()
    return render_template("customer_detail.html", c=customer, stats=stats, v=values, bills=bills,
                           customer_types=CUSTOMER_TYPES)


@bp.route("/undo/<token>", methods=("POST",))
@login_required
def undo(token):
    """Take back a "Combined" within its 30 seconds."""
    back = people.undo(get_db(), g.shop["id"], token)
    if back is None:
        flash("It is too late to undo that.")
        return redirect(url_for("customers.index"))
    flash("Undone. The customers are back as they were.", "ok")
    return redirect(back)


@bp.route("/customers/<int:customer_id>/delete", methods=("POST",))
@login_required
def delete(customer_id):
    own_customer(customer_id)
    if people.delete_if_unused(get_db(), g.shop["id"], customer_id):
        flash("Customer removed", "ok")
        return redirect(url_for("customers.index"))
    flash("This customer has bills, so they can't be removed.")
    return redirect(url_for("customers.detail", customer_id=customer_id))
