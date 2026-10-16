import pytest

from app.services.billing import BillError
from tests.test_auth import create
from tests.test_billing import CASH, save, shop, stock_of   # noqa: F401  (shop is a fixture)
from tests.test_inventory import add

TRAY = 1
CUSHION = 2


def bill_row(db, bill_id):
    return db.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()


def count_bills(db):
    return db.execute("SELECT COUNT(*) FROM bills").fetchone()[0]


def test_replace_with_more_takes_the_extra_out_of_stock(shop):
    old = save(shop, [{"product_id": TRAY, "quantity": 4}], "Asha")
    assert stock_of(shop, "Tray") == 6
    new = save(shop, [{"product_id": TRAY, "quantity": 7}], "Asha", replaces=old)
    assert stock_of(shop, "Tray") == 3                       # 10 - 7, not 10 - 4 - 7
    assert (bill_row(shop, old)["status"], bill_row(shop, old)["replaced_by"]) == ("Cancelled", new)
    assert bill_row(shop, new)["replaces"] == old and bill_row(shop, new)["status"] == "Saved"
    assert bill_row(shop, new)["invoice_number"] == 2


def test_replace_with_fewer_is_a_return(shop):
    old = save(shop, [{"product_id": TRAY, "quantity": 4}], "Asha")
    save(shop, [{"product_id": TRAY, "quantity": 1}], "Asha", replaces=old)
    assert stock_of(shop, "Tray") == 9                       # three came back


def test_swap_one_item_for_another(shop):
    old = save(shop, [{"product_id": TRAY, "quantity": 2}, {"product_id": CUSHION, "quantity": 3}],
               "Asha")
    assert (stock_of(shop, "Tray"), stock_of(shop, "Cushion")) == (8, 0)
    save(shop, [{"product_id": TRAY, "quantity": 2}], "Asha", replaces=old)   # cushions returned
    assert (stock_of(shop, "Tray"), stock_of(shop, "Cushion")) == (8, 3)


def test_edit_can_use_the_stock_the_old_bill_held(shop):
    old = save(shop, [{"product_id": TRAY, "quantity": 4}], "Asha")           # 6 left on the shelf
    with pytest.raises(BillError, match="Only 10 left of Tray"):
        save(shop, [{"product_id": TRAY, "quantity": 11}], "Asha", replaces=old)
    save(shop, [{"product_id": TRAY, "quantity": 10}], "Asha", replaces=old)  # 6 + the 4 given back
    assert stock_of(shop, "Tray") == 0


def test_refused_edit_changes_nothing(shop):
    old = save(shop, [{"product_id": TRAY, "quantity": 4}], "Asha")
    with pytest.raises(BillError):
        save(shop, [{"product_id": TRAY, "quantity": 11}], "Asha", replaces=old)
    with pytest.raises(BillError, match="customer's name"):
        save(shop, [{"product_id": TRAY, "quantity": 1}], " ", replaces=old)
    assert stock_of(shop, "Tray") == 6
    assert bill_row(shop, old)["status"] == "Saved" and bill_row(shop, old)["replaced_by"] is None
    assert count_bills(shop) == 1
    assert shop.execute("SELECT next_invoice_number FROM shops").fetchone()[0] == 2


def test_failure_halfway_through_an_edit_undoes_everything(shop):
    old = save(shop, [{"product_id": TRAY, "quantity": 4}], "Asha")
    shop.execute("CREATE TRIGGER boom BEFORE UPDATE ON products WHEN NEW.id = 2 "
                 "BEGIN SELECT RAISE(ABORT, 'boom'); END")
    with pytest.raises(BillError, match="nothing was changed"):
        save(shop, [{"product_id": TRAY, "quantity": 2}, {"product_id": CUSHION, "quantity": 1}],
             "Asha", replaces=old)
    assert (stock_of(shop, "Tray"), stock_of(shop, "Cushion")) == (6, 3)      # exactly as before
    assert bill_row(shop, old)["status"] == "Saved" and count_bills(shop) == 1
    assert shop.execute("SELECT next_invoice_number FROM shops").fetchone()[0] == 2


def test_a_bill_can_only_be_replaced_once(shop):
    old = save(shop, [{"product_id": TRAY, "quantity": 2}], "Asha")
    save(shop, [{"product_id": TRAY, "quantity": 3}], "Asha", replaces=old)
    with pytest.raises(BillError, match="already been cancelled or replaced"):
        save(shop, [{"product_id": TRAY, "quantity": 1}], "Asha", replaces=old)
    assert stock_of(shop, "Tray") == 7                       # untouched by the refused attempt


def test_cancelled_bills_are_never_deleted(shop):
    old = save(shop, [{"product_id": TRAY, "quantity": 2}], "Asha")
    newer = save(shop, [{"product_id": TRAY, "quantity": 1}], "Asha", replaces=old)
    save(shop, [{"product_id": TRAY, "quantity": 1}], "Asha", replaces=newer)
    assert count_bills(shop) == 3
    statuses = [r[0] for r in shop.execute("SELECT status FROM bills ORDER BY id")]
    assert statuses == ["Cancelled", "Cancelled", "Saved"]
    # The old bills still show exactly what they sold.
    assert shop.execute("SELECT COUNT(*) FROM bill_lines WHERE bill_id = ?", (old,)).fetchone()[0] == 1


def test_returned_item_that_was_removed_from_inventory_still_goes_back(shop):
    old = save(shop, [{"product_id": TRAY, "quantity": 1}, {"product_id": CUSHION, "quantity": 2}],
               "Asha")
    shop.execute("UPDATE products SET active = 0, code = NULL WHERE id = ?", (CUSHION,))
    shop.commit()
    save(shop, [{"product_id": TRAY, "quantity": 1}], "Asha", replaces=old)
    assert stock_of(shop, "Cushion") == 3


def test_the_old_payment_and_due_stay_with_the_cancelled_bill(shop):
    old = save(shop, [{"product_id": TRAY, "quantity": 2}], "Asha", payments=[{"mode": "UPI"}],
               due_amount="100")
    new = save(shop, [{"product_id": TRAY, "quantity": 2}], "Asha", replaces=old)
    assert bill_row(shop, new)["due_amount"] == 0            # the new bill has its own payments
    assert shop.execute("SELECT mode FROM payments WHERE bill_id = ?", (new,)).fetchone()[0] == "Cash"
    assert shop.execute("SELECT mode FROM payments WHERE bill_id = ?", (old,)).fetchone()[0] == "UPI"


# ---- through the website ----

def make(client, **extra):
    body = {"items": [{"product_id": 1, "quantity": 4, "discount": "10"}], "customer": "Asha",
            "phone": "98765 43210", "location": "Indiranagar", "order_source": "Website",
            "payments": [{"mode": "UPI"}], "whole_discount": "5", "shipping": "80"}
    body.update(extra)
    res = client.post("/billing/save", json=body)
    assert res.status_code == 200, res.get_json()
    return res


def test_edit_page_opens_a_copy_with_everything_filled_in(client):
    create(client)
    add(client, name="Tray", price="450", stock="10")
    make(client)                                             # stock is now 6
    page = client.get("/billing/edit/1").data.decode()
    assert "Editing bill #1" in page and "Save changes (replaces #1)" in page
    assert '"stock": 10' in page                             # the 4 held by bill #1 count as available
    for expected in ('"customer": "Asha"', '"phone": "98765 43210"', '"location": "Indiranagar"',
                     '"source": "Website"', '"whole_discount": "5"', '"shipping": "80.00"',
                     '"discount": "10"', '"quantity": 4', '"replaces": 1'):
        assert expected in page
    # Just opening the copy changes nothing.
    assert b">6<" in client.get("/inventory/").data
    assert b"This bill is cancelled" not in client.get("/bills/1").data


def test_saving_the_copy_replaces_the_bill(client):
    create(client)
    add(client, name="Tray", price="450", stock="10")
    make(client)
    res = make(client, replaces=1, items=[{"product_id": 1, "quantity": 2}], whole_discount="",
               shipping="")
    assert res.get_json()["url"].startswith("/bills/2")
    new_page = client.get("/bills/2").data.decode()
    assert "This bill replaces" in new_page and "bill #1" in new_page and "₹900.00" in new_page
    old_page = client.get("/bills/1").data.decode()
    assert "This bill is cancelled" in old_page and "replaced by" in old_page and "bill #2" in old_page
    assert ">Edit<" not in old_page                          # a cancelled bill can't be edited again
    listing = client.get("/bills").data.decode()
    assert "Cancelled" in listing and "replaced by #2" in listing
    assert b">8<" in client.get("/inventory/").data          # 10 - 2
    again = client.get("/billing/edit/1", follow_redirects=True).data
    assert b"already been cancelled or replaced" in again


def test_edit_button_only_on_saved_bills(client):
    create(client)
    add(client, name="Tray", price="450", stock="10")
    make(client)
    assert b">Edit<" in client.get("/bills/1").data


def test_cannot_edit_or_replace_another_shops_bill(client):
    create(client)
    add(client, name="Tray", price="450", stock="10")
    make(client)
    client.get("/logout")
    create(client, login="other@example.com", shop="Other shop")
    add(client, name="Tray", price="450", stock="10")
    assert client.get("/billing/edit/1").status_code == 302         # sent back to Past bills
    res = client.post("/billing/save", json={
        "items": [{"product_id": 1, "quantity": 1}], "customer": "X", "order_source": "Stall",
        "payments": CASH, "replaces": 1})
    assert res.status_code == 400 and "wasn't found" in res.get_json()["error"]
    client.get("/logout")
    client.post("/login", data={"login": "owner@example.com", "password": "secret123"})
    assert b"This bill is cancelled" not in client.get("/bills/1").data and b">6<" in client.get("/inventory/").data


def test_bad_replaces_value_is_refused(client):
    create(client)
    add(client, name="Tray", price="450", stock="10")
    res = client.post("/billing/save", json={
        "items": [{"product_id": 1, "quantity": 1}], "customer": "X", "order_source": "Stall",
        "payments": CASH, "replaces": "abc"})
    assert res.status_code == 400


# ---- cancelling without a replacement ----

def test_cancel_puts_everything_back_and_keeps_the_bill(shop):
    from app.services.billing import cancel_bill
    bill = save(shop, [{"product_id": TRAY, "quantity": 4}, {"product_id": CUSHION, "quantity": 2}],
                "Asha")
    assert (stock_of(shop, "Tray"), stock_of(shop, "Cushion")) == (6, 1)
    cancel_bill(shop, 1, bill)
    assert (stock_of(shop, "Tray"), stock_of(shop, "Cushion")) == (10, 3)
    row = bill_row(shop, bill)
    assert row["status"] == "Cancelled" and row["replaced_by"] is None
    assert shop.execute("SELECT COUNT(*) FROM bill_lines WHERE bill_id = ?", (bill,)).fetchone()[0] == 2
    assert shop.execute("SELECT next_invoice_number FROM shops").fetchone()[0] == 2   # no new number used


def test_a_bill_can_only_be_cancelled_once_and_not_after_replacing(shop):
    from app.services.billing import cancel_bill
    first = save(shop, [{"product_id": TRAY, "quantity": 2}], "Asha")
    cancel_bill(shop, 1, first)
    with pytest.raises(BillError, match="already been cancelled or replaced"):
        cancel_bill(shop, 1, first)                          # a second cancel must not return stock twice
    second = save(shop, [{"product_id": TRAY, "quantity": 3}], "Asha")
    save(shop, [{"product_id": TRAY, "quantity": 1}], "Asha", replaces=second)
    with pytest.raises(BillError):
        cancel_bill(shop, 1, second)
    with pytest.raises(BillError, match="wasn't found"):
        cancel_bill(shop, 1, 999)
    assert stock_of(shop, "Tray") == 9                       # only bill 3's single tray is out
    with pytest.raises(BillError):
        save(shop, [{"product_id": TRAY, "quantity": 1}], "Asha", replaces=first)   # can't edit a cancelled bill


def test_cancel_through_the_website(client):
    create(client)
    add(client, name="Tray", price="450", stock="10")
    make(client)                                             # 4 trays out, due none
    page = client.get("/bills/1").data.decode()
    assert "Cancel bill" in page and ">Edit<" in page
    done = client.post("/bills/1/cancel", follow_redirects=True).data.decode()
    assert "Bill cancelled. Its items are back in stock." in done and "This bill is cancelled" in done
    assert "Cancel bill" not in done and ">Edit<" not in done
    assert b">10<" in client.get("/inventory/").data
    assert "Cancelled" in client.get("/bills").data.decode()
    again = client.post("/bills/1/cancel", follow_redirects=True).data
    assert b"already been cancelled or replaced" in again and b">10<" in client.get("/inventory/").data


def test_a_cancelled_bill_no_longer_counts_as_due(client):
    create(client)
    add(client, name="Tray", price="450", stock="10")
    make(client, due_amount="100")
    assert "Asha" in client.get("/bills?due=due").data.decode()
    client.post("/bills/1/cancel")
    assert "Asha" not in client.get("/bills?due=due").data.decode()
    assert b"Nothing is due" not in client.get("/bills/1").data                # no stray payment form
    assert b"Mark payment received" not in client.get("/bills/1").data


def test_cannot_cancel_another_shops_bill(client):
    create(client)
    add(client, name="Tray", price="450", stock="10")
    make(client)
    client.get("/logout")
    create(client, login="other@example.com", shop="Other shop")
    client.post("/bills/1/cancel")
    client.get("/logout")
    client.post("/login", data={"login": "owner@example.com", "password": "secret123"})
    assert b"This bill is cancelled" not in client.get("/bills/1").data and b">6<" in client.get("/inventory/").data

