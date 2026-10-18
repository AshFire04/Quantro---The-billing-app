import html
import sqlite3

from app.services.gst import breakdown, line_gst, share_out
from tests.test_auth import create
from tests.test_inventory import add


def test_gst_is_taken_out_of_a_price_that_already_includes_it():
    assert line_gst(11800, 18) == 1800                 # 118.00 incl. 18% -> 18.00 GST
    assert line_gst(10000, 5) == 476                   # 100.00 incl. 5%  -> 4.76 (4.7619 rounded)
    assert line_gst(10000, 0) == 0 and line_gst(10000, 12.5) == 1111


def test_a_whole_bill_discount_is_shared_in_proportion_with_the_last_line_taking_the_rest():
    assert share_out([10000, 20000, 30000], 1000) == [167, 333, 500]
    assert sum(share_out([3333, 3333, 3334], 100)) == 100
    assert share_out([100], 0) == [0]


def test_breakdown_adds_up_and_hides_when_every_rate_is_zero():
    lines = [{"line_amount": 11800, "gst_rate": 18}, {"line_amount": 10500, "gst_rate": 5}]
    per_line, s = breakdown(lines, 0)
    assert [p["gst"] for p in per_line] == [1800, 500]
    assert s["show"] and s["gst"] == 2300 and s["taxable"] == 11800 + 10500 - 2300
    assert s["by_rate"] == [(5.0, 500), (18.0, 1800)]
    _, discounted = breakdown(lines, 2230)             # 10% off the 22300: nets 10620 and 9450
    assert discounted["gst"] == line_gst(10620, 18) + line_gst(9450, 5)
    assert breakdown([{"line_amount": 5000, "gst_rate": 0}], 0)[1]["show"] is False
    assert breakdown([{"line_amount": 5000, "gst_rate": None}], 0)[1]["show"] is False


def make_bill(client, gst_a="18", gst_b="0"):
    create(client)
    add(client, name="Tray", price="118", stock="10", gst_rate=gst_a)
    add(client, name="Mat", price="100", stock="10", gst_rate=gst_b)
    res = client.post("/billing/save", json={
        "items": [{"product_id": 1, "quantity": 1}, {"product_id": 2, "quantity": 1}],
        "customer": "Ravi", "order_source": "Walk-in", "payments": [{"mode": "Cash"}]})
    assert res.status_code == 200
    return html.unescape(client.get("/bills/1").data.decode())


def test_the_product_gst_is_saved_on_the_bill_line_and_old_bills_never_change(client, app):
    page = make_bill(client)
    client.post("/inventory/1/edit", data={"name": "Tray", "price": "118", "stock": "9",
                                           "low_stock_level": "1", "gst_rate": "5"})
    db = sqlite3.connect(app.config["DATABASE"])
    assert db.execute("SELECT gst_rate FROM bill_lines ORDER BY id").fetchall() == [(18.0,), (0.0,)]
    assert db.execute("SELECT total FROM bills").fetchone()[0] == 21800        # GST never changes the total
    again = html.unescape(client.get("/bills/1").data.decode())
    assert "incl. GST 18%: Rs 18.00" in again and "incl. GST 5%" not in again
    assert "GST included (subtotal)" in page and "Taxable value" in page


def test_no_gst_lines_when_every_rate_is_zero_and_a_blank_gst_means_zero(client, app):
    page = make_bill(client, gst_a="", gst_b="0")
    assert "GST included" not in page and "incl. GST" not in page
    db = sqlite3.connect(app.config["DATABASE"])
    assert db.execute("SELECT gst_rate FROM products ORDER BY id").fetchall() == [(0.0,), (0.0,)]


def test_two_rates_show_a_breakdown_by_rate(client):
    page = make_bill(client, gst_a="18", gst_b="5")
    assert "GST 5%: Rs 4.76" in page and "GST 18%: Rs 18.00" in page


def test_the_paper_has_a6_pages_with_header_footer_and_a_gstin(client):
    page = make_bill(client)
    client.post("/settings/details", data={"name": "Shop", "gstin": "29abcde1234f1z5"})
    page = html.unescape(client.get("/bills/1").data.decode())
    assert "GSTIN: 29ABCDE1234F1Z5" in page and 'id="sheets"' in page and "bill_print.js" in page
    assert "Page <span" in page and "Cash / Credit Memo" in page
    bad = client.post("/settings/details", data={"name": "Shop", "gstin": "123"}, follow_redirects=True)
    assert "GSTIN should be 15" in bad.data.decode()
    css = open("static/css/print.css", encoding="utf-8").read()
    assert "size: 105mm 148mm" in css and "margin: 4mm" in css


def test_the_upgrade_adds_the_gst_columns_once_and_backs_up_first(client, app):
    make_bill(client)
    import os
    from app.db import init_db
    db = sqlite3.connect(app.config["DATABASE"])
    db.executescript("ALTER TABLE bill_lines RENAME TO old_lines;"
                     "CREATE TABLE bill_lines (id INTEGER PRIMARY KEY, bill_id INTEGER, product_id INTEGER, code TEXT,"
                     " name TEXT, quantity INTEGER, rate INTEGER, line_discount_pct REAL, line_amount INTEGER, cost INTEGER DEFAULT 0);"
                     "INSERT INTO bill_lines SELECT id, bill_id, product_id, code, name, quantity, rate, line_discount_pct,"
                     " line_amount, cost FROM old_lines; DROP TABLE old_lines;")
    db.commit()
    db.close()
    with app.app_context():
        init_db()
        init_db()                                              # a second run changes nothing
    folder = os.path.dirname(app.config["DATABASE"])
    assert [f for f in os.listdir(folder) if "before-gst" in f]
    db = sqlite3.connect(app.config["DATABASE"])
    assert db.execute("SELECT gst_rate FROM bill_lines").fetchall() == [(0.0,), (0.0,)]   # old bills: none saved
