from tests.test_auth import create
from tests.test_inventory import add

CASH = [{"mode": "Cash"}]


def make_bill(client, customer, qty=1, phone=""):
    res = client.post("/billing/save", json={
        "items": [{"product_id": 1, "quantity": qty}], "customer": customer, "phone": phone,
        "order_source": "Store (walk-in)", "payments": CASH})
    assert res.status_code == 200
    return res.get_json()["url"]


def test_empty_state(client):
    create(client)
    assert b"No bills yet" in client.get("/bills").data


def test_list_is_newest_first_with_status_and_amount(client):
    create(client)
    add(client, name="Tray", price="450", stock="10")
    make_bill(client, "Asha", qty=1)
    make_bill(client, "Ravi", qty=2)
    page = client.get("/bills").data.decode()
    assert page.index("Ravi") < page.index("Asha")          # newest first
    assert "₹900.00" in page and "₹450.00" in page and "Paid" in page


def test_search_by_number_and_by_customer(client):
    create(client)
    add(client, name="Tray", price="450", stock="10")
    make_bill(client, "Asha Rao", phone="98765 43210")
    make_bill(client, "Ravi Kumar")
    by_name = client.get("/bills?q=asha").data.decode()
    assert "Asha Rao" in by_name and "Ravi Kumar" not in by_name
    by_number = client.get("/bills?q=%232").data.decode()   # "#2"
    assert "Ravi Kumar" in by_number and "Asha Rao" not in by_number
    assert "Asha Rao" in client.get("/bills?q=98765").data.decode()   # phone
    assert b"No bills match" in client.get("/bills?q=zzz").data


def test_opening_a_bill_shows_its_details(client):
    create(client)
    add(client, name="Tray", price="450", stock="10")
    url = make_bill(client, "Asha", qty=2)
    assert b"Bill saved and stock updated" in client.get(url).data     # right after saving
    page = client.get("/bills/1").data                                 # opened from the list
    assert b"Tray" in page and b"Asha" in page and "₹900.00".encode() in page
    assert b"Bill saved and stock updated" not in page


def test_bills_are_private_to_each_shop(client):
    create(client)
    add(client, name="Tray", price="450", stock="10")
    make_bill(client, "Asha")
    client.get("/logout")
    create(client, login="other@example.com", shop="Other shop")
    assert b"Asha" not in client.get("/bills").data
    assert client.get("/bills/1").status_code == 404


def test_filters(client):
    create(client)
    add(client, name="Tray", price="450", stock="20")

    def bill(customer, source, mode, due=None):
        body = {"items": [{"product_id": 1, "quantity": 1}], "customer": customer,
                "order_source": source, "payments": [{"mode": mode}]}
        if due:
            body.update(due_amount=due, due_date="2999-01-31")
        return client.post("/billing/save", json=body)

    bill("Asha", "Website", "UPI")
    bill("Ravi", "Stall", "Cash", due="100")
    bill("Meena", "Store (walk-in)", "Net-banking")

    def names(query):
        page = client.get("/bills?" + query).data.decode()
        return [n for n in ("Asha", "Ravi", "Meena") if n in page]

    assert names("source=Website") == ["Asha"]
    assert names("source=Stall") == ["Ravi"]
    assert names("mode=Cash") == ["Ravi"]
    assert names("mode=Net-banking") == ["Meena"]
    assert names("due=due") == ["Ravi"]
    assert "₹100.00 by 31 Jan 2999" in client.get("/bills?due=due").data.decode()
    assert names("source=Website&mode=UPI") == ["Asha"]            # filters combine
    assert names("source=Website&mode=Cash") == []
    assert sorted(names("date_from=2000-01-01&date_to=2999-12-31")) == ["Asha", "Meena", "Ravi"]
    assert names("date_from=2999-01-01") == []
    assert b"No bills match these filters" in client.get("/bills?date_from=2999-01-01").data


def test_marking_a_due_payment_received(client):
    create(client)
    add(client, name="Tray", price="450", stock="20")
    client.post("/billing/save", json={
        "items": [{"product_id": 1, "quantity": 2}], "customer": "Ravi", "order_source": "Stall",
        "payments": [{"mode": "Cash"}], "due_amount": "400", "due_date": "2999-01-31"})
    page = client.get("/bills/1").data.decode()
    assert "Payment due: ₹400.00" in page and "Mark payment received" in page
    # Choosing no mode, or an 'Other' without text, is refused and changes nothing.
    assert b"payment mode" in client.post("/bills/1/payment-received", data={"mode": ""},
                                          follow_redirects=True).data
    page = client.post("/bills/1/payment-received", data={"mode": "UPI"},
                       follow_redirects=True).data.decode()
    assert "The due amount is cleared" in page
    assert "Mark payment received" not in page and "UPI ₹400.00 (received" in page
    assert "Cash ₹500.00" in page                                       # the first payment stays
    assert "Ravi" not in client.get("/bills?due=due").data.decode()     # no longer due
    assert "Ravi" in client.get("/bills?mode=UPI").data.decode()        # and counted under UPI
    # Pressing it again does nothing: there is nothing due any more.
    assert b"Nothing is due" in client.post("/bills/1/payment-received", data={"mode": "UPI"},
                                            follow_redirects=True).data


def test_cannot_clear_another_shops_due(client):
    create(client)
    add(client, name="Tray", price="450", stock="20")
    client.post("/billing/save", json={
        "items": [{"product_id": 1, "quantity": 1}], "customer": "Ravi", "order_source": "Stall",
        "payments": [{"mode": "Cash"}], "due_amount": "100", "due_date": "2999-01-31"})
    client.get("/logout")
    create(client, login="other@example.com", shop="Other shop")
    client.post("/bills/1/payment-received", data={"mode": "UPI"})
    client.get("/logout")
    client.post("/login", data={"login": "owner@example.com", "password": "secret123"})
    assert "Payment due: ₹100.00" in client.get("/bills/1").data.decode()


def test_dates_show_as_day_short_month_year_without_time(client):
    from datetime import datetime
    create(client)
    add(client, name="Tray", price="450", stock="20")
    client.post("/billing/save", json={
        "items": [{"product_id": 1, "quantity": 1}], "customer": "Ravi", "order_source": "Stall",
        "payments": [{"mode": "Cash"}], "due_amount": "100", "due_date": "2999-01-05"})
    today = datetime.now().strftime("%d %b %Y")
    for url in ("/bills", "/bills/1"):
        page = client.get(url).data.decode()
        assert today in page and "05 Jan 2999" in page
        assert "2999-01-05" not in page and datetime.now().strftime("%Y-%m-%dT") not in page
    client.post("/bills/1/payment-received", data={"mode": "UPI"})
    assert f"(received {today})" in client.get("/bills/1").data.decode()


def test_past_bills_shows_the_place_of_sale(client):
    create(client)
    add(client, name="Tray", price="450", stock="20")
    for customer, place in (("Asha", "Karnataka"), ("Ravi", "Singapore")):
        client.post("/billing/save", json={
            "items": [{"product_id": 1, "quantity": 1}], "customer": customer,
            "place_of_sale": place, "order_source": "Website", "payments": [{"mode": "UPI"}]})
    page = client.get("/bills").data.decode()
    assert "Place of sale" in page and "Karnataka" in page and "Singapore" in page


def test_status_shows_paid_payment_due_or_cancelled(client):
    import re
    create(client)
    add(client, name="Tray", price="450", stock="20")

    def bill(customer, **extra):
        body = {"items": [{"product_id": 1, "quantity": 1}], "customer": customer,
                "order_source": "Stall", "payments": [{"mode": "Cash"}]}
        body.update(extra)
        assert client.post("/billing/save", json=body).status_code == 200

    bill("Paid Pat")                                              # bill 1
    bill("Due Dan", due_amount="100", due_date="2999-01-31")      # bill 2
    bill("Cancelled Cal")                                         # bill 3
    client.post("/bills/3/cancel")

    def badge(customer):
        page = client.get("/bills").data.decode()
        row = page[page.index(customer):]
        return re.search(r'<span class="badge status-(\w+)">([^<]+)</span>', row).groups()

    assert badge("Paid Pat") == ("paid", "Paid")
    assert badge("Due Dan") == ("due", "Payment due")
    assert badge("Cancelled Cal") == ("cancelled", "Cancelled")
    # On the bill page too.
    assert 'badge status-paid">Paid' in client.get("/bills/1").data.decode()
    assert 'badge status-due">Payment due' in client.get("/bills/2").data.decode()
    assert 'badge status-cancelled">Cancelled' in client.get("/bills/3").data.decode()
    # Once the due amount is received, the bill turns Paid.
    client.post("/bills/2/payment-received", data={"mode": "UPI"})
    assert badge("Due Dan") == ("paid", "Paid")