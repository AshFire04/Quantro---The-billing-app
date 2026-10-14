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

    from .routes import inventory, billing, bills as bills_routes
    app.register_blueprint(inventory.bp)
    app.register_blueprint(billing.bp)
    app.register_blueprint(bills_routes.bp)

    from .services.money import format_date, format_rupees
    app.jinja_env.filters["rupees"] = format_rupees
    app.jinja_env.filters["fdate"] = format_date

    @app.route("/")
    def index():
        return redirect(url_for("billing.index"))

    # Placeholder screens; each is replaced by its own slice later.
    @app.route("/settings")
    @auth.login_required
    def settings():
        return auth.placeholder("Settings")

    return app

