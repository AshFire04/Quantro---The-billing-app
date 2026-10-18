import os
import re
import secrets

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template,
                   request, send_from_directory, url_for)

from ..auth import login_required
from ..db import get_db
from ..services import choices
from ..services.billing import BillError, parse_percent
from ..services.money import paise_to_input, rupees_to_paise

bp = Blueprint("settings", __name__)

MAX_QR_BYTES = 1024 * 1024        # 1 MB per image
MAX_QR_CODES = 3
# The first bytes of a real PNG or JPEG file. The file name alone can't be trusted.
IMAGE_TYPES = {b"\x89PNG\r\n\x1a\n": ".png", b"\xff\xd8\xff": ".jpg"}


@bp.route("/settings")
@login_required
def index():
    db = get_db()
    offers = db.execute("SELECT * FROM offers WHERE shop_id = ? ORDER BY id",
                        (g.shop["id"],)).fetchall()
    qr_codes = db.execute("SELECT * FROM shop_qr_codes WHERE shop_id = ? ORDER BY position, id",
                          (g.shop["id"],)).fetchall()
    categories = [r[0] for r in db.execute(
        "SELECT DISTINCT category FROM products WHERE shop_id = ? AND active = 1 "
        "AND category != '' ORDER BY category COLLATE NOCASE", (g.shop["id"],))]
    return render_template("settings.html", offers=offers, qr_codes=qr_codes,
                           categories=categories, paise_to_input=paise_to_input,
                           max_qr_codes=MAX_QR_CODES,
                           sources=choices.rows(db, g.shop["id"], "source"),
                           methods=choices.rows(db, g.shop["id"], "method"),
                           categories_list=choices.rows(db, g.shop["id"], "category"),
                           suppliers=choices.rows(db, g.shop["id"], "supplier"),
                           default_source=choices.default_of(db, g.shop["id"], "source"),
                           default_method=choices.default_of(db, g.shop["id"], "method"))


@bp.route("/settings/details", methods=("POST",))
@login_required
def details():
    f = request.form
    name = f.get("name", "").strip()
    if not name:
        flash("Please give your shop a name")
        return redirect(url_for("settings.index"))
    email = f.get("email", "").strip()
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        flash("That email address doesn't look right")
        return redirect(url_for("settings.index"))
    db = get_db()
    with db:
        db.execute("UPDATE shops SET name = ?, phone = ?, website = ?, email = ?, "
                   "bank_details = ?, terms = ? WHERE id = ?",
                   (name, f.get("phone", "").strip(), f.get("website", "").strip(), email,
                    f.get("bank_details", "").strip(), f.get("terms", "").strip(),
                    g.shop["id"]))
    flash("Shop details saved", "ok")
    return redirect(url_for("settings.index"))


@bp.route("/settings/target", methods=("POST",))
@login_required
def target():
    text = request.form.get("monthly_target", "").strip()
    try:
        paise = rupees_to_paise(text or "0")
    except ValueError:
        flash("Enter the monthly target as an amount, like 200000")
        return redirect(url_for("settings.index"))
    db = get_db()
    with db:
        db.execute("UPDATE shops SET monthly_target = ? WHERE id = ?", (paise, g.shop["id"]))
    flash("Monthly sales target saved", "ok")
    return redirect(url_for("settings.index"))


# ---- Order sources and payment methods: the shop's own lists ----

ANCHORS = {"source": "sources", "method": "payments", "category": "categories",
           "supplier": "suppliers"}


def kind_of(word):
    """The page addresses are /settings/sources/..., /settings/payments/...,
    /settings/categories/... and /settings/suppliers/..."""
    return {"sources": "source", "payments": "method", "categories": "category",
            "suppliers": "supplier"}.get(word) or abort(404)


@bp.route("/settings/<any(sources,payments):word>/default", methods=("POST",))
@login_required
def set_default_choice(word):
    kind = kind_of(word)
    error = choices.set_default(get_db(), g.shop["id"], kind, request.form.get("name", ""))
    if error:
        flash(error)
    else:
        flash("Starting choice saved. New bills begin with it.", "ok")
    return redirect(url_for("settings.index") + "#" + ANCHORS[kind])


@bp.route("/settings/<any(sources,payments,categories,suppliers):word>", methods=("POST",))
@login_required
def add_choice(word):
    kind = kind_of(word)
    error = choices.add(get_db(), g.shop["id"], kind, request.form.get("name", ""))
    if error:
        flash(error)
    else:
        flash(f"\"{' '.join(request.form['name'].split())}\" added", "ok")
    return redirect(url_for("settings.index") + "#" + ANCHORS[kind])


@bp.route("/settings/<any(sources,payments,categories,suppliers):word>/<int:choice_id>/delete", methods=("POST",))
@login_required
def delete_choice(word, choice_id):
    kind = kind_of(word)
    if not choices.remove(get_db(), g.shop["id"], kind, choice_id):
        abort(404)
    return redirect(url_for("settings.index") + "#" + ANCHORS[kind])


# ---- Saved offers ----

def read_offer_form():
    """Validate the Add offer form. Returns (values, error)."""
    f = request.form
    name = f.get("name", "").strip()
    applies_to = f.get("applies_to", "")
    category = f.get("category", "").strip()
    chosen = []                         # categories left out of an all-items offer
    for c in f.getlist("exclude_category"):
        c = " ".join(c.replace("|", " ").split())
        if c and c.lower() not in [x.lower() for x in chosen]:
            chosen.append(c)
    exclude = "|".join(chosen)
    try:
        pct = parse_percent(f.get("percentage", ""), "The offer percentage")
        if pct <= 0:
            raise BillError("The offer percentage must be above 0")
        minimum = rupees_to_paise(f.get("min_amount") or "0")
    except BillError as e:
        return None, str(e)
    except ValueError:
        return None, "Enter the minimum bill amount as a number, like 2500"
    if not name:
        return None, "Please give the offer a name"
    if applies_to not in ("category", "bill"):
        return None, "Please choose what the offer applies to"
    if applies_to == "category" and not category:
        return None, "Please enter the category this offer applies to"
    if applies_to == "category":
        minimum = 0                       # a minimum only makes sense for whole-bill offers
    else:
        category = ""
    if applies_to == "category":
        exclude = ""                      # leaving a category out only makes sense for all-items offers
    return {"name": name, "pct": float(pct), "applies_to": applies_to,
            "category": category, "minimum": minimum, "exclude": exclude}, None


@bp.route("/settings/offers", methods=("POST",))
@login_required
def add_offer():
    values, error = read_offer_form()
    if error:
        flash(error)
    else:
        db = get_db()
        with db:
            db.execute("INSERT INTO offers (shop_id, name, percentage, applies_to, category, "
                       "min_amount, exclude_category) VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (g.shop["id"], values["name"], values["pct"], values["applies_to"],
                        values["category"], values["minimum"], values["exclude"]))
        flash(f"Offer \"{values['name']}\" added", "ok")
    return redirect(url_for("settings.index"))


def own_offer(offer_id):
    offer = get_db().execute("SELECT * FROM offers WHERE id = ? AND shop_id = ?",
                             (offer_id, g.shop["id"])).fetchone()
    if offer is None:
        abort(404)
    return offer


@bp.route("/settings/offers/<int:offer_id>/toggle", methods=("POST",))
@login_required
def toggle_offer(offer_id):
    offer = own_offer(offer_id)
    db = get_db()
    with db:
        db.execute("UPDATE offers SET active = ? WHERE id = ?", (0 if offer["active"] else 1, offer_id))
    return redirect(url_for("settings.index"))


@bp.route("/settings/offers/<int:offer_id>/delete", methods=("POST",))
@login_required
def delete_offer(offer_id):
    own_offer(offer_id)
    db = get_db()
    with db:
        # Old bills keep the offer's name as text, so nothing else needs to change.
        db.execute("DELETE FROM offers WHERE id = ?", (offer_id,))
    return redirect(url_for("settings.index"))


# ---- Images: the QR codes and the shop logo ----

def read_image(image):
    """The bytes and file extension of an uploaded PNG or JPG. Returns (data, extension, error)."""
    if image is None or image.filename == "":
        return None, None, "Please choose an image to upload"
    data = image.read(MAX_QR_BYTES + 1)
    extension = next((ext for magic, ext in IMAGE_TYPES.items() if data.startswith(magic)), None)
    if len(data) > MAX_QR_BYTES:
        return None, None, "That image is too big. Please use one under 1 MB."
    if extension is None:
        return None, None, "That file isn't a PNG or JPG image"
    return data, extension, None


def save_image(data, extension):
    """Writes the image under a random name (never the uploaded one) and returns that name."""
    filename = secrets.token_hex(16) + extension
    with open(os.path.join(upload_dir(), filename), "wb") as out:
        out.write(data)
    return filename


def delete_image(filename):
    try:
        os.remove(os.path.join(upload_dir(), filename))
    except OSError:
        pass                                  # the record is gone; a leftover file is harmless


@bp.route("/settings/logo", methods=("POST",))
@login_required
def add_logo():
    data, extension, error = read_image(request.files.get("logo"))
    if error:
        flash(error)
        return redirect(url_for("settings.index") + "#logo")
    old = g.shop["logo"]
    db = get_db()
    filename = save_image(data, extension)
    with db:
        db.execute("UPDATE shops SET logo = ? WHERE id = ?", (filename, g.shop["id"]))
    if old:
        delete_image(old)
    flash("Logo saved. It now prints at the top of your bills.", "ok")
    return redirect(url_for("settings.index") + "#logo")


@bp.route("/settings/logo/remove", methods=("POST",))
@login_required
def remove_logo():
    old = g.shop["logo"]
    db = get_db()
    with db:
        db.execute("UPDATE shops SET logo = '' WHERE id = ?", (g.shop["id"],))
    if old:
        delete_image(old)
        flash("Logo removed", "ok")
    return redirect(url_for("settings.index") + "#logo")


# ---- QR code images ----

def upload_dir():
    path = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(path, exist_ok=True)
    return path


@bp.route("/settings/qr", methods=("POST",))
@login_required
def add_qr():
    label = request.form.get("label", "").strip()
    image = request.files.get("image")
    db = get_db()
    count = db.execute("SELECT COUNT(*) FROM shop_qr_codes WHERE shop_id = ?",
                       (g.shop["id"],)).fetchone()[0]
    if not label:
        flash("Please give the QR code a label, like UPI or Instagram")
    elif len(label) > 40:
        flash("Keep the QR code label under 40 characters")
    elif count >= MAX_QR_CODES:
        flash(f"You can keep up to {MAX_QR_CODES} QR codes. Remove one first.")
    else:
        data, extension, error = read_image(image)
        if error:
            flash(error)
        else:
            filename = save_image(data, extension)
            with db:
                db.execute("INSERT INTO shop_qr_codes (shop_id, label, filename, position) "
                           "VALUES (?, ?, ?, ?)", (g.shop["id"], label, filename, count))
            flash(f"QR code \"{label}\" added", "ok")
    return redirect(url_for("settings.index"))


@bp.route("/settings/qr/<int:qr_id>/delete", methods=("POST",))
@login_required
def delete_qr(qr_id):
    db = get_db()
    qr = db.execute("SELECT * FROM shop_qr_codes WHERE id = ? AND shop_id = ?",
                    (qr_id, g.shop["id"])).fetchone()
    if qr is None:
        abort(404)
    with db:
        db.execute("DELETE FROM shop_qr_codes WHERE id = ?", (qr_id,))
    delete_image(qr["filename"])
    return redirect(url_for("settings.index"))


@bp.route("/uploads/<filename>")
@login_required
def uploaded_file(filename):
    """Serves a QR image or logo, but only to the shop that owns it."""
    owned = get_db().execute(
        "SELECT 1 FROM shop_qr_codes WHERE filename = ? AND shop_id = ? "
        "UNION SELECT 1 FROM shops WHERE logo = ? AND id = ?",
        (filename, g.shop["id"], filename, g.shop["id"])).fetchone()
    if owned is None:
        abort(404)
    return send_from_directory(upload_dir(), filename)


@bp.app_errorhandler(413)
def too_large(error):
    flash("That upload is too big. Please use an image under 1 MB.")
    return redirect(url_for("settings.index"))
