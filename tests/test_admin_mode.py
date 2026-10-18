from tests.test_auth import create


def test_non_admin_sees_only_billing_past_bills_and_customers(client):
    create(client)
    page = client.get("/billing").data.decode()
    assert "Inventory" in page and "Shop Details" in page and "Profit" in page
    client.post("/mode")                                           # switch to Non-Admin
    page = client.get("/billing").data.decode()
    assert "Past bills" in page and "Customer Details" in page
    assert 'href="/inventory' not in page and 'href="/settings' not in page and 'href="/profit' not in page
    for url in ("/", "/inventory/", "/profit", "/settings", "/inventory/new"):
        r = client.get(url)
        assert r.status_code == 302 and "/billing" in r.headers["Location"], url
    assert client.get("/bills").status_code == 200 and client.get("/customers").status_code == 200
    client.post("/mode")                                           # back to Admin
    assert client.get("/inventory/").status_code == 200 and client.get("/settings").status_code == 200


def test_offer_category_is_a_dropdown_of_the_shop_categories(client):
    create(client)
    client.post("/settings/categories", data={"name": "Bedsheets"})
    page = client.get("/settings").data.decode()
    assert '<select name="category">' in page and '<option value="Bedsheets">' in page
