from tests.test_auth import create
from tests.test_bills import make_bill
from tests.test_inventory import add


def setup(client):
    create(client)
    add(client, name="Tray", price="450", stock="50")


def customers(client):
    return client.get("/customers").data.decode()


def test_empty_state_and_menu_tab(client):
    setup(client)
    page = customers(client)
    assert "No customers yet" in page and "Customer Details" in page


def test_a_bill_saves_its_customer_and_the_same_phone_is_one_customer(client):
    setup(client)
    make_bill(client, "Asha", phone="98765 43210")
    make_bill(client, "Asha K", phone="9876543210")               # same number, spaced differently
    page = customers(client)
    assert page.count("<td>Asha K</td>") == 1 and "<td>Asha</td>" not in page
    assert ">2</a>" in page                                         # two bills, one customer


def test_no_phone_saves_under_the_plain_name(client):
    setup(client)
    make_bill(client, "Ravi")
    make_bill(client, "ravi")                                       # same label, any capitals
    make_bill(client, "Meena")
    page = customers(client)
    assert "<td>Meena</td>" in page and page.lower().count("<td>ravi</td>") == 1
    assert "Retail -" not in page


def test_b2b_without_a_phone_also_keeps_the_plain_name(client):
    setup(client)
    client.post("/billing/save", json={
        "items": [{"product_id": 1, "quantity": 1}], "customer": "Sharma Stores",
        "order_source": "Instagram", "payments": [{"mode": "Cash"}], "customer_type": "B2B"})
    page = customers(client)
    assert "<td>Sharma Stores</td>" in page and "B2B -" not in page and "<td>B2B</td>" in page


def test_lookup_is_by_phone_only(client):
    setup(client)
    client.post("/billing/save", json={
        "items": [{"product_id": 1, "quantity": 1}], "customer": "Asha", "phone": "98765 43210",
        "location": "Indiranagar", "order_source": "Instagram", "payments": [{"mode": "Cash"}],
        "customer_type": "B2B"})
    found = client.get("/customers/lookup?phone=9876543210").get_json()
    assert found == {"found": True, "name": "Asha", "location": "Indiranagar",
                     "customer_type": "B2B"}
    assert client.get("/customers/lookup?phone=Asha").get_json() == {"found": False}
    assert client.get("/customers/lookup?phone=").get_json() == {"found": False}
    assert client.get("/customers/lookup?phone=9999999999").get_json() == {"found": False}


def test_a_blank_location_does_not_wipe_the_saved_one(client):
    setup(client)
    body = {"items": [{"product_id": 1, "quantity": 1}], "customer": "Asha",
            "phone": "9876543210", "order_source": "Instagram", "payments": [{"mode": "Cash"}]}
    client.post("/billing/save", json={**body, "location": "Indiranagar"})
    client.post("/billing/save", json=body)
    assert client.get("/customers/lookup?phone=9876543210").get_json()["location"] == "Indiranagar"


def test_search_and_bills_link(client):
    setup(client)
    make_bill(client, "Asha", phone="9876543210")
    make_bill(client, "Ravi")
    assert "Asha" in customers(client)
    page = client.get("/customers?q=9876").data.decode()
    assert "Asha" in page and "Ravi" not in page
    assert "No customers match" in client.get("/customers?q=zzz").data.decode()
    bills = client.get("/bills?customer=1").data.decode()
    assert "Asha" in bills and "Ravi" not in bills


def test_failed_bill_saves_no_customer(client):
    setup(client)
    res = client.post("/billing/save", json={
        "items": [{"product_id": 1, "quantity": 999}], "customer": "Asha", "phone": "9876543210",
        "order_source": "Instagram", "payments": [{"mode": "Cash"}]})
    assert res.status_code == 400
    assert "No customers yet" in customers(client)


def test_customers_are_kept_separate_between_shops(client):
    setup(client)
    make_bill(client, "Asha", phone="9876543210")
    client.get("/logout")
    create(client, login="two@example.com", shop="Other Shop")
    assert client.get("/customers/lookup?phone=9876543210").get_json() == {"found": False}
    assert "Asha" not in customers(client)


# ---- sorting by total billed ----

def test_sort_by_total_billed(client):
    setup(client)
    make_bill(client, "Small", qty=1)
    make_bill(client, "Big", qty=5)
    make_bill(client, "Medium", qty=3)

    def order(sort):
        page = client.get(f"/customers?sort={sort}").data.decode()
        return [n for n in ("Small", "Medium", "Big") if n in page], sorted(
            ((page.index(f"<td>{n}</td>"), n) for n in ("Small", "Medium", "Big")))

    assert [n for _, n in order("high")[1]] == ["Big", "Medium", "Small"]
    assert [n for _, n in order("low")[1]] == ["Small", "Medium", "Big"]
    assert [n for _, n in order("name")[1]] == ["Big", "Medium", "Small"]       # A to Z
    assert "highest to lowest" in client.get("/customers").data.decode()


# ---- edit customer on a saved bill ----

def bill_row(app, bill_id=1):
    import sqlite3
    db = sqlite3.connect(app.config["DATABASE"])
    db.row_factory = sqlite3.Row
    return db.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone(), db


def test_bill_page_buttons(client):
    setup(client)
    make_bill(client, "Asha")
    page = client.get("/bills/1").data.decode()
    assert ">Edit customer<" in page and ">Edit product<" in page and ">Print<" in page
    assert ">Past bills<" not in page.split("paper-head")[0].split("<main")[1]
    assert ">New bill<" not in page


def test_edit_customer_changes_only_the_customer(client, app):
    setup(client)
    make_bill(client, "Asha", qty=2, phone="9876543210")
    before, db = bill_row(app)
    stock_before = db.execute("SELECT stock FROM products").fetchone()[0]
    page = client.get("/bills/1/customer").data.decode()
    assert 'value="Asha"' in page and "stay exactly as they are" in page
    res = client.post("/bills/1/customer", data={
        "name": "Asha Rao", "phone": "98765 43210", "location": "Indiranagar",
        "place": "Kerala", "place_other": "", "customer_type": "B2B"}, follow_redirects=True)
    assert b"Customer details updated" in res.data and b"Asha Rao" in res.data
    after, db = bill_row(app)
    assert (after["customer_name"], after["customer_location"], after["place_of_sale"],
            after["customer_type"]) == ("Asha Rao", "Indiranagar", "Kerala", "B2B")
    for field in ("bill_label", "total", "status", "invoice_number", "replaced_by", "replaces"):
        assert after[field] == before[field]                    # nothing about the bill itself
    assert db.execute("SELECT stock FROM products").fetchone()[0] == stock_before
    assert db.execute("SELECT COUNT(*) FROM bills").fetchone()[0] == 1       # no replacement bill
    assert db.execute("SELECT COUNT(*) FROM bill_lines").fetchone()[0] == 1
    customers_page = client.get("/customers").data.decode()
    assert "Asha Rao" in customers_page and customers_page.count("<td>Asha Rao</td>") == 1


def test_edit_customer_fixes_a_mistyped_name_without_leaving_a_ghost(client):
    setup(client)
    make_bill(client, "Ashaa")                                              # typo, no phone
    client.post("/bills/1/customer", data={"name": "Asha", "phone": "", "location": "",
                                           "place": "Karnataka", "customer_type": "Retail"})
    page = client.get("/customers").data.decode()
    assert page.count("<td>Asha</td>") == 1 and "Ashaa" not in page


def test_edit_customer_other_state_and_checks(client):
    setup(client)
    make_bill(client, "Asha")
    client.post("/bills/1/customer", data={"name": "Asha", "phone": "", "location": "",
                                           "place": "Other", "place_other": "Singapore",
                                           "customer_type": "Retail"})
    assert "Singapore" in client.get("/bills/1/customer").data.decode()
    for data, message in [({"name": " "}, "enter the customer"), ({"phone": "123"}, "phone number"),
                          ({"customer_type": "X"}, "Retail or B2B"),
                          ({"place": "Other", "place_other": ""}, "type the state")]:
        body = {"name": "Asha", "phone": "", "location": "", "place": "Karnataka",
                "place_other": "", "customer_type": "Retail", **data}
        assert message in client.post("/bills/1/customer", data=body).data.decode()


def test_edit_customer_works_on_cancelled_bills_and_stays_in_the_shop(client):
    setup(client)
    make_bill(client, "Asha")
    client.post("/bills/1/cancel")
    assert client.get("/bills/1/customer").status_code == 200
    client.get("/logout")
    create(client, login="two@example.com", shop="Other Shop")
    assert client.get("/bills/1/customer").status_code == 404
    assert client.post("/bills/1/customer", data={"name": "Hacker"}).status_code == 404
