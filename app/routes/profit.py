from datetime import datetime

from flask import Blueprint, Response, g, render_template, request

from ..auth import login_required
from ..db import get_db
from ..services.export import profit_workbook
from ..services.period import date_range
from ..services.profit import profit_figures

bp = Blueprint("profit", __name__)


@bp.route("/profit")
@login_required
def index():
    start, end = date_range(request.args)
    figures = profit_figures(get_db(), g.shop["id"], start, end)
    return render_template("profit.html", p=figures, date_from=start, date_to=end)


@bp.route("/profit/export.xlsx")
@login_required
def export():
    """The same figures as the page (same dates), as an Excel file."""
    start, end = date_range(request.args)
    figures = profit_figures(get_db(), g.shop["id"], start, end)
    name = f"quantro-profit-{datetime.now():%Y-%m-%d}.xlsx"
    return Response(profit_workbook(figures, start, end),
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
