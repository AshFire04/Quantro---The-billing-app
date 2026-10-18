"""The automatic "Is this the same person?" prompt, the combine rules and Undo."""
import html
import re
import sqlite3
import time
from datetime import date

from app.services.money import format_date
from tests.test_auth import create
from tests.test_inventory import add


def setup(client):
    create(client)
    add(client, name="Tray", price="450", stock="500")


def page(client, url):
    return html.unescape(client.get(url).data.decode())


def page_of(res):
    return html.unescape(res.data.decode())


def post_bill(client, name="", phone="", **extra):
    res = client.post("/billing/save", json={
        "items": [{"product_id": 1, "quantity": 1}], "customer": name, "phone": phone,
        "order_source": "Walk-in", "payments": [{"mode": "Cash"}], **extra})
    assert res.status_code == 200, res.get_json()


def database(app):
    db = sqlite3.connect(app.config["DATABASE"])
    db.row_factory = sqlite3.Row
    return db


def bill(app, bill_id):
    return database(app).execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()


def customers(app):
    return {r["id"]: dict(r) for r in database(app).execute("SELECT * FROM customers")}


def edit_form(phone, name="Asha", location="", action=None):
    data = {"name": name, "phone": phone, "location": location, "place": "Karnataka",
            "place_other": "", "customer_type": "Retail"}
    if action:
        data["action"] = action
    return data


def undo_token(res):
    return re.search(r'/undo/([\w-]+)"', res.data.decode()).group(1)


TODAY = format_date(date.today().isoformat())


# ---- the flow from the request ----

def test_saved_without_phone_added_again_with_phone_then_edited_combined_and_undone(client, app):
    setup(client)
    post_bill(client, "Asha", location="Indiranagar")             # bill 1: saved without a phone
    post_bill(client, "Asha Rao", "9876543210")                   # bill 2: the same person, with a phone
    assert sorted(c["name"] for c in customers(app).values()) == ["Asha", "Asha Rao"]
    assert bill(app, 1)["customer_id"] == 1 and bill(app, 2)["customer_id"] == 2

    # edit the first bill to that phone number: nothing happens yet, there is a question
    asked = client.post("/bills/1/customer", data=edit_form("98765 43210", "Asha", "Indiranagar"))
    text = page_of(asked)
    assert f"This number already belongs to Asha Rao (1 bill, last bill {TODAY}). Is this the same person?" in text
    assert "Move 1 bill of Asha to Asha Rao, and remove Asha from Customer Details." in text
    assert "Yes, same person" in text and "No, change the number" in text
    assert bill(app, 1)["customer_phone"] == "" and len(customers(app)) == 2      # unchanged so far

    # No: nothing changes and you are back on the form with what you typed
    back = client.post("/bills/1/customer", data=edit_form("98765 43210", "Asha", "Indiranagar", "no"))
    form = page_of(back)
    assert 'name="phone"' in form and "98765 43210" in form and "Is this the same person" not in form
    assert bill(app, 1)["customer_phone"] == "" and len(customers(app)) == 2

    # Yes: combined
    yes = client.post("/bills/1/customer", data=edit_form("98765 43210", "Asha", "Indiranagar", "yes"),
                      follow_redirects=True)
    assert "Combined." in page_of(yes) and "Undo" in page_of(yes)
    token = undo_token(yes)
    now = customers(app)
    assert list(now) == [2]                                                        # the empty one is gone
    assert now[2]["name"] == "Asha Rao"                                            # the owner keeps their details
    assert now[2]["location"] == "Indiranagar"                                     # a blank filled from the other
    assert bill(app, 1)["customer_id"] == 2 and bill(app, 2)["customer_id"] == 2
    assert bill(app, 1)["customer_phone"] == "9876543210"                          # the edit was saved on the bill
    assert bill(app, 1)["customer_name"] == "Asha" and bill(app, 2)["customer_name"] == "Asha Rao"  # printed names stay
    one = client.get("/customers/lookup?phone=9876543210").get_json()
    assert one["bill_count"] == 2

    # Undo: everything comes back
    res = client.post(f"/undo/{token}", follow_redirects=True)
    assert "Undone" in page_of(res)
    back = customers(app)
    assert sorted(back) == [1, 2] and back[1]["name"] == "Asha" and back[1]["phone"] == ""
    assert back[1]["location"] == "Indiranagar" and back[2]["location"] == ""      # the owner's blank is blank again
    assert bill(app, 1)["customer_id"] == 1 and bill(app, 2)["customer_id"] == 2
    assert bill(app, 1)["customer_phone"] == ""                                    # the bill is as it was
    assert client.get("/customers/lookup?phone=9876543210").get_json()["bill_count"] == 1

    # it can only be undone once
    again = client.post(f"/undo/{token}", follow_redirects=True)
    assert "too late" in page_of(again) and sorted(customers(app)) == [1, 2]


# ---- which bills move ----

def test_a_customer_with_their_own_phone_and_other_bills_only_loses_this_bill(client, app):
    setup(client)
    post_bill(client, "Asha", "9876543210")
    post_bill(client, "Asha", "9876543210")
    post_bill(client, "Ravi", "9123456780")
    asha = bill(app, 1)["customer_id"]
    ravi = bill(app, 3)["customer_id"]
    text = page_of(client.post("/bills/1/customer", data=edit_form("9123456780")))
    assert "Move 1 bill (only this one) to Ravi. Asha stays, with their other bills." in text
    yes = client.post("/bills/1/customer", data=edit_form("9123456780", action="yes"), follow_redirects=True)
    assert bill(app, 1)["customer_id"] == ravi and bill(app, 2)["customer_id"] == asha
    assert sorted(customers(app)) == [asha, ravi]                                  # both people stay
    client.post(f"/undo/{undo_token(yes)}")
    assert bill(app, 1)["customer_id"] == asha and bill(app, 1)["customer_phone"] == "9876543210"


def test_a_customer_with_their_own_phone_and_only_this_bill_is_combined_completely(client, app):
    setup(client)
    post_bill(client, "Asha", "9876543210")
    post_bill(client, "Ravi", "9123456780")
    text = page_of(client.post("/bills/1/customer", data=edit_form("9123456780")))
    assert "Move 1 bill of Asha to Ravi, and remove Asha from Customer Details." in text
    client.post("/bills/1/customer", data=edit_form("9123456780", action="yes"))
    assert list(customers(app)) == [2] and bill(app, 1)["customer_id"] == 2


def test_a_customer_without_a_phone_moves_all_their_bills_together(client, app):
    setup(client)
    post_bill(client, "Meena")
    post_bill(client, "Meena")                                                     # a second no-phone Meena? no: another customer
    first = bill(app, 1)["customer_id"]
    # put both bills on one no-phone customer, as older data would have them
    db = database(app)
    db.execute("UPDATE bills SET customer_id = ? WHERE id = 2", (first,))
    db.commit()
    db.close()
    post_bill(client, "Meena Rao", "9876543210")
    text = page_of(client.post("/bills/1/customer", data=edit_form("9876543210", "Meena")))
    assert "Move 2 bills of Meena to Meena Rao, and remove Meena from Customer Details." in text
    client.post("/bills/1/customer", data=edit_form("9876543210", "Meena", action="yes"))
    owner = bill(app, 3)["customer_id"]
    assert bill(app, 1)["customer_id"] == owner and bill(app, 2)["customer_id"] == owner
    assert first not in customers(app)
    assert bill(app, 2)["customer_phone"] == ""                                    # bill 2 printed nothing new


def test_a_walk_in_bill_is_only_linked(client, app):
    setup(client)
    post_bill(client, "", "")
    post_bill(client, "Asha Rao", "9876543210")
    assert bill(app, 1)["customer_id"] == 0
    owner = bill(app, 2)["customer_id"]
    text = page_of(client.post("/bills/1/customer", data=edit_form("9876543210", "")))
    assert "Move 1 bill: it will count under Asha Rao." in text
    yes = client.post("/bills/1/customer", data=edit_form("9876543210", "", action="yes"), follow_redirects=True)
    assert bill(app, 1)["customer_id"] == owner and bill(app, 1)["customer_name"] == "Walk-in customer"
    assert list(customers(app)) == [owner]
    client.post(f"/undo/{undo_token(yes)}")
    assert bill(app, 1)["customer_id"] == 0 and bill(app, 1)["customer_phone"] == ""


def test_a_number_nobody_has_just_saves_without_a_question(client, app):
    setup(client)
    post_bill(client, "Asha", "9876543210")
    res = client.post("/bills/1/customer", data=edit_form("9123456780"), follow_redirects=True)
    assert "Is this the same person" not in page_of(res) and "this bill only" in page_of(res)
    assert bill(app, 1)["customer_phone"] == "9123456780"
    assert customers(app)[1]["phone"] == "9876543210"                              # the customer is unchanged


def test_the_owner_keeps_their_own_location_and_the_printed_bills_never_change(client, app):
    setup(client)
    post_bill(client, "Asha", "", location="Jayanagar")
    post_bill(client, "Asha Rao", "9876543210", location="Indiranagar")
    printed = [(r["customer_name"], r["customer_location"]) for r in database(app).execute(
        "SELECT customer_name, customer_location FROM bills ORDER BY id")]
    client.post("/bills/1/customer", data=edit_form("9876543210", "Asha", "Jayanagar", "yes"))
    assert customers(app)[2]["location"] == "Indiranagar"                          # kept, not overwritten
    assert [(r["customer_name"], r["customer_location"]) for r in database(app).execute(
        "SELECT customer_name, customer_location FROM bills ORDER BY id")] == printed


# ---- Customer Details uses the same prompt ----

def test_changing_a_phone_on_customer_details_asks_the_same_question(client, app):
    setup(client)
    post_bill(client, "Asha")
    post_bill(client, "Asha", "")                                                  # a second no-phone customer
    post_bill(client, "Asha Rao", "9876543210")
    asha = bill(app, 1)["customer_id"]
    owner = bill(app, 3)["customer_id"]
    data = {"name": "Asha", "phone": "98765 43210", "location": "", "customer_type": "Retail"}
    text = page_of(client.post(f"/customers/{asha}", data=data))
    assert f"This number already belongs to Asha Rao (1 bill, last bill {TODAY}). Is this the same person?" in text
    assert "Move 1 bill of Asha to Asha Rao, and remove Asha from Customer Details." in text
    assert customers(app)[asha]["phone"] == ""                                     # nothing saved yet
    no = client.post(f"/customers/{asha}", data={**data, "action": "no"})
    assert "98765 43210" in page_of(no) and "Is this the same person" not in page_of(no)
    assert customers(app)[asha]["phone"] == "" and bill(app, 1)["customer_id"] == asha
    yes = client.post(f"/customers/{asha}", data={**data, "action": "yes"}, follow_redirects=True)
    assert "Combined." in page_of(yes)
    assert asha not in customers(app) and bill(app, 1)["customer_id"] == owner
    assert bill(app, 1)["customer_phone"] == ""                                    # printed bills unchanged
    client.post(f"/undo/{undo_token(yes)}")
    assert asha in customers(app) and bill(app, 1)["customer_id"] == asha


def test_a_new_number_on_customer_details_just_saves(client, app):
    setup(client)
    post_bill(client, "Asha")
    res = client.post("/customers/1", data={"name": "Asha", "phone": "9876543210", "location": "",
                                            "customer_type": "Retail"}, follow_redirects=True)
    assert "Customer saved" in page_of(res) and customers(app)[1]["phone"] == "9876543210"


# ---- Undo ----

def test_undo_runs_out_after_30_seconds_and_is_private(client, app):
    setup(client)
    post_bill(client, "Asha")
    post_bill(client, "Asha Rao", "9876543210")
    yes = client.post("/bills/1/customer", data=edit_form("9876543210", action="yes"), follow_redirects=True)
    token = undo_token(yes)
    # the page shows a countdown while it is available
    assert 'id="undo-banner"' in yes.data.decode() and 'data-left="' in yes.data.decode()
    db = database(app)
    db.execute("UPDATE undo_actions SET created = ?", (time.time() - 31,))
    db.commit()
    late = client.post(f"/undo/{token}", follow_redirects=True)
    assert "too late" in page_of(late) and list(customers(app)) == [2]
    assert 'id="undo-banner"' not in page(client, f"/bills/1?undo={token}")        # no button once it has run out


def test_another_shop_cannot_undo(client, app):
    setup(client)
    post_bill(client, "Asha")
    post_bill(client, "Asha Rao", "9876543210")
    yes = client.post("/bills/1/customer", data=edit_form("9876543210", action="yes"), follow_redirects=True)
    token = undo_token(yes)
    client.get("/logout")
    create(client, login="two@example.com", shop="Other Shop")
    res = client.post(f"/undo/{token}", follow_redirects=True)
    assert "too late" in page_of(res) and list(customers(app)) == [2]
    assert client.post(f"/undo/{token}").status_code == 302
    assert 'id="undo-banner"' not in page(client, f"/customers?undo={token}")
