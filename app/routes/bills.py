from flask import (Blueprint, abort, flash, g, redirect, render_template, request,
                   url_for)

from ..auth import login_required
from ..db import get_db
from ..services.billing import (BillError, ORDER_SOURCES, PAYMENT_MODES,
                                cancel_bill, receive_due)

bp = Blueprint("bills", __name__)


@bp.route("/bills")
@login_required
def index():
    args = request.args
    q = args.get("q", "").strip()
    f = {key: args.get(key, "").strip()
         for key in ("source", "mode", "due", "date_from", "date_to")}
    sql = ("SELECT bills.*, (SELECT invoice_number FROM bills r WHERE r.id = bills.replaced_by) "
           "AS replaced_by_number FROM bills WHERE shop_id = ?")
    params = [g.shop["id"]]
    if q:
        # A bill number may be typed with a '#'. Customer name and phone are searched too.
        number = q.lstrip("#")
        sql += " AND (CAST(invoice_number AS TEXT) = ? OR customer_name LIKE ? OR customer_phone LIKE ?)"
        params += [number, f"%{q}%", f"%{q}%"]
    if f["source"] in ORDER_SOURCES:
        sql += " AND order_source LIKE ?"          # 'Other' matches 'Other: Phone call' too
        params.append(f["source"] + "%")
    if f["mode"] in PAYMENT_MODES:
        sql += " AND EXISTS (SELECT 1 FROM payments WHERE bill_id = bills.id AND mode LIKE ?)"
        params.append(f["mode"] + "%")
    if f["due"] == "due":
        sql += " AND due_amount > 0 AND status = 'Saved'"
    if f["date_from"]:
        sql += " AND date(created_at) >= date(?)"
        params.append(f["date_from"])
    if f["date_to"]:
        sql += " AND date(created_at) <= date(?)"
        params.append(f["date_to"])
    sql += " ORDER BY created_at DESC, id DESC"
    bills = get_db().execute(sql, params).fetchall()
    has_any = get_db().execute("SELECT 1 FROM bills WHERE shop_id = ?",
                               (g.shop["id"],)).fetchone() is not None
    filtering = bool(q or any(f.values()))
    return render_template("bills.html", bills=bills, q=q, f=f, has_any=has_any,
                           filtering=filtering, order_sources=ORDER_SOURCES,
                           payment_modes=PAYMENT_MODES)


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
        "SELECT id, invoice_number FROM bills WHERE id = ? AND shop_id = ?",
        (bill_id, g.shop["id"])).fetchone() if bill_id else None
    return render_template("bill_view.html", bill=bill, lines=lines, payments=payments, qr_codes=qr_codes,
                           replaced_by=other(bill["replaced_by"]), replaces=other(bill["replaces"]),
                           just_saved=request.args.get("saved") == "1",
                           payment_modes=PAYMENT_MODES)


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

