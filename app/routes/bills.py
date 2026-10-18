from datetime import datetime

from flask import (Blueprint, Response, abort, flash, g, redirect, render_template, request,
                   url_for)

from ..auth import login_required
from ..db import get_db
from ..services import choices
from ..services import customers as people
from ..services.billing import (BillError, CUSTOMER_TYPES, cancel_bill, receive_due,
                                update_bill_customer)
from ..services.states import PLACES
from ..services.export import bills_workbook
from ..services.period import date_range

bp = Blueprint("bills", __name__)


def filtered_bills():
    """The shop's bills that match the search and filters on the page. Returns (bills, q, f)."""
    args = request.args
    q = args.get("q", "").strip()
    f = {key: args.get(key, "").strip()
         for key in ("source", "mode", "due", "date_from", "date_to", "customer")}
    f["date_from"], f["date_to"] = date_range(args)         # this month so far, until chosen otherwise
    sql = ("SELECT bills.*, (SELECT bill_label FROM bills r WHERE r.id = bills.replaced_by) "
           "AS replaced_by_number FROM bills WHERE shop_id = ?")
    params = [g.shop["id"]]
    if q:
        # A bill number may be typed as 26/1, 1 or #1. Customer name and phone are searched too.
        number = q.lstrip("#")
        sql += (" AND (bill_label = ? OR CAST(bill_seq AS TEXT) = ? "
                "OR customer_name LIKE ? OR customer_phone LIKE ?)")
        params += [number, number, f"%{q}%", f"%{q}%"]
    db = get_db()
    if f["source"] in choices.filter_options(db, g.shop["id"], "source"):
        if f["source"] == "Other":                 # matches 'Other: Phone call' and so on
            sql += " AND order_source LIKE 'Other%'"
        else:
            sql += " AND order_source = ?"
            params.append(f["source"])
    if f["mode"] in choices.filter_options(db, g.shop["id"], "method"):
        if f["mode"] == "Other":
            sql += " AND EXISTS (SELECT 1 FROM payments WHERE bill_id = bills.id AND mode LIKE 'Other%')"
        else:
            sql += " AND EXISTS (SELECT 1 FROM payments WHERE bill_id = bills.id AND mode = ?)"
            params.append(f["mode"])
    if f["customer"].isdigit():
        sql += " AND customer_id = ?"
        params.append(int(f["customer"]))
    if f["due"] == "due":
        sql += " AND due_amount > 0 AND status = 'Saved'"
    if f["date_from"]:
        sql += " AND date(created_at) >= date(?)"
        params.append(f["date_from"])
    if f["date_to"]:
        sql += " AND date(created_at) <= date(?)"
        params.append(f["date_to"])
    sql += " ORDER BY created_at DESC, id DESC"
    return get_db().execute(sql, params).fetchall(), q, f


@bp.route("/bills")
@login_required
def index():
    bills, q, f = filtered_bills()
    # What each bill was paid with, added up per way of paying: {bill id: {"UPI": paise, ...}}.
    # The columns are the shop's own payment methods; anything else is added up as "Other".
    methods = choices.names(get_db(), g.shop["id"], "method")
    paid = {}
    if bills:
        marks = ",".join("?" * len(bills))
        for p in get_db().execute(f"SELECT bill_id, mode, amount FROM payments "
                                  f"WHERE bill_id IN ({marks})", [b["id"] for b in bills]):
            by_mode = paid.setdefault(p["bill_id"], {})
            mode = p["mode"] if p["mode"] in methods else "Other"
            by_mode[mode] = by_mode.get(mode, 0) + p["amount"]
    columns = methods + (["Other"] if any("Other" in m for m in paid.values()) else [])
    has_any = get_db().execute("SELECT 1 FROM bills WHERE shop_id = ?",
                               (g.shop["id"],)).fetchone() is not None
    filtering = bool(request.args)
    return render_template("bills.html", bills=bills, q=q, f=f, has_any=has_any,
                           filtering=filtering, paid=paid, columns=columns,
                           order_sources=choices.filter_options(get_db(), g.shop["id"], "source"),
                           payment_modes=choices.filter_options(get_db(), g.shop["id"], "method"))


@bp.route("/bills/export.xlsx")
@login_required
def export():
    """Excel file of the bills the page is showing (everything, when nothing is filtered)."""
    bills, _, _ = filtered_bills()
    name = f"quantro-bills-{datetime.now():%Y-%m-%d}.xlsx"
    methods = choices.names(get_db(), g.shop["id"], "method")
    return Response(bills_workbook(get_db(), bills, methods),
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@bp.route("/bills/<int:bill_id>")
@login_required
def view(bill_id):
    db = get_db()
    bill = db.execute("SELECT * FROM bills WHERE id = ? AND shop_id = ?",
                      (bill_id, g.shop["id"])).fetchone()
    if bill is None:
        abort(404)
    lines = db.execute("SELECT * FROM bill_lines WHERE bill_id = ? ORDER BY id",
                       (bill_id,)).fetchall()
    payments = db.execute("SELECT * FROM payments WHERE bill_id = ? ORDER BY id",
                          (bill_id,)).fetchall()
    qr_codes = db.execute("SELECT * FROM shop_qr_codes WHERE shop_id = ? ORDER BY position, id",
                          (g.shop["id"],)).fetchall()
    other = lambda bill_id: db.execute(
        "SELECT id, bill_label FROM bills WHERE id = ? AND shop_id = ?",
        (bill_id, g.shop["id"])).fetchone() if bill_id else None
    return render_template("bill_view.html", bill=bill, lines=lines, payments=payments, qr_codes=qr_codes,
                           replaced_by=other(bill["replaced_by"]), replaces=other(bill["replaces"]),
                           just_saved=request.args.get("saved") == "1",
                           payment_modes=choices.with_other(db, g.shop["id"], "method"))


def own_bill(bill_id):
    bill = get_db().execute("SELECT * FROM bills WHERE id = ? AND shop_id = ?",
                            (bill_id, g.shop["id"])).fetchone()
    if bill is None:
        abort(404)
    return bill


@bp.route("/bills/<int:bill_id>/customer", methods=("GET", "POST"))
@login_required
def edit_customer(bill_id):
    """Fix the customer details printed on this one bill. No other bill is touched."""
    bill = own_bill(bill_id)
    values = {"name": bill["customer_name"], "phone": bill["customer_phone"],
              "location": bill["customer_location"],
              "customer_type": bill["customer_type"] or "Retail",
              "place": bill["place_of_sale"], "place_other": ""}
    if values["place"] and values["place"] not in PLACES:
        values["place"], values["place_other"] = "Other", bill["place_of_sale"]
    if request.method == "POST":
        f = request.form
        values = {"name": f.get("name", ""), "phone": f.get("phone", ""),
                  "location": f.get("location", ""),
                  "customer_type": f.get("customer_type", ""),
                  "place": f.get("place", ""), "place_other": f.get("place_other", "")}
        place = values["place_other"] if values["place"] == "Other" else values["place"]
        try:
            if values["place"] == "Other" and not place.strip():
                raise BillError("Please type the state or country for 'Other'")
            owner = update_bill_customer(get_db(), g.shop["id"], bill_id, values["name"],
                                         values["phone"], values["location"], place,
                                         values["customer_type"])
            if owner is not None:
                return redirect(url_for("bills.link_customer", bill_id=bill_id, to=owner["id"]))
            flash("Customer details updated on this bill only.", "ok")
            return redirect(url_for("bills.view", bill_id=bill_id))
        except BillError as e:
            flash(str(e))
    current = people.get(get_db(), g.shop["id"], bill["customer_id"]) if bill["customer_id"] else None
    return render_template("customer_edit.html", bill=bill, v=values, places=PLACES,
                           customer_types=CUSTOMER_TYPES, current=current)


@bp.route("/bills/<int:bill_id>/customer/link")
@login_required
def link_customer(bill_id):
    """After a phone number was changed to one that belongs to another customer: offer to move."""
    bill = own_bill(bill_id)
    owner = people.get(get_db(), g.shop["id"], request.args.get("to", ""))
    if owner is None or owner["id"] == bill["customer_id"]:
        return redirect(url_for("bills.view", bill_id=bill_id))
    current = people.get(get_db(), g.shop["id"], bill["customer_id"]) if bill["customer_id"] else None
    return render_template("bill_link.html", bill=bill, owner=owner, current=current)


@bp.route("/bills/<int:bill_id>/move", methods=("POST",))
@login_required
def move(bill_id):
    """Link this bill to another customer. What the bill printed stays as it was."""
    own_bill(bill_id)
    try:
        people.move_bill(get_db(), g.shop["id"], bill_id, request.form.get("customer_id", ""))
        flash("Bill moved to the other customer. What it printed is unchanged.", "ok")
    except people.CustomerError as e:
        flash(str(e))
        return redirect(url_for("bills.edit_customer", bill_id=bill_id))
    return redirect(url_for("bills.view", bill_id=bill_id))


@bp.route("/bills/<int:bill_id>/payment-received", methods=("POST",))
@login_required
def payment_received(bill_id):
    try:
        receive_due(get_db(), g.shop["id"], bill_id, request.form.get("mode"),
                    request.form.get("other"))
        flash("Payment received. The due amount is cleared.", "ok")
    except BillError as e:
        flash(str(e))
    return redirect(url_for("bills.view", bill_id=bill_id))

@bp.route("/bills/<int:bill_id>/cancel", methods=("POST",))
@login_required
def cancel(bill_id):
    try:
        cancel_bill(get_db(), g.shop["id"], bill_id)
        flash("Bill cancelled. Its items are back in stock.", "ok")
    except BillError as e:
        flash(str(e))
    return redirect(url_for("bills.view", bill_id=bill_id))

