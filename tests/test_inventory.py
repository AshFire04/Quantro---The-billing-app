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
    # a removed product's code can be used again
    assert add(client, code="KA36").status_code == 302


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
