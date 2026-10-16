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
    app.config["UPLOAD_FOLDER"] = os.path.join(app.instance_path, "uploads")   # QR images
    app.config["MAX_CONTENT_LENGTH"] = 3 * 1024 * 1024   # refuse any request over 3 MB
    if test_config:
        app.config.update(test_config)

    os.makedirs(app.instance_path, exist_ok=True)

    from . import db, auth
    db.init_app(app)
    app.register_blueprint(auth.bp)

    from .routes import inventory, billing, bills as bills_routes, settings, home, customers
    app.register_blueprint(inventory.bp)
    app.register_blueprint(billing.bp)
    app.register_blueprint(bills_routes.bp)
    app.register_blueprint(settings.bp)
    app.register_blueprint(home.bp)
    app.register_blueprint(customers.bp)

    from .services.billing import bill_status
    app.jinja_env.globals["bill_status"] = bill_status
    from .services.money import format_date, format_rupees
    app.jinja_env.filters["rupees"] = format_rupees
    app.jinja_env.filters["fdate"] = format_date

    @app.route("/")
    def index():
        return redirect(url_for("home.index"))

    return app

