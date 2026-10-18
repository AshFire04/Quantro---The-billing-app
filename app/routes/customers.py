from flask import (Blueprint, abort, flash, g, jsonify, redirect, render_template, request,
                   url_for)

from ..auth import login_required
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
              "location": customer["location"],
              "customer_type": customer["customer_type"]}
    taken = None
    if request.method == "POST":
        f = request.form
        values = {k: f.get(k, "") for k in values}
        try:
            people.update(db, g.shop["id"], customer_id, values["name"], values["phone"],
                          values["location"], values["customer_type"])
            flash("Customer saved. Bills already made keep what was printed on them.", "ok")
            return redirect(url_for("customers.detail", customer_id=customer_id))
        except people.PhoneTaken as e:
            taken = e.owner
        except people.CustomerError as e:
            flash(str(e))
    stats = people.listing(db, g.shop["id"], "")
    stats = next((c for c in stats if c["id"] == customer_id), customer)
    bills = db.execute("SELECT * FROM bills WHERE customer_id = ? AND shop_id = ? "
                       "ORDER BY created_at DESC, id DESC", (customer_id, g.shop["id"])).fetchall()
    others = [c for c in people.listing(db, g.shop["id"], "") if c["id"] != customer_id]
    return render_template("customer_detail.html", c=customer, stats=stats, v=values, bills=bills,
                           others=others, taken=taken, customer_types=CUSTOMER_TYPES)


@bp.route("/customers/<int:customer_id>/merge", methods=("GET", "POST"))
@login_required
def merge(customer_id):
    """Join this customer into another one: a page to check it, then the real thing."""
    db = get_db()
    source = own_customer(customer_id)
    target = people.get(db, g.shop["id"], request.values.get("into", ""))
    if target is None or target["id"] == source["id"]:
        flash("Pick the customer to merge into")
        return redirect(url_for("customers.detail", customer_id=customer_id))
    if request.method == "POST":
        try:
            done = people.merge(db, g.shop["id"], source["id"], target["id"])
        except people.CustomerError as e:
            flash(str(e))
            return redirect(url_for("customers.detail", customer_id=customer_id))
        note = f"Merged. {done['moved']} bill{'' if done['moved'] == 1 else 's'} moved to {target['name']}."
        if done["copied_phone"]:
            note += f" The number {source['phone']} was copied across."
        if done["dropped_phone"]:
            note += f" {source['name']} had a different number, {done['dropped_phone']}, which is no longer kept."
        flash(note, "ok")
        return redirect(url_for("customers.detail", customer_id=target["id"]))
    rows = {c["id"]: c for c in people.listing(db, g.shop["id"], "")}
    return render_template("customer_merge.html", source=rows[source["id"]], target=rows[target["id"]])


@bp.route("/customers/<int:customer_id>/delete", methods=("POST",))
@login_required
def delete(customer_id):
    own_customer(customer_id)
    if people.delete_if_unused(get_db(), g.shop["id"], customer_id):
        flash("Customer removed", "ok")
        return redirect(url_for("customers.index"))
    flash("This customer has bills, so they can't be removed. Merge them into another customer instead.")
    return redirect(url_for("customers.detail", customer_id=customer_id))
