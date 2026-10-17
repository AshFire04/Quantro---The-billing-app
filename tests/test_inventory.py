from tests.test_auth import create


def add(client, **kw):
    data = {"code": "", "name": "Tray", "category": "Trays", "price": "450",
            "stock": "10", "low_stock_level": "3"}
    data.update(kw)
    return client.post("/inventory/new", data=data)


def test_empty_state(client):
    create(client)
    assert b"No products yet" in client.get("/inventory/").data


def test_add_edit_remove(client):
    create(client)
    assert add(client, code="KA36", name="Tray 9.5").status_code == 302
    page = client.get("/inventory/").data
    assert b"KA36" in page and b"Tray 9.5" in page and "₹450.00".encode() in page
    client.post("/inventory/1/edit", data={"code": "KA36", "name": "Tray Big", "category": "Trays",
                                           "price": "500.50", "stock": "7", "low_stock_level": "3"})
    page = client.get("/inventory/").data
    assert b"Tray Big" in page and "₹500.50".encode() in page
    client.post("/inventory/1/remove")
    assert b"No products yet" in client.get("/inventory/").data
    # a code is used for good: even after the product is removed it can't be used again
    res = add(client, code="KA36")
    assert res.status_code == 200 and b"has been removed" in res.data
    assert add(client, code="ka36", name="Another").status_code == 200       # any capitals
    assert add(client, code="KA37").status_code == 302                       # a new code is fine
    res = client.post("/inventory/2/edit", data={"code": "KA36", "name": "Tray", "category": "",
                                                 "price": "1", "stock": "1", "low_stock_level": "1"})
    assert b"has been removed" in res.data                                   # editing can't take it either


def test_status_and_filters(client):
    create(client)
    add(client, name="Plenty", stock="10", low_stock_level="3")
    add(client, name="Few", stock="3", low_stock_level="3")
    add(client, name="None", stock="0", low_stock_level="3")
    low = client.get("/inventory/?status=low").data
    assert b"Few" in low and b"Plenty" not in low and b"None" not in low
    out = client.get("/inventory/?status=out").data
    assert b"None" in out and b"Few" not in out
    assert b"Plenty" in client.get("/inventory/?status=all").data


def test_search_by_name_or_code(client):
    create(client)
    add(client, code="KA36", name="Tray")
    add(client, name="Bedsheet", category="Linen")
    assert b"Bedsheet" not in client.get("/inventory/?q=ka36").data
    assert b"Bedsheet" in client.get("/inventory/?q=bed").data
    assert b"Tray" not in client.get("/inventory/?q=bed").data


def test_validation(client):
    create(client)
    assert b"already uses the code" in (add(client, code="A1"), add(client, code="a1"))[1].data
    assert b"Enter the price" in add(client, price="abc").data
    assert b"whole numbers" in add(client, stock="x").data
    assert b"name" in add(client, name="").data


def test_shops_are_separate(client, app):
    create(client)
    add(client, name="Secret tray")
    client.get("/logout")
    create(client, login="other@example.com", shop="Other Shop")
    assert b"Secret tray" not in client.get("/inventory/").data
    assert client.get("/inventory/1/edit").status_code == 404
    assert client.post("/inventory/1/remove").status_code == 404


def test_extra_product_details_are_saved_shown_and_optional(client):
    from tests.test_auth import create
    create(client)
    res = client.post("/inventory/new", data={
        "name": "Tray", "price": "450", "stock": "5", "low_stock_level": "2",
        "hsn": "9403", "supplier": "Mehta Traders", "cost_price": "300.50", "gst_rate": "18"})
    assert res.status_code == 302
    page = client.get("/inventory/1/edit").data.decode()
    assert 'value="9403"' in page and "Mehta Traders" in page
    assert 'value="300.50"' in page and 'value="18"' in page
    client.post("/inventory/new", data={        # all four left blank is fine
        "name": "Cushion", "price": "100", "stock": "5", "low_stock_level": "2"})
    assert client.get("/inventory/2/edit").status_code == 200


def test_bad_extra_product_details_are_refused(client):
    from tests.test_auth import create
    create(client)
    base = {"name": "Tray", "price": "450", "stock": "5", "low_stock_level": "2"}
    for extra, message in [({"hsn": "94A3"}, "digits only"), ({"cost_price": "abc"}, "cost price"),
                           ({"gst_rate": "150"}, "between 0 and 100"), ({"gst_rate": "x"}, "GST rate")]:
        res = client.post("/inventory/new", data={**base, **extra}, follow_redirects=True)
        assert message in res.data.decode()
    assert "No products yet" in client.get("/inventory/").data.decode()
