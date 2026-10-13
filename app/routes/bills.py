from flask import Blueprint, abort, g, render_template

from ..auth import login_required
from ..db import get_db

bp = Blueprint("bills", __name__)


@bp.route("/bills/<int:bill_id>")
@login_required
def view(bill_id):
    db = get_db()
    bill = db.execute("SELECT * FROM bills WHERE id = ? AND shop_id = ?",
                      (bill_id, g.shop["id"])).fetchone()
    if bill is None:
        abort(404)
    lines = db.execute("SELECT * FROM bill_lines WHERE bill_id = ? ORDER BY id",
                       (bill_id,)).fetchall()
    payments = db.execute("SELECT * FROM payments WHERE bill_id = ? ORDER BY id",
                          (bill_id,)).fetchall()
    return render_template("bill_view.html", bill=bill, lines=lines, payments=payments)
