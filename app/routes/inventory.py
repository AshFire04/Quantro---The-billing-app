from flask import (Blueprint, abort, flash, g, redirect, render_template,
                   request, url_for)

from ..auth import login_required
from ..db import get_db
from decimal import Decimal, InvalidOperation

from ..services.money import paise_to_input, rupees_to_paise

bp = Blueprint("inventory", __name__, url_prefix="/inventory")


def status_of(product):
    """In stock / Low / Out, worked out from the stock and the low-stock level."""
    if product["stock"] <= 0:
        return "Out"
    if product["stock"] <= product["low_stock_level"]:
        return "Low"
    return "In stock"


def get_product(product_id):
    """Fetch a product, but only if it belongs to the signed-in shop."""
    product = get_db().execute(
        "SELECT * FROM products WHERE id = ? AND shop_id = ? AND active = 1",
        (product_id, g.shop["id"])).fetchone()
    if product is None:
        abort(404)
    return product


@bp.route("/")
@login_required
def index():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "all")
    sql = "SELECT * FROM products WHERE shop_id = ? AND active = 1"
    params = [g.shop["id"]]
    if q:
        sql += " AND (name LIKE ? OR code LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    if status == "out":
        sql += " AND stock <= 0"
    elif status == "low":
        sql += " AND stock > 0 AND stock <= low_stock_level"
    sql += " ORDER BY name COLLATE NOCASE"
    products = [dict(p, status=status_of(p))
                for p in get_db().execute(sql, params).fetchall()]
    has_any = get_db().execute(
        "SELECT 1 FROM products WHERE shop_id = ? AND active = 1",
        (g.shop["id"],)).fetchone() is not None
    return render_template("inventory.html", products=products, q=q,
                           status=status, has_any=has_any)


def read_form(product_id=None):
    """Validate the product form. Returns (values, error)."""
    f = request.form
    values = {
        "code": f.get("code", "").strip() or None,
        "name": f.get("name", "").strip(),
        "category": f.get("category", "").strip(),
        "hsn": f.get("hsn", "").strip(),
        "supplier": f.get("supplier", "").strip(),
    }
    if values["hsn"] and not (values["hsn"].isdigit() and len(values["hsn"]) <= 8):
        return values, "The HSN/SAC number should be digits only, up to 8 of them"
    try:
        cost = f.get("cost_price", "").strip()
        values["cost_price"] = rupees_to_paise(cost) if cost else 0
    except ValueError:
        return values, "Enter the cost price as a number, like 300 or 300.50"
    gst = f.get("gst_rate", "").strip().rstrip("%")
    values["gst_rate"] = None
    if gst:
        try:
            rate = Decimal(gst)
        except InvalidOperation:
            return values, "Enter the GST rate as a number, like 5 or 18"
        if not rate.is_finite() or not 0 <= rate <= 100 or rate != rate.quantize(Decimal("0.01")):
            return values, "The GST rate must be between 0 and 100, with at most two decimal places"
        values["gst_rate"] = float(rate)
    try:
        values["price"] = rupees_to_paise(f.get("price", ""))
        values["stock"] = int(f.get("stock", ""))
        values["low_stock_level"] = int(f.get("low_stock_level", ""))
    except ValueError as e:
        if "price" in str(e).lower():
            return values, str(e)
        return values, "Stock and low-stock level must be whole numbers"
    if not values["name"]:
        return values, "Please give the product a name"
    if values["stock"] < 0 or values["low_stock_level"] < 0:
        return values, "Stock and low-stock level can't be negative"
    if values["code"]:
        # A code is used for good: a removed product keeps its code, so it can't come back.
        clash = get_db().execute(
            "SELECT active FROM products WHERE shop_id = ? AND code = ? AND id != ?",
            (g.shop["id"], values["code"], product_id or 0)).fetchone()
        if clash and clash["active"]:
            return values, f"Another product already uses the code {values['code']}"
        if clash:
            return values, (f"The code {values['code']} was used by a product that has been "
                            "removed, so it can't be used again")
    return values, None


@bp.route("/new", methods=("GET", "POST"))
@login_required
def new():
    values = {"low_stock_level": 5, "stock": 0}
    if request.method == "POST":
        values, error = read_form()
        if error:
            flash(error)
        else:
            db = get_db()
            with db:
                db.execute(
                    "INSERT INTO products (shop_id, code, name, category, price, "
                    "stock, low_stock_level, hsn, supplier, cost_price, gst_rate) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (g.shop["id"], values["code"], values["name"], values["category"],
                     values["price"], values["stock"], values["low_stock_level"],
                     values["hsn"], values["supplier"], values["cost_price"], values["gst_rate"]))
            return redirect(url_for("inventory.index"))
        values = request.form
    return render_template("product_form.html", product=values, editing=False)


@bp.route("/<int:product_id>/edit", methods=("GET", "POST"))
@login_required
def edit(product_id):
    product = get_product(product_id)
    if request.method == "POST":
        values, error = read_form(product_id)
        if error:
            flash(error)
            return render_template("product_form.html", product=request.form,
                                   editing=True, product_id=product_id)
        db = get_db()
        with db:
            db.execute(
                "UPDATE products SET code = ?, name = ?, category = ?, price = ?, "
                "stock = ?, low_stock_level = ?, hsn = ?, supplier = ?, cost_price = ?, "
                "gst_rate = ? WHERE id = ? AND shop_id = ?",
                (values["code"], values["name"], values["category"], values["price"],
                 values["stock"], values["low_stock_level"], values["hsn"], values["supplier"],
                 values["cost_price"], values["gst_rate"], product_id, g.shop["id"]))
        return redirect(url_for("inventory.index"))
    product = dict(product, price=paise_to_input(product["price"]),
                   cost_price=paise_to_input(product["cost_price"]) if product["cost_price"] else "",
                   gst_rate="%g" % product["gst_rate"] if product["gst_rate"] is not None else "")
    return render_template("product_form.html", product=product, editing=True,
                           product_id=product_id)


@bp.route("/<int:product_id>/remove", methods=("POST",))
@login_required
def remove(product_id):
    get_product(product_id)
    db = get_db()
    with db:
        # Hide, don't delete: old bills still need to show what was sold.
        # The code stays with it, so no new product can ever take the same code.
        db.execute("UPDATE products SET active = 0 WHERE id = ? AND shop_id = ?",
                   (product_id, g.shop["id"]))
    return redirect(url_for("inventory.index"))
