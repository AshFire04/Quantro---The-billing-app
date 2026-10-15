from datetime import date, datetime, timedelta

from app.db import get_db
from app.services.billing import cancel_bill
from app.services.home import home_figures, pie_slices, target_progress
from tests.test_auth import create
from tests.test_billing import save, shop   # noqa: F401  (shop is a fixture)
from tests.test_inventory import add


def set_date(db, bill_id, when):
    db.execute("UPDATE bills SET created_at = ? WHERE id = ?", (when.isoformat(timespec="seconds"), bill_id))
    db.commit()


def test_sign_in_lands_on_home(client):
    create(client)
    assert client.get("/", follow_redirects=False).headers["Location"].endswith("/home")
    assert client.get("/logout").status_code == 302
    assert client.get("/home").status_code == 302          # needs sign-in


def test_empty_home_has_no_errors(client):
    create(client)
    page = client.get("/home").data
    assert b"Nothing is running low" in page and b"No bills yet" in page
    assert b"not set a monthly target" in page and b"No stock to show yet" in page


def test_tiles_week_and_recent_match_the_bills(shop):
    today = date.today()
    a = save(shop, [{"product_id": 1, "quantity": 2}], "Asha")                 # 900.00
    b = save(shop, [{"product_id": 1, "quantity": 1}], "Ravi")                 # 450.00
    c = save(shop, [{"product_id": 1, "quantity": 1}], "Old")                  # 450.00, 3 days ago
    set_date(shop, c, datetime.now() - timedelta(days=3))
    f = home_figures(shop, 1, today)
    assert f["today_sales"] == 135000 and f["bills_today"] == 2
    assert [w["amount"] for w in f["week"]][-1] == 135000
    assert f["week"][3]["amount"] == 45000 and f["week"][-1]["height"] == 100
    assert [r["invoice_number"] for r in f["recent"]] == [3, 2, 1]
    assert f["recent"][-1]["item_count"] == 1


def test_cancelled_bills_are_left_out(shop):
    a = save(shop, [{"product_id": 1, "quantity": 2}], "Asha")
    save(shop, [{"product_id": 1, "quantity": 1}], "Ravi")
    cancel_bill(shop, 1, a)
    f = home_figures(shop, 1)
    assert f["today_sales"] == 45000 and f["bills_today"] == 1


def test_payments_pending_adds_up_the_dues(shop):
    due = (date.today() + timedelta(days=5)).isoformat()
    save(shop, [{"product_id": 1, "quantity": 2}], "Asha", due_amount="300", due_date=due)
    save(shop, [{"product_id": 1, "quantity": 1}], "Ravi", due_amount="100", due_date=due)
    save(shop, [{"product_id": 2, "quantity": 1}], "Paid in full")
    f = home_figures(shop, 1)
    assert f["pending_amount"] == 40000 and f["pending_customers"] == 2


def test_running_low_counts_low_and_out(shop):
    add_low = get_db()
    add_low.execute("UPDATE products SET low_stock_level = 3 WHERE id = 2")   # Cushion: stock 3
    add_low.commit()
    f = home_figures(shop, 1)
    assert [p["name"] for p in f["running_low"]] == ["Cushion"] and f["low_count"] == 1
    save(shop, [{"product_id": 2, "quantity": 3}], "Asha")                     # now out of stock
    assert home_figures(shop, 1)["low_count"] == 1


def test_target_and_month_sales(shop):
    shop.execute("UPDATE shops SET monthly_target = 200000 WHERE id = 1")
    shop.commit()
    save(shop, [{"product_id": 1, "quantity": 2}], "Asha")                     # 900.00
    t = home_figures(shop, 1)["target"]
    assert t["sold"] == 90000 and t["left"] == 110000 and round(t["pct"], 1) == 45.0
    assert target_progress(90000, 0) is None
    assert target_progress(300000, 200000)["pct"] == 100 and target_progress(300000, 200000)["reached"]


def test_category_pie_is_by_stock_value(app, client):
    create(client)
    add(client, name="Tray", category="Trays", price="100", stock="3")        # 300
    add(client, name="Rug", category="Rugs", price="100", stock="1")          # 100
    add(client, name="Loose", category="", price="50", stock="2")             # 100
    with app.app_context():
        slices = home_figures(get_db(), 1)["categories"]
    assert [(s["label"], s["pct"]) for s in slices][0] == ("Trays", 60.0)
    assert {s["label"] for s in slices} == {"Trays", "Rugs", "No category"}


def test_pie_groups_extra_categories():
    slices = pie_slices([(f"C{i}", 10 * (i + 1)) for i in range(8)] + [("Empty", 0)])
    assert len(slices) == 5 and slices[-1]["label"] == "Other categories"
    assert round(sum(s["pct"] for s in slices)) == 100


def test_each_shop_sees_only_its_own_figures(app, client):
    create(client)
    add(client, name="Tray", category="Trays", price="100", stock="3")
    client.get("/logout")
    create(client, login="other@example.com", shop="Other Shop")
    page = client.get("/home").data
    assert b"No stock to show yet" in page and b"Trays" not in page


def test_target_is_saved_in_shop_details(client):
    create(client)
    assert b"saved" in client.post("/settings/target", data={"monthly_target": "200000"},
                                   follow_redirects=True).data
    assert b"Sold" in client.get("/home").data
    bad = client.post("/settings/target", data={"monthly_target": "lots"}, follow_redirects=True)
    assert b"as an amount" in bad.data
