from datetime import date

from app.services.billing import fiscal_year


def num_today(n):
    return f"{fiscal_year(date.today())}/{n}"


from tests.test_auth import create
from tests.test_bills import make_bill
from tests.test_inventory import add
from tests.test_settings import PNG, seen, upload


def paper(page):
    return page[page.index('class="paper"'):]


def test_printable_bill_uses_the_shops_own_settings(client):
    create(client)
    client.post("/settings/details", data={
        "name": "Sajja Home Furnishing", "phone": "90087 89936", "website": "www.sajja.in",
        "bank_details": "A/c No: 1234\nIFSC: ABCD0001", "terms": "Goods once sold will not be taken back"})
    upload(client, label="Follow us")
    add(client, name="Tray", price="450", stock="10")
    url = make_bill(client, "Asha Rao")
    page = paper(seen(client.get(url)))
    for text in ("Sajja Home Furnishing", "www.sajja.in", "90087 89936", "Cash / Credit Memo",
                 "Bill No: <strong>" + num_today(1), "Asha Rao", "Tray", "₹450.00", "Total", "Shipping",
                 "Bank Details", "IFSC: ABCD0001", "Goods once sold will not be taken back",
                 "Follow us", "/uploads/"):
        assert text in page
    assert "Print" in seen(client.get(url))


def test_print_layout_hides_the_menu(client):
    css = client.get("/static/css/print.css").data.decode()
    assert ".topbar" in css and "display: none" in css


def test_bill_without_settings_still_prints(client):
    create(client)
    add(client, name="Tray", price="450", stock="10")
    page = paper(seen(client.get(make_bill(client, "Ravi"))))
    assert "Bank Details" not in page and "Cash / Credit Memo" in page
