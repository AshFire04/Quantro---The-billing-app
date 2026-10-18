import html
import sqlite3

from app.services.gst import breakdown, line_gst, share_out
from tests.test_auth import create
from tests.test_inventory import add


def test_gst_is_a_percentage_of_the_amount_charged():
    assert line_gst(50000, 5) == 2500                  # Rs 500 at 5% -> Rs 25.00
    assert line_gst(45000, 5) == 2250                  # Rs 450 at 5% -> Rs 22.50
    assert line_gst(10001, 5) == 500 and line_gst(10010, 5) == 501    # rounded half up to the paisa
    assert line_gst(10000, 0) == 0 and line_gst(10000, 12.5) == 1250


def test_a_whole_bill_discount_is_shared_in_proportion_with_the_last_line_taking_the_rest():
    assert share_out([10000, 20000, 30000], 1000) == [167, 333, 500]
    assert sum(share_out([3333, 3333, 3334], 100)) == 100
    assert share_out([100], 0) == [0]


def test_breakdown_adds_up_and_hides_when_every_rate_is_zero():
    lines = [{"line_amount": 11800, "gst_rate": 18}, {"line_amount": 10500, "gst_rate": 5}]
    per_line, s = breakdown(lines, 0)
    assert [p["gst"] for p in per_line] == [2124, 525]
    assert s["show"] and s["gst"] == 2649 and s["excl"] == 11800 + 10500 - 2649
    assert s["by_rate"] == [(5.0, 525), (18.0, 2124)]
    assert breakdown([{"line_amount": 5000, "gst_rate": 0}], 0)[1]["show"] is False
    assert breakdown([{"line_amount": 5000, "gst_rate": None}], 0)[1]["show"] is False


def make_bill(client, gst_a="18", gst_b="0", **extra):
    create(client)
    add(client, name="Tray", price="118", stock="10", gst_rate=gst_a)
    add(client, name="Mat", price="100", stock="10", gst_rate=gst_b)
    res = client.post("/billing/save", json={
        "items": [{"product_id": 1, "quantity": 1}, {"product_id": 2, "quantity": 1}],
        "customer": "Ravi", "order_source": "Walk-in", "payments": [{"mode": "Cash"}], **extra})
    assert res.status_code == 200
    return html.unescape(client.get("/bills/1").data.decode())


def runner_bill(client, whole=""):
    create(client)
    add(client, name="Runner", price="500", stock="10", cost_price="100", gst_rate="5")
    res = client.post("/billing/save", json={
        "items": [{"product_id": 1, "quantity": 1}], "customer": "Test", "order_source": "Walk-in",
        "payments": [{"mode": "Cash"}], "whole_discount": whole})
    assert res.status_code == 200


def profit_row(app):
    from app.db import get_db
    from app.services.profit import profit_figures
    with app.app_context():
        f = profit_figures(get_db(), 1)
    return f, f["rows"][0]


def totals_of(client):
    page = html.unescape(client.get("/bills/1").data.decode())
    return page, page[page.index('class="paper-totals"'):page.index('class="sh-foot"')]


def test_runner_example_gst_25_and_profit_375(client, app):
    runner_bill(client)
    page, totals = totals_of(client)
    assert "GST 5%: Rs 25.00" in page
    assert "Total GST</td><td>₹25.00" in totals and "Amount excluding GST</td><td>₹475.00" in totals
    assert "₹500.00" in totals                                    # the total payable is unchanged
    f, row = profit_row(app)
    assert (row["revenue"], row["cost"], row["profit"]) == (47500, 10000, 37500)
    assert f["profit"] == 37500


def test_runner_with_a_10_percent_whole_bill_discount_gst_22_50_profit_327_50(client, app):
    runner_bill(client, whole="10")
    page, totals = totals_of(client)
    assert "GST 5%: Rs 22.50" in page
    assert "Total GST</td><td>₹22.50" in totals and "Amount excluding GST</td><td>₹427.50" in totals
    assert "₹450.00" in totals
    _, row = profit_row(app)
    assert (row["revenue"], row["profit"]) == (42750, 32750)


def test_a_zero_percent_product_has_no_gst_lines_and_its_profit_is_unchanged(client, app):
    create(client)
    add(client, name="Mat", price="500", stock="10", cost_price="100", gst_rate="0")
    client.post("/billing/save", json={"items": [{"product_id": 1, "quantity": 1}], "customer": "T",
                                       "order_source": "Walk-in", "payments": [{"mode": "Cash"}]})
    page = html.unescape(client.get("/bills/1").data.decode())
    assert "GST" not in page[page.index('class="paper"'):]
    _, row = profit_row(app)
    assert (row["revenue"], row["profit"]) == (50000, 40000)


def test_an_old_bill_with_no_gst_saved_prints_none_and_keeps_its_profit(client, app):
    runner_bill(client)
    db = sqlite3.connect(app.config["DATABASE"])
    db.execute("UPDATE bill_lines SET gst_rate = 0")             # how a bill made before GST looks
    db.commit()
    db.close()
    page, _ = totals_of(client)
    assert "Total GST" not in page and "GST 5%" not in page
    _, row = profit_row(app)
    assert (row["revenue"], row["profit"]) == (50000, 40000)      # as before GST: 500 - 100


def test_later_cost_and_gst_edits_do_not_change_an_old_bills_profit_or_print(client, app):
    runner_bill(client)
    client.post("/inventory/1/edit", data={"name": "Runner", "price": "500", "stock": "9",
                                           "low_stock_level": "1", "cost_price": "300", "gst_rate": "18"})
    assert "GST 5%: Rs 25.00" in html.unescape(client.get("/bills/1").data.decode())
    _, row = profit_row(app)
    assert row["profit"] == 37500


def test_the_billing_and_past_bills_screens_show_nothing_about_gst(client):
    runner_bill(client)
    billing = html.unescape(client.get("/billing").data.decode())
    assert "gst" not in billing.lower()
    assert "gst" not in open("static/js/billing.js", encoding="utf-8").read().lower()
    assert "GST" not in html.unescape(client.get("/bills").data.decode())
    screen = html.unescape(client.get("/bills/1").data.decode())
    assert "GST" not in screen[:screen.index('class="paper"')]       # only the printed bill has it


def test_the_product_form_and_inventory_list_keep_the_gst_field(client):
    create(client)
    add(client, name="Runner", price="500", stock="5", gst_rate="5")
    assert "GST %</th>" in html.unescape(client.get("/inventory/").data.decode())
    form = html.unescape(client.get("/inventory/new").data.decode())
    assert 'name="gst_rate"' in form and "GST %" in form


def test_the_gst_percentage_and_cost_are_copied_onto_the_bill_line(client, app):
    runner_bill(client)
    db = sqlite3.connect(app.config["DATABASE"])
    assert db.execute("SELECT gst_rate, cost FROM bill_lines").fetchone() == (5.0, 10000)


def test_two_rates_show_a_breakdown_by_rate(client):
    page = make_bill(client, gst_a="18", gst_b="5")
    assert "GST 18%: Rs 21.24" in page and "GST 5%: Rs 5.00" in page


def test_the_paper_has_a5_pages_with_header_footer_and_a_gstin(client):
    make_bill(client)
    client.post("/settings/details", data={"name": "Shop", "gstin": "29abcde1234f1z5"})
    page = html.unescape(client.get("/bills/1").data.decode())
    assert "GSTIN: 29ABCDE1234F1Z5" in page and 'id="sheets"' in page and "bill_print.js" in page
    assert "Page <span" in page and "Cash / Credit Memo" in page
    bad = client.post("/settings/details", data={"name": "Shop", "gstin": "123"}, follow_redirects=True)
    assert "GSTIN should be 15" in bad.data.decode()
    css = open("static/css/print.css", encoding="utf-8").read()
    assert "size: 148mm 210mm" in css and "margin: 4mm" in css


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


def test_layout_rules_thin_lines_one_thick_border_footer_columns_and_no_oval_qty(client):
    css = open("static/css/print.css", encoding="utf-8").read()
    assert "border: 0.8mm solid #000" in css and css.count("0.8mm solid") == 1     # the one outer border
    assert "0.3mm solid #000" in css and "1px" not in css
    assert "table-layout: fixed" in css
    assert ".qty" not in css and "white-space: nowrap" in css
    js = open("static/js/bill_print.js", encoding="utf-8").read()
    assert 'class="qty"' not in js                                  # that class is the Billing screen's rounded box
    make_bill(client)
    client.post("/settings/details", data={"name": "Shop", "bank_details": "A/c 1", "terms": "1. a\n2. b"})
    page = html.unescape(client.get("/bills/1").data.decode())
    assert 'class="tot-left"' in page and "<strong>Terms:</strong><br>1. a<br>2. b" in page
    assert page.index("Bank Details:") < page.index("Terms:") < page.index("paper-thanks")
    assert page.index("Bank Details:") < page.index('class="paper-totals"')       # bank and terms sit beside the totals
    assert "GST Rate" in open("static/js/bill_print.js", encoding="utf-8").read()


def test_a_test_draft_can_be_deleted_without_leaving_a_trace(client, app):
    create(client)
    add(client, name="GST test", price="1000", stock="5", gst_rate="18")
    client.post("/billing/save", json={"items": [{"product_id": 1, "quantity": 1}], "customer": "Test",
                                       "order_source": "Walk-in", "payments": [{"mode": "Cash"}], "draft": True})
    assert "GST 18%: Rs 180.00" in html.unescape(client.get("/bills/1").data.decode())
    client.post("/bills/1/delete-draft")
    db = sqlite3.connect(app.config["DATABASE"])
    assert db.execute("SELECT COUNT(*) FROM bills").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM bill_lines").fetchone()[0] == 0
    assert db.execute("SELECT stock FROM products").fetchone()[0] == 5
