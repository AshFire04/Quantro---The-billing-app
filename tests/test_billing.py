import pytest

from app.db import get_db
from app.services.billing import BillError, price_bill, save_bill
from tests.test_auth import create
from tests.test_inventory import add


CASH = [{"mode": "Cash"}]         # one payment with no amount = the whole bill


def save(db, items, customer_name, customer_phone="", order_source="Store (walk-in)",
         payments=CASH, **more):
    """save_bill with sensible defaults, so each test only spells out what it is about."""
    return save_bill(db, 1, items, customer_name, customer_phone=customer_phone,
                     order_source=order_source, payments=payments, **more)


def stock_of(db, name):
    return db.execute("SELECT stock FROM products WHERE name = ?", (name,)).fetchone()["stock"]


@pytest.fixture
def shop(app, client):
    """A signed-in shop with two products. Yields an open database inside the app context."""
    create(client)
    add(client, code="KA36", name="Tray", price="450", stock="10")
    add(client, name="Cushion", price="299.50", stock="3")
    with app.app_context():
        yield get_db()


def test_price_is_quantity_times_rate_in_paise(shop):
    lines, total = price_bill(shop, 1, [{"product_id": 1, "quantity": 2},
                                        {"product_id": 2, "quantity": 1}])
    assert total == 2 * 45000 + 29950
    assert lines[0]["line_amount"] == 90000


def test_same_product_twice_becomes_one_line(shop):
    lines, total = price_bill(shop, 1, [{"product_id": 1, "quantity": 1},
                                        {"product_id": 1, "quantity": 2}])
    assert len(lines) == 1 and lines[0]["quantity"] == 3


def test_save_lowers_stock_and_numbers_bills(shop):
    first = save(shop, [{"product_id": 1, "quantity": 4}], "Asha")
    second = save(shop, [{"product_id": 1, "quantity": 1}], "Ravi")
    assert stock_of(shop, "Tray") == 5
    numbers = [r["invoice_number"] for r in shop.execute(
        "SELECT invoice_number FROM bills ORDER BY id")]
    assert numbers == [1, 2] and first != second
    line = shop.execute("SELECT * FROM bill_lines WHERE bill_id = ?", (first,)).fetchone()
    assert (line["code"], line["name"], line["rate"]) == ("KA36", "Tray", 45000)


def test_overselling_is_refused_and_changes_nothing(shop):
    with pytest.raises(BillError, match="Only 3 left of Cushion"):
        save(shop, [{"product_id": 1, "quantity": 2}, {"product_id": 2, "quantity": 4}], "Asha")
    assert stock_of(shop, "Tray") == 10 and stock_of(shop, "Cushion") == 3
    assert shop.execute("SELECT COUNT(*) FROM bills").fetchone()[0] == 0


def test_stale_page_cannot_sell_the_last_item(shop):
    # The server checks the real stock inside the save, even if the page was out of date.
    save(shop, [{"product_id": 2, "quantity": 3}], "Asha")
    with pytest.raises(BillError):
        save(shop, [{"product_id": 2, "quantity": 1}], "Asha")
    assert stock_of(shop, "Cushion") == 0


def test_failure_halfway_undoes_everything(shop):
    # Make the second stock update fail after the first has already happened.
    shop.execute("CREATE TRIGGER boom BEFORE UPDATE ON products WHEN NEW.id = 2 "
                 "BEGIN SELECT RAISE(ABORT, 'boom'); END")
    with pytest.raises(BillError, match="nothing was changed"):
        save(shop, [{"product_id": 1, "quantity": 2}, {"product_id": 2, "quantity": 1}], "Asha")
    assert stock_of(shop, "Tray") == 10 and stock_of(shop, "Cushion") == 3
    assert shop.execute("SELECT COUNT(*) FROM bills").fetchone()[0] == 0
    assert shop.execute("SELECT next_invoice_number FROM shops").fetchone()[0] == 1


@pytest.mark.parametrize("items", [[], [{"product_id": 1, "quantity": 0}],
                                   [{"product_id": 999, "quantity": 1}],
                                   [{"product_id": "x", "quantity": 1}]])
def test_bad_bills_are_refused(shop, items):
    with pytest.raises(BillError):
        save(shop, items, "Asha")


def test_save_through_the_website(client):
    create(client)
    add(client, name="Tray", price="450", stock="5")
    assert b"Tray" in client.get("/billing").data
    res = client.post("/billing/save", json={"items": [{"product_id": 1, "quantity": 2}],
                                             "customer": "Asha", "phone": "98765 43210", "place_of_sale": "Karnataka",
                                             "order_source": "Website", "payments": CASH})
    assert res.status_code == 200
    page = client.get(res.get_json()["url"]).data
    assert b"Asha" in page and b"Website" in page and b"Cash" in page and b"98765 43210" in page and "₹900.00".encode() in page
    assert b"<td class=\"num mono\">3</td>" not in page  # stock is on Inventory, not the bill
    assert b">3<" in client.get("/inventory/").data
    bad = client.post("/billing/save", json={"items": [{"product_id": 1, "quantity": 9}], "customer": "Asha",
                                             "order_source": "Stall", "payments": CASH})
    assert bad.status_code == 400 and "Only 3 left" in bad.get_json()["error"]


def test_cannot_bill_another_shops_product(client):
    create(client)
    add(client, name="Tray", stock="5")
    client.get("/logout")
    create(client, login="other@example.com", shop="Other shop")
    res = client.post("/billing/save", json={"items": [{"product_id": 1, "quantity": 1}], "customer": "Asha",
                                             "order_source": "Stall", "payments": CASH})
    assert res.status_code == 400
    assert client.get("/bills/1").status_code == 404


def test_customer_name_is_required_and_phone_is_optional(shop):
    items = [{"product_id": 1, "quantity": 1}]
    with pytest.raises(BillError, match="customer's name"):
        save(shop, items, "   ")
    with pytest.raises(BillError, match="phone number"):
        save(shop, items, "Asha", customer_phone="12ab")
    assert stock_of(shop, "Tray") == 10
    save(shop, items, "Asha")                                # no phone: fine
    save(shop, items, "Ravi", customer_phone="+91 98765 43210")
    phones = [r[0] for r in shop.execute("SELECT customer_phone FROM bills ORDER BY id")]
    assert phones == ["", "+91 98765 43210"]


def test_order_source_and_payment_mode_are_required(shop):
    items = [{"product_id": 1, "quantity": 1}]
    with pytest.raises(BillError, match="order source"):
        save(shop, items, "Asha", order_source="")
    with pytest.raises(BillError, match="order source"):
        save(shop, items, "Asha", order_source="Other")             # 'Other' needs typed text
    with pytest.raises(BillError, match="payment mode"):
        save(shop, items, "Asha", payments=[{"mode": ""}])
    with pytest.raises(BillError, match="payment mode"):
        save(shop, items, "Asha", payments=[{"mode": "Other", "other": " "}])
    assert stock_of(shop, "Tray") == 10
    save(shop, items, "Asha", order_source="Other", order_source_other="Phone call",
         payments=[{"mode": "Other", "other": "Cheque"}])
    bill = shop.execute("SELECT * FROM bills").fetchone()
    assert bill["order_source"] == "Other: Phone call"
    assert shop.execute("SELECT mode, amount FROM payments").fetchall()[0][:] == ("Other: Cheque", 45000)


def test_single_payment_covers_the_whole_bill(shop):
    save(shop, [{"product_id": 1, "quantity": 2}], "Asha", payments=[{"mode": "UPI"}])
    rows = shop.execute("SELECT mode, amount FROM payments").fetchall()
    assert [tuple(r) for r in rows] == [("UPI", 90000)]


def test_split_payment_must_add_up_to_the_total(shop):
    items = [{"product_id": 1, "quantity": 2}]                      # total ₹900
    save(shop, items, "Asha", payments=[{"mode": "Cash", "amount": "500"},
                                        {"mode": "UPI", "amount": "400"}])
    rows = shop.execute("SELECT mode, amount FROM payments ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [("Cash", 50000), ("UPI", 40000)]
    for bad in ([{"mode": "Cash", "amount": "500"}, {"mode": "UPI", "amount": "300"}],     # short
                [{"mode": "Cash", "amount": "500"}, {"mode": "UPI", "amount": "500"}],     # over
                [{"mode": "Cash", "amount": "900"}, {"mode": "UPI", "amount": "0"}],       # zero
                [{"mode": "Cash", "amount": "900"}, {"mode": "UPI", "amount": ""}],        # blank
                [{"mode": "Cash", "amount": "abc"}, {"mode": "UPI", "amount": "400"}]):
        with pytest.raises(BillError):
            save(shop, items, "Asha", payments=bad)
    assert stock_of(shop, "Tray") == 8                              # only the good bill went through
    assert shop.execute("SELECT COUNT(*) FROM bills").fetchone()[0] == 1



def test_customer_location_is_saved_and_optional(shop):
    items = [{"product_id": 1, "quantity": 1}]
    save(shop, items, "Asha", customer_location="Indiranagar, Bengaluru")
    save(shop, items, "Ravi")
    places = [r[0] for r in shop.execute("SELECT customer_location FROM bills ORDER BY id")]
    assert places == ["Indiranagar, Bengaluru", ""]


def test_part_payment_with_the_rest_due_later(shop):
    items = [{"product_id": 1, "quantity": 2}]                      # total ₹900
    save(shop, items, "Asha", payments=[{"mode": "UPI"}], due_amount="400", due_date="2999-01-31")
    bill = shop.execute("SELECT due_amount, due_date FROM bills").fetchone()
    assert (bill["due_amount"], bill["due_date"]) == (40000, "2999-01-31")
    rows = shop.execute("SELECT mode, amount FROM payments").fetchall()
    assert [tuple(r) for r in rows] == [("UPI", 50000)]             # ₹900 - ₹400 paid now


def test_split_payment_adds_up_to_what_is_paid_now(shop):
    items = [{"product_id": 1, "quantity": 2}]                      # ₹900, ₹300 due: ₹600 now
    save(shop, items, "Asha", due_amount="300", due_date="2999-01-31",
         payments=[{"mode": "Cash", "amount": "400"}, {"mode": "UPI", "amount": "200"}])
    with pytest.raises(BillError, match="paid now"):
        save(shop, items, "Asha", due_amount="300", due_date="2999-01-31",
             payments=[{"mode": "Cash", "amount": "500"}, {"mode": "UPI", "amount": "400"}])


def test_whole_bill_due_needs_no_payment_mode(shop):
    save(shop, [{"product_id": 1, "quantity": 1}], "Asha", payments=[],
         due_amount="450", due_date="2999-01-31")
    assert shop.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 0
    assert stock_of(shop, "Tray") == 9                               # stock still drops


def test_due_rules(shop):
    items = [{"product_id": 1, "quantity": 1}]                      # ₹450
    for kwargs, message in [
        ({"due_amount": "500", "due_date": "2999-01-31"}, "more than the bill total"),
        ({"due_amount": "100", "due_date": ""}, "date the payment is due"),
        ({"due_amount": "100", "due_date": "31/01/2999"}, "date the payment is due"),
        ({"due_amount": "100", "due_date": "2000-01-01"}, "in the past"),
        ({"due_amount": "abc", "due_date": "2999-01-31"}, "as a number"),
    ]:
        with pytest.raises(BillError, match=message):
            save(shop, items, "Asha", **kwargs)
    assert stock_of(shop, "Tray") == 10
    save(shop, items, "Asha", due_amount="", due_date="")           # no due: fine


# ---- Discounts and shipping ----------------------------------------------------------
# Tray is ₹450 and Cushion is ₹299.50. Amounts below are worked out by hand.

def total_of(shop, items, whole="0", shipping=0):
    from decimal import Decimal
    return price_bill(shop, 1, items, Decimal(whole), shipping)[1]


def test_item_discount(shop):
    lines, total = price_bill(shop, 1, [{"product_id": 1, "quantity": 2, "discount": "10"}])
    assert lines[0]["line_amount"] == 81000        # 2 x 450 = 900, less 10% = 810
    assert lines[0]["line_discount_pct"] == 10 and total == 81000


def test_whole_bill_discount(shop):
    items = [{"product_id": 1, "quantity": 2}, {"product_id": 2, "quantity": 1}]
    assert total_of(shop, items, whole="5") == 113953   # 900 + 299.50 = 1199.50; 5% off = 1139.525 -> 1139.53


def test_item_discount_comes_first_then_whole_bill_discount(shop):
    # 10% off the trays (900 -> 810), cushion full price (299.50): subtotal 1109.50.
    # 5% off the whole bill: 1109.50 x 0.95 = 1054.025 -> 1054.03
    items = [{"product_id": 1, "quantity": 2, "discount": "10"}, {"product_id": 2, "quantity": 1}]
    assert total_of(shop, items, whole="5") == 105403


def test_shipping_is_added_last_and_not_discounted(shop):
    items = [{"product_id": 1, "quantity": 2, "discount": "10"}]    # 810
    assert total_of(shop, items, whole="50", shipping=8000) == 40500 + 8000   # 405 + 80 shipping


def test_rounding_is_half_up_to_the_paisa(shop):
    # ₹299.50 less 12.5% = 262.058... paise-exact: 29950 x 0.875 = 26206.25 -> 26206
    assert total_of(shop, [{"product_id": 2, "quantity": 1, "discount": "12.5"}]) == 26206
    # exactly half a paisa rounds up: 45000 x 0.99995 would need 3 decimals, so use 29950 x 0.5 = 14975
    assert total_of(shop, [{"product_id": 2, "quantity": 1, "discount": "50"}]) == 14975
    assert total_of(shop, [{"product_id": 2, "quantity": 1, "discount": "99.99"}]) == 3   # 2.995 -> 3


def test_one_hundred_percent_off_is_allowed(shop):
    assert total_of(shop, [{"product_id": 1, "quantity": 1, "discount": "100"}]) == 0


@pytest.mark.parametrize("bad", ["-1", "101", "abc", "10.555", "nan"])
def test_bad_item_discounts_are_refused(shop, bad):
    with pytest.raises(BillError, match="discount"):
        price_bill(shop, 1, [{"product_id": 1, "quantity": 1, "discount": bad}])


def test_saving_stores_the_discounts_and_shipping(shop):
    bill_id = save(shop, [{"product_id": 1, "quantity": 2, "discount": "10"},
                          {"product_id": 2, "quantity": 1}], "Asha",
                   whole_discount="5", shipping="80")
    bill = shop.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
    assert (bill["whole_discount_pct"], bill["shipping"]) == (5, 8000)
    assert bill["total"] == 105403 + 8000
    lines = shop.execute("SELECT line_discount_pct, line_amount FROM bill_lines "
                         "WHERE bill_id = ? ORDER BY id", (bill_id,)).fetchall()
    assert [tuple(l) for l in lines] == [(10, 81000), (0, 29950)]
    assert shop.execute("SELECT amount FROM payments").fetchone()[0] == 105403 + 8000


@pytest.mark.parametrize("kwargs, message", [
    ({"whole_discount": "150"}, "between 0 and 100"),
    ({"whole_discount": "x"}, "must be a number"),
    ({"shipping": "-5"}, "shipping"),
    ({"shipping": "abc"}, "shipping"),
])
def test_bad_whole_discount_or_shipping_is_refused(shop, kwargs, message):
    with pytest.raises(BillError, match=message):
        save(shop, [{"product_id": 1, "quantity": 1}], "Asha", **kwargs)
    assert stock_of(shop, "Tray") == 10


def test_due_and_split_use_the_discounted_total(shop):
    items = [{"product_id": 1, "quantity": 2, "discount": "10"}]    # 810
    save(shop, items, "Asha", whole_discount="10", due_amount="100", due_date="2999-01-31",
         payments=[{"mode": "Cash", "amount": "300"}, {"mode": "UPI", "amount": "329"}])  # 729 - 100


def test_discounts_through_the_website_and_on_the_saved_bill(client):
    create(client)
    add(client, name="Tray", price="450", stock="10")
    res = client.post("/billing/save", json={
        "items": [{"product_id": 1, "quantity": 2, "discount": "10"}], "customer": "Asha",
        "order_source": "Stall", "payments": CASH, "whole_discount": "5", "shipping": "80"})
    assert res.status_code == 200
    page = client.get(res.get_json()["url"]).data.decode()
    assert "₹900.00" in page and "₹810.00" in page and "10% off" in page   # original, then discounted
    assert "Whole-bill discount (5%)" in page and "−₹40.50" in page
    assert "Shipping &amp; handling" in page and "₹80.00" in page
    assert "₹849.50" in page                                               # 810 - 40.50 + 80
    bad = client.post("/billing/save", json={
        "items": [{"product_id": 1, "quantity": 1, "discount": "250"}], "customer": "Asha",
        "order_source": "Stall", "payments": CASH})
    assert bad.status_code == 400 and "between 0 and 100" in bad.get_json()["error"]
