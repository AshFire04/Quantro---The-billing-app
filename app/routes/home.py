from datetime import datetime

from flask import Blueprint, g, render_template

from ..auth import login_required
from ..db import get_db
from ..services.home import home_figures

bp = Blueprint("home", __name__)


def greeting(hour):
    return "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"


@bp.route("/home")
@login_required
def index():
    figures = home_figures(get_db(), g.shop["id"])
    return render_template("home.html", f=figures, greeting=greeting(datetime.now().hour))
