from flask import Blueprint, g, render_template, request

from ..auth import login_required
from ..db import get_db
from ..services.profit import profit_figures

bp = Blueprint("profit", __name__)


@bp.route("/profit")
@login_required
def index():
    start = request.args.get("date_from", "").strip()
    end = request.args.get("date_to", "").strip()
    figures = profit_figures(get_db(), g.shop["id"], start, end)
    return render_template("profit.html", p=figures, date_from=start, date_to=end)
