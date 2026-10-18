import functools

from flask import (Blueprint, flash, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db
from .services.choices import seed_defaults

bp = Blueprint("auth", __name__)


@bp.before_app_request
def load_user():
    """Runs before every page: who is signed in, and which shop are they in?"""
    user_id = session.get("user_id")
    g.user = g.shop = None
    if user_id is not None:
        db = get_db()
        g.user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if g.user:
            g.shop = db.execute("SELECT * FROM shops WHERE id = ?",
                                (g.user["shop_id"],)).fetchone()


# Pages only the admin sees. Logos and QR images stay open: the printed bill needs them.
ADMIN_ONLY = {"home", "inventory", "profit", "settings"}
OPEN_ENDPOINTS = {"settings.uploaded_file"}


@bp.before_app_request
def admin_mode():
    """Admin / Non-Admin work: non-admin only gets Billing, Past bills and Customer Details."""
    g.is_admin = session.get("admin", True)
    if (g.user and not g.is_admin and request.blueprint in ADMIN_ONLY
            and request.endpoint not in OPEN_ENDPOINTS):
        return redirect(url_for("billing.index"))


@bp.route("/mode", methods=("POST",))
def switch_mode():
    if g.user is None:
        return redirect(url_for("auth.login"))
    session["admin"] = not session.get("admin", True)
    return redirect(url_for("home.index" if session["admin"] else "billing.index"))


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)
    return wrapped


def placeholder(title):
    return render_template("placeholder.html", title=title)


@bp.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        login_id = request.form["login"].strip()
        password = request.form["password"]
        user = get_db().execute("SELECT * FROM users WHERE login = ?",
                                (login_id,)).fetchone()
        if user is None or not check_password_hash(user["password_hash"], password):
            # Same message either way, so it doesn't reveal which part was wrong.
            flash("That email/phone or password isn't right")
        else:
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for("index"))
    return render_template("login.html")


@bp.route("/create-shop", methods=("GET", "POST"))
def create_shop():
    if request.method == "POST":
        shop_name = request.form["shop_name"].strip()
        owner = request.form["owner_name"].strip()
        login_id = request.form["login"].strip()
        password = request.form["password"]
        db = get_db()
        error = None
        if not (shop_name and owner and login_id and password):
            error = "Please fill in every box"
        elif len(password) < 6:
            error = "Password needs at least 6 characters"
        elif db.execute("SELECT 1 FROM users WHERE login = ?", (login_id,)).fetchone():
            error = "That email/phone already has an account"
        if error:
            flash(error)
        else:
            # Shop and owner are created together, all-or-nothing.
            with db:
                shop_id = db.execute("INSERT INTO shops (name) VALUES (?)",
                                     (shop_name,)).lastrowid
                seed_defaults(db, shop_id)
                user_id = db.execute(
                    "INSERT INTO users (shop_id, name, login, password_hash) "
                    "VALUES (?, ?, ?, ?)",
                    (shop_id, owner, login_id, generate_password_hash(password)),
                ).lastrowid
            session.clear()
            session["user_id"] = user_id
            return redirect(url_for("index"))
    return render_template("create_shop.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
