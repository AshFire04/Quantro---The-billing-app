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
        "order_source": "Stall", "payments": [{"mode": "Cash"}], "customer_type": "B2B"})
    page = customers(client)
    assert "<td>Sharma Stores</td>" in page and "B2B -" not in page and "<td>B2B</td>" in page


def test_lookup_is_by_phone_only(client):
    setup(client)
    client.post("/billing/save", json={
        "items": [{"product_id": 1, "quantity": 1}], "customer": "Asha", "phone": "98765 43210",
        "location": "Indiranagar", "order_source": "Stall", "payments": [{"mode": "Cash"}],
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
            "phone": "9876543210", "order_source": "Stall", "payments": [{"mode": "Cash"}]}
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
        "order_source": "Stall", "payments": [{"mode": "Cash"}]})
    assert res.status_code == 400
    assert "No customers yet" in customers(client)


def test_customers_are_kept_separate_between_shops(client):
    setup(client)
    make_bill(client, "Asha", phone="9876543210")
    client.get("/logout")
    create(client, login="two@example.com", shop="Other Shop")
    assert client.get("/customers/lookup?phone=9876543210").get_json() == {"found": False}
    assert "Asha" not in customers(client)
