import html
import os
import sqlite3

import pytest

from app.db import init_db
from app.services import customers as people
from tests.test_auth import create
from tests.test_inventory import add


def setup(client):
    create(client)
    add(client, name="Tray", price="450", stock="500")


def page(client, url):
    return html.unescape(client.get(url).data.decode())


def page_of(res):
    return html.unescape(res.data.decode())


def post_bill(client, name="", phone="", qty=1, **extra):
    body = {"items": [{"product_id": 1, "quantity": qty}], "customer": name, "phone": phone,
            "order_source": "Walk-in", "payments": [{"mode": "Cash"}], **extra}
    res = client.post("/billing/save", json=body)
    assert res.status_code == 200, res.get_json()
    return res


def database(app):
    db = sqlite3.connect(app.config["DATABASE"])
    db.row_factory = sqlite3.Row
    return db


def rows(client, url="/customers"):
    """The names in the Customer Details table, top to bottom."""
    import re
    return re.findall(r'<td><a href="/customers/\d+">([^<]+)</a></td>', page(client, url))


def bill(app, bill_id):
    return database(app).execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()


# ---- phone numbers ----

@pytest.mark.parametrize("typed", ["98765 43210", "9876543210", "+91 98765 43210", "+91-98765-43210",
                                   "09876543210", "(98765) 43210", "0091 98765 43210", "91 98765 43210"])
def test_every_way_of_typing_a_number_is_the_same_customer(client, app, typed):
    setup(client)
    post_bill(client, "Asha", "9876543210")
    post_bill(client, "Asha again", typed)
    assert len(rows(client)) == 1
    assert database(app).execute("SELECT phone FROM customers").fetchone()[0] == "9876543210"
    assert people.normalize_phone(typed) == ("9876543210", None)


@pytest.mark.parametrize("typed", ["5123456789", "98765", "1234567890123", "abc", "011 2345 6789"])
def test_only_indian_mobile_numbers_are_accepted(client, typed):
    setup(client)
    res = client.post("/billing/save", json={"items": [{"product_id": 1, "quantity": 1}],
                                             "customer": "Asha", "phone": typed,
                                             "order_source": "Walk-in", "payments": [{"mode": "Cash"}]})
    assert res.status_code == 400 and "10-digit mobile" in res.get_json()["error"]
    assert "No customers yet" in page(client, "/customers")


def test_there_is_no_other_phone_anywhere(client):
    setup(client)
    post_bill(client, "Asha", "9876543210")
    for url in ("/billing", "/customers", "/customers/1", "/bills/1/customer"):
        assert "Other phone" not in page(client, url) and "other_phone" not in page(client, url)


# ---- identity is the id ----

def test_two_people_with_the_same_name_are_two_rows(client):
    setup(client)
    post_bill(client, "Asha Rao", "9876543210")
    post_bill(client, "Asha Rao", "9123456780")                 # same day, same name, other person
    assert rows(client) == ["Asha Rao", "Asha Rao"]
    ids = {c["id"] for c in client.get("/customers/search?q=Asha").get_json()["customers"]}
    assert len(ids) == 2


def test_same_name_without_phone_makes_separate_customers_unless_you_pick_one(client, app):
    setup(client)
    post_bill(client, "Meena")
    post_bill(client, "Meena")                                  # "Add as new customer"
    assert rows(client) == ["Meena", "Meena"]
    first = client.get("/customers/search?q=Meena").get_json()["customers"][0]["id"]
    post_bill(client, "Meena", customer_id=first)               # picked an existing one
    assert rows(client) == ["Meena", "Meena"]
    assert database(app).execute("SELECT COUNT(*) FROM bills WHERE customer_id = ?", (first,)).fetchone()[0] == 2


def test_changing_one_bills_phone_leaves_the_other_bill_unchanged(client, app):
    setup(client)
    post_bill(client, "Asha", "9876543210", location="Indiranagar")
    post_bill(client, "Asha", "9876543210")
    client.post("/bills/1/customer", data={
        "name": "Asha", "phone": "9123456780", "other_phone": "", "location": "Indiranagar",
        "place": "Karnataka", "place_other": "", "customer_type": "Retail"}, follow_redirects=True)
    one, two = bill(app, 1), bill(app, 2)
    assert one["customer_phone"] == "9123456780" and two["customer_phone"] == "9876543210"
    assert one["customer_id"] == two["customer_id"]                # still linked the same
    record = database(app).execute("SELECT phone FROM customers").fetchone()[0]
    assert record == "9876543210"                                  # the customer record is not touched
    assert "9876543210" in page(client, "/bills/2") and "9123456780" not in page(client, "/bills/2")


def test_a_bill_with_no_name_is_refused(client, app):
    setup(client)
    for name in ("", "   "):
        res = client.post("/billing/save", json={
            "items": [{"product_id": 1, "quantity": 1}], "customer": name, "phone": "",
            "order_source": "Walk-in", "payments": [{"mode": "Cash"}]})
        assert res.status_code == 400 and "customer's name" in res.get_json()["error"]
    db = database(app)
    assert db.execute("SELECT COUNT(*) FROM bills").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0
    assert "No customers yet" in page(client, "/customers")


def test_a_name_without_a_phone_makes_a_customer_without_a_phone(client, app):
    setup(client)
    post_bill(client, "Meena", location="Jayanagar")
    p = page(client, "/customers")
    assert "Meena" in p and "No phone" in p and "No phone, older bill" not in p
    assert tuple(database(app).execute("SELECT phone, legacy FROM customers").fetchone()) == ("", 0)


def test_an_existing_phone_is_that_customer_never_a_duplicate(client, app):
    setup(client)
    post_bill(client, "Asha Rao", "9876543210", location="Indiranagar")
    post_bill(client, "Asha R", "98765 43210", location="Jayanagar")          # typed a different name
    db = database(app)
    assert db.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 1
    record = db.execute("SELECT name, location FROM customers").fetchone()
    assert (record["name"], record["location"]) == ("Asha Rao", "Indiranagar")   # a bill never edits it
    assert bill(app, 2)["customer_name"] == "Asha R"                          # the bill prints what was typed
    assert bill(app, 2)["customer_location"] == "Jayanagar"
    assert "Asha R" in page(client, "/bills/2")


def test_a_picked_customer_cannot_be_given_someone_elses_number(client):
    setup(client)
    post_bill(client, "Asha", "9876543210")
    post_bill(client, "Ravi", "9123456780")
    asha = client.get("/customers/lookup?phone=9876543210").get_json()["id"]
    res = client.post("/billing/save", json={
        "items": [{"product_id": 1, "quantity": 1}], "customer": "Asha", "phone": "9123456780",
        "customer_id": asha, "order_source": "Walk-in", "payments": [{"mode": "Cash"}]})
    assert res.status_code == 400 and "belongs to Ravi" in res.get_json()["error"]


def test_a_new_number_needs_a_name(client):
    setup(client)
    res = client.post("/billing/save", json={
        "items": [{"product_id": 1, "quantity": 1}], "customer": "", "phone": "9876543210",
        "order_source": "Walk-in", "payments": [{"mode": "Cash"}]})
    assert res.status_code == 400 and "name for a new phone" in res.get_json()["error"]


def test_a_failed_bill_leaves_no_customer_behind(client):
    setup(client)
    res = client.post("/billing/save", json={
        "items": [{"product_id": 1, "quantity": 999}], "customer": "Asha", "phone": "9876543210",
        "order_source": "Walk-in", "payments": [{"mode": "Cash"}]})
    assert res.status_code == 400
    assert "No customers yet" in page(client, "/customers")


# ---- Billing: finding customers ----

def test_lookup_finds_by_phone_only_and_shows_the_last_bill(client):
    setup(client)
    post_bill(client, "Asha", "9876543210", location="Indiranagar", qty=2, customer_type="B2B")
    found = client.get("/customers/lookup?phone=%2B91%2098765%2043210").get_json()
    assert found["found"] and found["name"] == "Asha" and found["location"] == "Indiranagar"
    assert found["customer_type"] == "B2B" and found["bill_count"] == 1
    assert found["total"] == "₹900.00" and found["last_bill"]
    assert client.get("/customers/lookup?phone=Asha").get_json()["found"] is False
    assert client.get("/customers/lookup?phone=9999999999").get_json() == {"found": False}
    assert client.get("/customers/lookup?phone=").get_json() == {"found": False}
    bad = client.get("/customers/lookup?phone=5123456789").get_json()
    assert bad["found"] is False and "10-digit mobile" in bad["error"]


def test_name_search_lists_matches_including_customers_without_a_phone(client):
    setup(client)
    post_bill(client, "Asha Rao", "9876543210", location="Indiranagar")
    post_bill(client, "Asha Kumar")                              # no phone
    post_bill(client, "Ravi", "9123456780")
    found = client.get("/customers/search?q=asha").get_json()["customers"]
    assert sorted(c["name"] for c in found) == ["Asha Kumar", "Asha Rao"]
    rao = next(c for c in found if c["name"] == "Asha Rao")
    assert rao["phone"] == "9876543210" and rao["location"] == "Indiranagar" and rao["last_bill"]
    assert [c["name"] for c in client.get("/customers/search?q=98765").get_json()["customers"]] == ["Asha Rao"]
    assert len(client.get("/customers/search?q=").get_json()["customers"]) == 3     # recent ones


def test_search_and_lookup_stay_inside_the_shop(client):
    setup(client)
    post_bill(client, "Asha", "9876543210")
    client.get("/logout")
    create(client, login="two@example.com", shop="Other Shop")
    assert client.get("/customers/lookup?phone=9876543210").get_json()["found"] is False
    assert client.get("/customers/search?q=Asha").get_json()["customers"] == []
    assert client.get("/customers/1").status_code == 404
    res = client.post("/billing/save", json={
        "items": [], "customer": "x", "customer_id": 1, "order_source": "Walk-in", "payments": []})
    assert res.status_code == 400


# ---- Customer Details ----

def test_empty_state_menu_tab_search_sort_and_bills_link(client):
    setup(client)
    assert "No customers yet" in page(client, "/customers")
    post_bill(client, "Small", "9000000001", qty=1)
    post_bill(client, "Big", "9000000002", qty=5)
    post_bill(client, "Medium", "9000000003", qty=3)
    assert "Customer Details" in page(client, "/customers")
    assert rows(client, "/customers?sort=high") == ["Big", "Medium", "Small"]
    assert rows(client, "/customers?sort=low") == ["Small", "Medium", "Big"]
    assert rows(client, "/customers?sort=name") == ["Big", "Medium", "Small"]
    assert rows(client, "/customers?q=9000000002") == ["Big"]
    assert "No customers match" in page(client, "/customers?q=zzz")
    bills = page(client, "/bills?customer=2")
    assert "Big" in bills and "Small" not in bills


def test_editing_the_customer_record_is_for_future_bills_only(client, app):
    setup(client)
    post_bill(client, "Asha", "9876543210", location="Indiranagar")
    cid = client.get("/customers/lookup?phone=9876543210").get_json()["id"]
    assert "future bills" in page(client, f"/customers/{cid}")
    res = client.post(f"/customers/{cid}", data={
        "name": "Asha Rao", "phone": "98123 45678", "other_phone": "080 1111 2222",
        "location": "Jayanagar", "customer_type": "B2B"}, follow_redirects=True)
    assert "keep what was printed" in page_of(res)
    record = database(app).execute("SELECT * FROM customers").fetchone()
    assert (record["name"], record["phone"], record["location"], record["customer_type"]) == (
        "Asha Rao", "9812345678", "Jayanagar", "B2B")
    old = bill(app, 1)                                       # the bill still says what it printed
    assert (old["customer_name"], old["customer_phone"], old["customer_location"]) == (
        "Asha", "9876543210", "Indiranagar")
    post_bill(client, "Asha Rao", "9812345678")              # the new number now finds her
    assert len(rows(client)) == 1


# ---- Edit customer on a bill ----

def test_bill_page_buttons(client):
    setup(client)
    post_bill(client, "Asha")
    p = page(client, "/bills/1")
    assert ">Edit customer<" in p and ">Edit product<" in p and ">Print<" in p
    assert ">New bill<" not in p


def test_edit_customer_on_a_bill_changes_only_that_bill(client, app):
    setup(client)
    post_bill(client, "Asha", "9876543210", qty=2)
    before = bill(app, 1)
    stock_before = database(app).execute("SELECT stock FROM products").fetchone()[0]
    p = page(client, "/bills/1/customer")
    assert 'value="Asha"' in p and "this bill" in p and "stay exactly as they are" in p
    res = client.post("/bills/1/customer", data={
        "name": "Asha Rao", "phone": "+91 98765 43210",
        "location": "Indiranagar", "place": "Kerala", "place_other": "", "customer_type": "B2B"},
        follow_redirects=True)
    assert "this bill only" in page_of(res)
    after = bill(app, 1)
    assert (after["customer_name"], after["customer_phone"], after["customer_location"],
            after["place_of_sale"], after["customer_type"]) == (
        "Asha Rao", "9876543210", "Indiranagar", "Kerala", "B2B")
    for field in ("bill_label", "total", "status", "invoice_number", "replaced_by", "replaces", "customer_id"):
        assert after[field] == before[field]
    db = database(app)
    assert db.execute("SELECT stock FROM products").fetchone()[0] == stock_before
    assert db.execute("SELECT COUNT(*) FROM bills").fetchone()[0] == 1
    assert db.execute("SELECT name FROM customers").fetchone()[0] == "Asha"   # the record is not touched


def test_edit_customer_other_state_and_checks(client):
    setup(client)
    post_bill(client, "Asha")
    client.post("/bills/1/customer", data={"name": "Asha", "phone": "", "location": "",
                                           "place": "Other", "place_other": "Singapore",
                                           "customer_type": "Retail"})
    assert "Singapore" in page(client, "/bills/1/customer")
    for data, message in [({"name": " "}, "enter the customer"), ({"phone": "123"}, "10-digit mobile"),
                          ({"customer_type": "X"}, "Retail or B2B"),
                          ({"place": "Other", "place_other": ""}, "type the state")]:
        body = {"name": "Asha", "phone": "", "location": "", "place": "Karnataka",
                "place_other": "", "customer_type": "Retail", **data}
        assert message in page_of(client.post("/bills/1/customer", data=body))


def test_edit_customer_works_on_cancelled_and_walk_in_bills_and_stays_in_the_shop(client, app):
    setup(client)
    post_bill(client, "Asha")
    post_bill(client, "Temp")
    db = sqlite3.connect(app.config["DATABASE"])          # an older walk-in bill
    db.execute("UPDATE bills SET customer_id = 0, customer_name = 'Walk-in customer' WHERE id = 2")
    db.commit()
    db.close()
    client.post("/bills/1/cancel")
    assert client.get("/bills/1/customer").status_code == 200
    client.post("/bills/2/customer", data={"name": "", "phone": "", "place": "Karnataka",
                                           "customer_type": "Retail"})
    assert bill(app, 2)["customer_name"] == "Walk-in customer"        # still a walk-in
    client.get("/logout")
    create(client, login="two@example.com", shop="Other Shop")
    assert client.get("/bills/1/customer").status_code == 404
    assert client.post("/bills/1/customer", data={"name": "Hacker"}).status_code == 404


# ---- the upgrade of an existing database ----

def old_style(app):
    """Turn the new customers table back into the old one (found by name, phone_key) and add
    the kind of rows the old app made, so the upgrade has something real to work on."""
    db = database(app)
    db.executescript("""
        DROP INDEX IF EXISTS customers_phone_unique;
        DROP TABLE customers;
        CREATE TABLE customers (id INTEGER PRIMARY KEY AUTOINCREMENT, shop_id INTEGER NOT NULL,
            name TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '', phone_key TEXT NOT NULL DEFAULT '',
            location TEXT NOT NULL DEFAULT '', customer_type TEXT NOT NULL DEFAULT 'Retail');
        CREATE INDEX customers_phone ON customers (shop_id, phone_key);
        INSERT INTO customers VALUES (1, 1, 'Asha', '98765 43210', '9876543210', 'Indiranagar', 'Retail');
        INSERT INTO customers VALUES (2, 1, 'Asha K', '+91 9876543210', '919876543210', '', 'Retail');
        INSERT INTO customers VALUES (3, 1, 'Ravi', '', '', 'Jayanagar', 'Retail');
        INSERT INTO customers VALUES (4, 1, 'Lal', '011 2345 6789', '01123456789', '', 'B2B');
        INSERT INTO customers VALUES (5, 1, 'Meena', '99000 11122', '9900011122', '', 'Retail');
        UPDATE bills SET customer_id = id;""")
    db.commit()
    db.close()


def test_the_upgrade_keeps_customers_and_links_every_bill(client, app, capsys):
    setup(client)
    for name in ("Asha", "Asha K", "Ravi", "Lal", "Meena"):
        post_bill(client, name)
    old_style(app)
    printed_before = [tuple(r) for r in database(app).execute(
        "SELECT customer_name, customer_phone, customer_location FROM bills ORDER BY id")]
    with app.app_context():
        init_db()
    db = database(app)
    got = {r["id"]: r for r in db.execute("SELECT * FROM customers")}
    assert sorted(got) == [1, 3, 4, 5]                                # 2 was the same number as 1
    assert got[1]["phone"] == "9876543210" and got[1]["name"] == "Asha" and got[1]["legacy"] == 0
    assert got[1]["location"] == "Indiranagar"
    assert got[5]["phone"] == "9900011122"
    assert (got[3]["phone"], got[3]["legacy"]) == ("", 1)             # No phone, older bill
    assert (got[4]["phone"], got[4]["other_phone"], got[4]["legacy"]) == ("", "011 2345 6789", 1)
    links = [r[0] for r in db.execute("SELECT customer_id FROM bills ORDER BY id")]
    assert links == [1, 1, 3, 4, 5]                                   # every bill still linked
    assert [tuple(r) for r in db.execute(
        "SELECT customer_name, customer_phone, customer_location FROM bills ORDER BY id")] == printed_before
    assert "phone_key" not in [r[1] for r in db.execute("PRAGMA table_info(customers)")]
    assert db.execute("SELECT COUNT(*) FROM bills").fetchone()[0] == 5
    folder = os.path.dirname(app.config["DATABASE"])
    backups = [f for f in os.listdir(folder) if "backup" in f]
    assert len(backups) == 1                                          # a dated backup was made first
    saved = sqlite3.connect(os.path.join(folder, backups[0]))
    assert "phone_key" in [r[1] for r in saved.execute("PRAGMA table_info(customers)")]   # the old shape
    assert "Customer upgrade done" in capsys.readouterr().out
    # the phone rule is enforced by the database from now on
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO customers (shop_id, name, phone) VALUES (1, 'Dup', '9876543210')")
    # running it again changes nothing and makes no second backup
    with app.app_context():
        init_db()
    assert len([f for f in os.listdir(folder) if "backup" in f]) == 1
    assert sorted(r[0] for r in database(app).execute("SELECT id FROM customers")) == [1, 3, 4, 5]


def test_the_upgrade_shows_old_customers_correctly_on_the_page(client, app):
    setup(client)
    for name in ("A", "B", "Ravi", "Lal"):                 # bills 3 and 4 belong to customers 3 and 4
        post_bill(client, name)
    old_style(app)
    db = database(app)
    db.execute("DELETE FROM customers WHERE id IN (1, 2, 5)")
    db.commit()
    with app.app_context():
        init_db()
    p = page(client, "/customers")
    assert p.count("No phone, older bill") == 2
    post_bill(client, "New person")                                   # a new no-phone customer
    assert page(client, "/customers").count("No phone, older bill") == 2


def test_a_customer_with_no_bills_can_be_removed_but_one_with_bills_cannot(client, app):
    setup(client)
    post_bill(client, "Asha", "9876543210")
    db = database(app)
    db.execute("INSERT INTO customers (shop_id, name, phone) VALUES (1, 'Nobody Yet', '9123456780')")
    db.commit()
    asha = client.get("/customers/lookup?phone=9876543210").get_json()["id"]
    nobody = client.get("/customers/lookup?phone=9123456780").get_json()["id"]
    assert "has bills" in page_of(client.post(f"/customers/{asha}/delete", follow_redirects=True))
    assert len(rows(client, "/customers?date_from=&date_to=")) == 2
    client.post(f"/customers/{nobody}/delete")
    assert rows(client) == ["Asha"]


def test_there_are_no_manual_merge_or_move_tools(client):
    setup(client)
    post_bill(client, "Asha", "9876543210")
    post_bill(client, "Ravi", "9123456780")
    for url in ("/customers/1", "/customers/2", "/bills/1/customer", "/bills/1", "/customers"):
        p = page(client, url)
        assert "Merge" not in p and "Move bill" not in p and "merge" not in p.lower().replace("emerge", "")
    assert client.get("/customers/1/merge?into=2").status_code == 404
    assert client.post("/bills/1/move", data={"customer_id": 2}).status_code == 404
