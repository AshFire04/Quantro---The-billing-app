from flask import (Blueprint, Response, abort, flash, g, redirect, render_template,
                   request, url_for)

from ..auth import login_required
from ..db import get_db
from decimal import Decimal, InvalidOperation

from ..services import choices, inventory_import
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
    db = get_db()
    category_options = choices.product_filter_options(db, g.shop["id"], "category")
    supplier_options = choices.product_filter_options(db, g.shop["id"], "supplier")
    category = request.args.get("category", "")
    supplier = request.args.get("supplier", "")
    sql = "SELECT * FROM products WHERE shop_id = ? AND active = 1"
    params = [g.shop["id"]]
    if category in category_options:
        sql += " AND category = ?"
        params.append(category)
    if supplier in supplier_options:
        sql += " AND supplier = ?"
        params.append(supplier)
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
                           status=status, has_any=has_any, category=category, supplier=supplier,
                           category_options=category_options, supplier_options=supplier_options)


def form_lists():
    """The choices the product form's Category and Supplier dropdowns offer."""
    db = get_db()
    return {"category_choices": choices.names(db, g.shop["id"], "category"),
            "supplier_choices": choices.names(db, g.shop["id"], "supplier")}


def read_form(product_id=None, f=None):
    """Validate the product form (or a row of an imported sheet, passed as `f`).

    Returns (values, error).
    """
    f = request.form if f is None else f
    values = {
        "code": f.get("code", "").strip() or None,
        "name": f.get("name", "").strip(),
        "category": f.get("category", "").strip(),
        "hsn": f.get("hsn", "").strip(),
        "supplier": f.get("supplier", "").strip(),
    }
    # Category and supplier are picked from the lists kept in Shop Details. A product that
    # already carries a name the list no longer has can keep it.
    kept = {"category": "", "supplier": ""}
    if product_id:
        old = get_db().execute("SELECT category, supplier FROM products WHERE id = ? AND shop_id = ?",
                               (product_id, g.shop["id"])).fetchone()
        if old:
            kept = {"category": old["category"], "supplier": old["supplier"]}
    for field, kind in (("category", "category"), ("supplier", "supplier")):
        if values[field] \
                and values[field] not in choices.names(get_db(), g.shop["id"], kind) \
                and values[field] != kept[field]:
            return values, (f"Please choose a {field} from the list. "
                            f"Add new ones in Shop Details first.")
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
    return render_template("product_form.html", product=values, editing=False, **form_lists())


@bp.route("/<int:product_id>/edit", methods=("GET", "POST"))
@login_required
def edit(product_id):
    product = get_product(product_id)
    if request.method == "POST":
        values, error = read_form(product_id)
        if error:
            flash(error)
            return render_template("product_form.html", product=request.form,
                                   editing=True, product_id=product_id, **form_lists())
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
                           product_id=product_id, **form_lists())


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


# ---- Import from an Excel sheet ----

@bp.route("/import/template")
@login_required
def import_template():
    return Response(inventory_import.template_bytes(),
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename=products-template.xlsx"})


@bp.route("/import", methods=("GET", "POST"))
@login_required
def import_products():
    if request.method == "GET":
        return render_template("inventory_import.html", result=None)
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        flash("Please choose an Excel file")
        return redirect(url_for("inventory.import_products"))
    try:
        rows = inventory_import.read_products(upload.read(inventory_import.MAX_BYTES + 1))
    except inventory_import.SheetError as e:
        flash(str(e))
        return redirect(url_for("inventory.import_products"))

    db = get_db()
    shop_id = g.shop["id"]
    added, skipped, seen_codes = 0, [], set()
    for number, raw in rows:
        row = dict(raw)
        row["stock"] = row.get("stock") or "0"                  # blanks take the form's defaults
        row["low_stock_level"] = row.get("low_stock_level") or "5"
        values, error = read_form(f=row)
        if not error and values["code"] and values["code"].lower() in seen_codes:
            error = f"The code {values['code']} appears twice in the sheet"
        if error:
            skipped.append((number, error))
            continue
        if values["code"]:
            seen_codes.add(values["code"].lower())
        with db:
            db.execute(
                "INSERT INTO products (shop_id, code, name, category, price, "
                "stock, low_stock_level, hsn, supplier, cost_price, gst_rate) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (shop_id, values["code"], values["name"], values["category"],
                 values["price"], values["stock"], values["low_stock_level"],
                 values["hsn"], values["supplier"], values["cost_price"], values["gst_rate"]))
        added += 1
    return render_template("inventory_import.html",
                           result={"added": added, "skipped": skipped})
