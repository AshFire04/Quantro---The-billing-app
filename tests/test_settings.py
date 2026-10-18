import html
import os

from decimal import Decimal

import pytest

from app.db import get_db
from app.services.billing import BillError, price_details, load_offers
from tests.test_auth import create
from tests.test_billing import CASH, save, shop, stock_of   # noqa: F401  (shop is a fixture)
from tests.test_inventory import add

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def seen(response):
    """The page text with HTML escapes (&#34; and friends) turned back into normal characters."""
    return html.unescape(response.data.decode())


def upload(client, label="UPI", data=PNG, filename="qr.png"):
    import io
    return client.post("/settings/qr", data={"label": label, "image": (io.BytesIO(data), filename)},
                       content_type="multipart/form-data", follow_redirects=True)


# ---- shop details ----

def test_settings_needs_sign_in(client):
    assert client.get("/settings").status_code == 302


def test_shop_details_are_saved(client):
    create(client)
    res = client.post("/settings/details", data={
        "name": "Sajja Home Furnishings", "phone": "98765 43210", "website": "www.sajja.example",
        "bank_details": "A/c 1234\nIFSC ABCD0001", "terms": "No returns on sale items."},
        follow_redirects=True)
    page = seen(res)
    assert "Shop details saved" in page
    for text in ("Sajja Home Furnishings", "98765 43210", "www.sajja.example", "IFSC ABCD0001",
                 "No returns on sale items."):
        assert text in page


def test_shop_name_cannot_be_blank(client):
    create(client)
    page = seen(client.post("/settings/details", data={"name": "  "}, follow_redirects=True))
    assert "Please give your shop a name" in page and "Test Shop" in page


def test_one_shops_settings_stay_private(client):
    create(client)
    client.post("/settings/details", data={"name": "Shop A", "phone": "1112223334"})
    client.get("/logout")
    create(client, login="other@example.com", shop="Shop B")
    page = seen(client.get("/settings"))
    assert "1112223334" not in page and "Shop A" not in page


# ---- QR codes ----

def test_upload_show_and_remove_a_qr_code(client, app):
    create(client)
    page = seen(upload(client, "UPI"))
    assert 'QR code "UPI" added' in page and "/uploads/" in page
    row = None
    with app.app_context():
        row = get_db().execute("SELECT * FROM shop_qr_codes").fetchone()
        path = os.path.join(app.config["UPLOAD_FOLDER"], row["filename"])
    assert os.path.exists(path) and row["filename"].endswith(".png")
    served = client.get(f"/uploads/{row['filename']}")
    assert served.status_code == 200 and served.data == PNG
    served.close()                       # on Windows an open response would keep the file locked
    client.post(f"/settings/qr/{row['id']}/delete")
    assert not os.path.exists(path) and client.get(f"/uploads/{row['filename']}").status_code == 404
    assert b"Add a QR code" in client.get("/settings").data


def test_jpg_is_accepted(client):
    create(client)
    assert "added" in seen(upload(client, "Insta", JPG, "photo.jpeg"))


@pytest.mark.parametrize("label, data, filename, message", [
    ("UPI", b"this is not an image", "qr.png", "isn't a PNG or JPG"),         # renamed text file
    ("UPI", b"GIF89a" + b"\x00" * 50, "qr.gif", "isn't a PNG or JPG"),
    ("UPI", PNG + b"\x00" * (1024 * 1024 + 10), "big.png", "too big"),
    ("", PNG, "qr.png", "give the QR code a label"),
    ("x" * 41, PNG, "qr.png", "under 40 characters"),
], ids=["text-renamed-png", "gif", "over-1mb", "no-label", "long-label"])
def test_bad_uploads_are_refused_with_a_plain_message(client, app, label, data, filename, message):
    create(client)
    assert message in seen(upload(client, label, data, filename))
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM shop_qr_codes").fetchone()[0] == 0
    folder = app.config["UPLOAD_FOLDER"]
    assert not os.path.exists(folder) or os.listdir(folder) == []


def test_no_file_chosen(client):
    create(client)
    res = client.post("/settings/qr", data={"label": "UPI"}, content_type="multipart/form-data",
                      follow_redirects=True)
    assert "choose an image" in seen(res)


def test_at_most_three_qr_codes(client):
    create(client)
    for i in range(3):
        upload(client, f"QR {i}")
    assert "up to 3 QR codes" in seen(upload(client, "One too many"))
    page = seen(client.get("/settings"))
    assert "Add a QR code" not in page and "up to 3 QR codes" in page


def test_another_shop_cannot_see_or_remove_my_qr_code(client, app):
    create(client)
    upload(client, "UPI")
    with app.app_context():
        row = get_db().execute("SELECT * FROM shop_qr_codes").fetchone()
    client.get("/logout")
    create(client, login="other@example.com", shop="Other shop")
    assert client.get(f"/uploads/{row['filename']}").status_code == 404
    assert client.post(f"/settings/qr/{row['id']}/delete").status_code == 404
    assert client.get("/uploads/..%5Cquantro.db").status_code == 404
    client.get("/logout")
    client.post("/login", data={"login": "owner@example.com", "password": "secret123"})
    assert client.get(f"/uploads/{row['filename']}").status_code == 200


def test_uploads_need_sign_in(client):
    assert client.get("/uploads/anything.png").status_code == 302


# ---- saved offers: adding, switching on and off, deleting ----

def add_offer(client, **kw):
    data = {"name": "Diwali bedsheets", "percentage": "15", "applies_to": "category",
            "category": "Bedsheets", "min_amount": ""}
    data.update(kw)
    return client.post("/settings/offers", data=data, follow_redirects=True)


def test_add_toggle_and_delete_an_offer(client):
    create(client)
    page = seen(add_offer(client))
    assert 'Offer "Diwali bedsheets" added' in page and "15%" in page and 'Items in “Bedsheets”' in page
    add_offer(client, name="Big bill", percentage="10", applies_to="bill", category="", min_amount="2500")
    page = seen(client.get("/settings"))
    assert "All items, when the bill reaches ₹2,500.00" in page
    client.post("/settings/offers/1/toggle")
    assert ">Off<" in client.get("/settings").data.decode()
    client.post("/settings/offers/1/toggle")
    assert ">Off<" not in client.get("/settings").data.decode()
    client.post("/settings/offers/2/delete")
    assert "Big bill" not in client.get("/settings").data.decode()


@pytest.mark.parametrize("kw, message", [
    ({"name": " "}, "give the offer a name"),
    ({"percentage": "0"}, "above 0"),
    ({"percentage": "101"}, "between 0 and 100"),
    ({"percentage": "abc"}, "must be a number"),
    ({"percentage": "12.345"}, "two decimal places"),
    ({"applies_to": "nonsense"}, "what the offer applies to"),
    ({"category": ""}, "enter the category"),
    ({"applies_to": "bill", "min_amount": "lots"}, "minimum bill amount"),
])
def test_bad_offers_are_refused(client, kw, message):
    create(client)
    assert message in seen(add_offer(client, **kw))
    assert b"No offers yet" in client.get("/settings").data


def test_offers_are_private_to_each_shop(client):
    create(client)
    add_offer(client, name="Zeta clearance")
    client.get("/logout")
    create(client, login="other@example.com", shop="Other shop")
    assert "Zeta clearance" not in seen(client.get("/settings"))
    assert client.post("/settings/offers/1/toggle").status_code == 404
    assert client.post("/settings/offers/1/delete").status_code == 404


# ---- offers changing the price ----
# In these, Tray (₹450) is in "Trays" and Cushion (₹299.50) is changed to "Cushions".

def make_offer(db, name, pct, applies_to="category", category="", min_amount=0, active=1, shop_id=1):
    return db.execute("INSERT INTO offers (shop_id, name, percentage, applies_to, category, "
                      "min_amount, active) VALUES (?, ?, ?, ?, ?, ?, ?)",
                      (shop_id, name, pct, applies_to, category, min_amount, active)).lastrowid


@pytest.fixture
def offers_shop(shop):
    shop.execute("UPDATE products SET category = 'Cushions' WHERE id = 2")
    shop.commit()
    return shop


def price(db, items, offer_ids=(), whole=None):
    offers = load_offers(db, 1, offer_ids)
    return price_details(db, 1, items, whole, 0, offers)


def test_category_offer_applies_only_to_that_category(offers_shop):
    offer = make_offer(offers_shop, "Tray sale", 15, category="Trays")
    items = [{"product_id": 1, "quantity": 2}, {"product_id": 2, "quantity": 1}]
    result = price(offers_shop, items, [offer])
    assert [l["line_amount"] for l in result["lines"]] == [76500, 29950]   # 900 - 15% = 765; cushion full
    assert [l["line_discount_pct"] for l in result["lines"]] == [15, 0]
    assert result["offers_applied"] == ["Tray sale"]


def test_an_offer_does_nothing_unless_it_is_picked(offers_shop):
    make_offer(offers_shop, "Tray sale", 15, category="Trays")
    make_offer(offers_shop, "Big bill", 10, "bill", min_amount=1000)
    result = price(offers_shop, [{"product_id": 1, "quantity": 2}], [])
    assert result["total"] == 90000 and result["offers_applied"] == []


def test_category_match_ignores_capitals_and_spaces(offers_shop):
    offer = make_offer(offers_shop, "Tray sale", 10, category="  tRAYS ")
    assert price(offers_shop, [{"product_id": 1, "quantity": 1}], [offer])["total"] == 40500


def test_a_typed_discount_beats_an_offer_even_zero(offers_shop):
    offer = make_offer(offers_shop, "Tray sale", 15, category="Trays")
    assert price(offers_shop, [{"product_id": 1, "quantity": 2, "discount": "5"}], [offer])["total"] == 85500
    assert price(offers_shop, [{"product_id": 1, "quantity": 2, "discount": "0"}], [offer])["total"] == 90000
    result = price(offers_shop, [{"product_id": 1, "quantity": 2, "discount": "5"}], [offer])
    assert result["offers_applied"] == []                 # it didn't change any price


def test_the_best_offer_wins_when_two_match(offers_shop):
    small = make_offer(offers_shop, "Small", 5, category="Trays")
    big = make_offer(offers_shop, "Big", 20, category="Trays")
    result = price(offers_shop, [{"product_id": 1, "quantity": 1}], [small, big])
    assert result["total"] == 36000 and result["offers_applied"] == ["Big"]


def test_whole_bill_offer_needs_its_minimum_after_item_discounts(offers_shop):
    offer = make_offer(offers_shop, "10% above 2500", 10, "bill", min_amount=250000)
    items = [{"product_id": 1, "quantity": 10}]                        # ₹4,500
    assert price(offers_shop, items, [offer])["total"] == 405000       # qualifies: 10% off
    halved = [{"product_id": 1, "quantity": 10, "discount": "50"}]     # item discount brings it to ₹2,250
    result = price(offers_shop, halved, [offer])
    assert result["total"] == 225000 and result["offers_applied"] == []   # now below the minimum
    exactly = [{"product_id": 1, "quantity": 5, "discount": "0"}]      # ₹2,250 again, but ...
    assert price(offers_shop, exactly, [offer])["total"] == 225000
    just_enough = [{"product_id": 2, "quantity": 3}]                   # 3 x 299.50 = 898.50: far below
    assert price(offers_shop, just_enough, [offer])["total"] == 89900


def test_a_whole_bill_offer_at_exactly_the_minimum_qualifies(offers_shop):
    offer = make_offer(offers_shop, "10% at 900", 10, "bill", min_amount=90000)
    assert price(offers_shop, [{"product_id": 1, "quantity": 2}], [offer])["total"] == 81000


def test_typed_whole_bill_discount_beats_the_offer(offers_shop):
    offer = make_offer(offers_shop, "Big bill", 10, "bill", min_amount=0)
    from decimal import Decimal
    items = [{"product_id": 1, "quantity": 2}]
    assert price(offers_shop, items, [offer], whole=Decimal("5"))["total"] == 85500
    assert price(offers_shop, items, [offer], whole=Decimal("0"))["total"] == 90000
    assert price(offers_shop, items, [offer])["total"] == 81000


def test_item_offer_then_whole_bill_offer_together(offers_shop):
    tray = make_offer(offers_shop, "Tray sale", 10, category="Trays")
    big = make_offer(offers_shop, "Big bill", 5, "bill", min_amount=100000)
    items = [{"product_id": 1, "quantity": 2}, {"product_id": 2, "quantity": 1}]
    # trays 900 - 10% = 810; + 299.50 = 1109.50 (above ₹1,000); 5% off = 1054.025 -> 1054.03
    result = price(offers_shop, items, [tray, big])
    assert result["total"] == 105400 and result["offers_applied"] == ["Tray sale", "Big bill"]


def test_unavailable_offers_are_refused(offers_shop):
    off = make_offer(offers_shop, "Switched off", 10, category="Trays", active=0)
    other_shop = offers_shop.execute("INSERT INTO shops (name) VALUES ('Other')").lastrowid
    foreign = make_offer(offers_shop, "Not mine", 10, category="Trays", shop_id=other_shop)
    for bad in (off, foreign, 999, "abc"):
        with pytest.raises(BillError, match="no longer available"):
            load_offers(offers_shop, 1, [bad])


def test_saving_records_the_offers_used(offers_shop):
    tray = make_offer(offers_shop, "Tray sale", 15, category="Trays")
    unused = make_offer(offers_shop, "Cushion sale", 20, category="Cushions")
    offers_shop.commit()
    bill = save(offers_shop, [{"product_id": 1, "quantity": 2}], "Asha", offer_ids=[tray, unused])
    row = offers_shop.execute("SELECT * FROM bills WHERE id = ?", (bill,)).fetchone()
    assert row["total"] == 76500 and row["offers_applied"] == "Tray sale"
    assert row["offer_ids"] == f"{tray},{unused}"
    line = offers_shop.execute("SELECT line_discount_pct FROM bill_lines WHERE bill_id = ?", (bill,)).fetchone()
    assert line[0] == 15
    assert offers_shop.execute("SELECT amount FROM payments").fetchone()[0] == 76500
    # Deleting the offer later leaves the old bill exactly as it was.
    offers_shop.execute("DELETE FROM offers WHERE id = ?", (tray,))
    offers_shop.commit()
    again = offers_shop.execute("SELECT total, offers_applied FROM bills WHERE id = ?", (bill,)).fetchone()
    assert tuple(again) == (76500, "Tray sale")


def test_saving_with_a_switched_off_offer_changes_nothing(offers_shop):
    off = make_offer(offers_shop, "Switched off", 10, category="Trays", active=0)
    offers_shop.commit()
    with pytest.raises(BillError, match="no longer available"):
        save(offers_shop, [{"product_id": 1, "quantity": 1}], "Asha", offer_ids=[off])
    assert stock_of(offers_shop, "Tray") == 10
    assert offers_shop.execute("SELECT COUNT(*) FROM bills").fetchone()[0] == 0


# ---- through the website ----

def test_billing_page_lists_active_offers_and_the_bill_shows_the_offer(client):
    create(client)
    add(client, name="Bedsheet", category="Bedsheets", price="1000", stock="10")
    add_offer(client)                                                    # 15% on Bedsheets
    add_offer(client, name="Old offer", percentage="5")
    client.post("/settings/offers/2/toggle")                             # switched off
    page = client.get("/billing").data.decode()
    assert "Diwali bedsheets" in page and "Old offer" not in page
    res = client.post("/billing/save", json={
        "items": [{"product_id": 1, "quantity": 2}], "customer": "Asha", "order_source": "Instagram",
        "payments": CASH, "offer_ids": [1]})
    assert res.status_code == 200
    bill = client.get(res.get_json()["url"]).data.decode()
    assert "Offers applied: Diwali bedsheets" in bill and "₹1,700.00" in bill and "15% off" in bill
    bad = client.post("/billing/save", json={
        "items": [{"product_id": 1, "quantity": 1}], "customer": "Asha", "order_source": "Instagram",
        "payments": CASH, "offer_ids": [2]})
    assert bad.status_code == 400 and "no longer available" in bad.get_json()["error"]


def test_editing_a_bill_keeps_its_offers_ticked_if_they_are_still_on(client):
    create(client)
    add(client, name="Bedsheet", category="Bedsheets", price="1000", stock="10")
    add_offer(client)
    client.post("/billing/save", json={
        "items": [{"product_id": 1, "quantity": 2}], "customer": "Asha", "order_source": "Instagram",
        "payments": CASH, "offer_ids": [1]})
    assert '"offer_ids": [1]' in client.get("/billing/edit/1").data.decode()
    client.post("/settings/offers/1/toggle")                              # now switched off
    assert '"offer_ids": []' in client.get("/billing/edit/1").data.decode()




# ---- shop logo ----

def upload_logo(client, data=PNG, filename="logo.png"):
    import io
    return client.post("/settings/logo", data={"logo": (io.BytesIO(data), filename)},
                       content_type="multipart/form-data", follow_redirects=True)


def logo_name(app):
    import sqlite3
    return sqlite3.connect(app.config["DATABASE"]).execute("SELECT logo FROM shops").fetchone()[0]


def test_logo_can_be_added_shown_replaced_and_removed(client, app):
    create(client)
    assert "No logo yet" in seen(client.get("/settings"))
    page = seen(upload_logo(client))
    assert "Logo saved" in page and "Your shop logo" in page and "No logo yet" not in page
    first = logo_name(app)
    assert first.endswith(".png") and os.path.exists(os.path.join(app.config["UPLOAD_FOLDER"], first))
    assert client.get(f"/uploads/{first}").data == PNG
    upload_logo(client, data=JPG, filename="new.jpg")                     # replace
    second = logo_name(app)
    assert second != first and second.endswith(".jpg")
    assert not os.path.exists(os.path.join(app.config["UPLOAD_FOLDER"], first))   # the old file is gone
    assert "Logo removed" in seen(client.post("/settings/logo/remove", follow_redirects=True))
    assert logo_name(app) == "" and not os.listdir(app.config["UPLOAD_FOLDER"])


def test_logo_shows_on_the_bill_and_in_the_preview(client, app):
    create(client)
    add(client, name="Tray", price="450", stock="5")
    client.post("/billing/save", json={"items": [{"product_id": 1, "quantity": 1}], "customer": "A",
                                       "order_source": "Walk-in", "payments": CASH})
    assert "paper-logo" not in client.get("/bills/1").data.decode()
    upload_logo(client)
    name = logo_name(app)
    assert f"/uploads/{name}" in client.get("/bills/1").data.decode()
    assert "sd-paper-logo" in client.get("/settings").data.decode()


def test_bad_logo_files_are_refused(client, app):
    create(client)
    assert "isn't a PNG or JPG" in seen(upload_logo(client, data=b"<svg onload=alert(1)>", filename="x.png"))
    assert "too big" in seen(upload_logo(client, data=PNG + b"\x00" * (1024 * 1024)))
    assert "choose an image" in seen(client.post("/settings/logo", data={}, follow_redirects=True))
    assert logo_name(app) == ""


def test_logo_is_private_and_needs_sign_in(client, app):
    assert client.post("/settings/logo", data={}).status_code == 302
    create(client)
    upload_logo(client)
    name = logo_name(app)
    client.get("/logout")
    assert client.get(f"/uploads/{name}").status_code == 302              # signed out
    create(client, login="other@example.com", shop="Shop B")
    assert client.get(f"/uploads/{name}").status_code == 404              # someone else's shop
    assert "No logo yet" in seen(client.get("/settings"))


def test_an_all_items_offer_can_leave_one_category_out(offers_shop):
    offers_shop.execute("INSERT INTO offers (shop_id, name, percentage, applies_to, exclude_category) "
                        "VALUES (1, 'Festive', 10, 'bill', ' cushions ')")
    offers_shop.commit()
    items = [{"product_id": 1, "quantity": 2}, {"product_id": 2, "quantity": 1}]
    result = price(offers_shop, items, [1])
    # Trays 900.00 get 10% off (810.00); the cushion (299.50) is left alone: 1109.50 -> 1110
    assert result["total"] == 111000 and result["offers_applied"] == ["Festive"]
    # A discount typed by hand covers everything, as before.
    assert price(offers_shop, items, [1], whole=Decimal("10"))["total"] == 108000


def test_the_except_category_is_saved_from_the_form_for_all_items_offers_only(client, app):
    create(client)
    add_offer(client, name="Festive", applies_to="bill", category="", exclude_category="Curtains")
    add_offer(client, name="Trays", applies_to="category", category="Trays", exclude_category="Curtains")
    with app.app_context():
        rows = get_db().execute("SELECT name, exclude_category FROM offers ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [("Festive", "Curtains"), ("Trays", "")]
    assert "except “Curtains”" in seen(client.get("/settings"))
