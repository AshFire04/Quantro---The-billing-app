import os

from flask import Flask, redirect, url_for


def create_app(test_config=None):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = Flask(
        __name__,
        instance_path=os.path.join(root, "instance"),
        template_folder=os.path.join(root, "templates"),
        static_folder=os.path.join(root, "static"),
    )
    app.config["SECRET_KEY"] = "dev-only-change-me"  # signs the sign-in cookie
    app.config["DATABASE"] = os.path.join(app.instance_path, "quantro.db")
    if test_config:
        app.config.update(test_config)

    os.makedirs(app.instance_path, exist_ok=True)

    from . import db, auth
    db.init_app(app)
    app.register_blueprint(auth.bp)

    @app.route("/")
    def index():
        return redirect(url_for("billing"))

    # Placeholder screens; each is replaced by its own slice later.
    @app.route("/billing")
    @auth.login_required
    def billing():
        return auth.placeholder("Billing")

    @app.route("/inventory")
    @auth.login_required
    def inventory():
        return auth.placeholder("Inventory")

    @app.route("/bills")
    @auth.login_required
    def bills():
        return auth.placeholder("Past bills")

    @app.route("/settings")
    @auth.login_required
    def settings():
        return auth.placeholder("Settings")

    return app
