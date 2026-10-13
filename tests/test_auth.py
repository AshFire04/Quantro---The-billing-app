def create(client, login="owner@example.com", password="secret123", shop="Test Shop"):
    return client.post("/create-shop", data={
        "shop_name": shop, "owner_name": "Owner", "login": login, "password": password})


def test_signed_out_redirects_to_login(client):
    r = client.get("/bills")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_create_shop_signs_in(client):
    r = create(client)
    assert r.status_code == 302
    assert b"Test Shop" in client.get("/bills").data


def test_sign_out_then_in(client):
    create(client)
    client.get("/logout")
    assert client.get("/bills").status_code == 302
    r = client.post("/login", data={"login": "owner@example.com", "password": "secret123"})
    assert r.status_code == 302
    assert client.get("/bills").status_code == 200


def test_wrong_password_refused(client):
    create(client)
    client.get("/logout")
    r = client.post("/login", data={"login": "owner@example.com", "password": "nope"})
    assert b"isn&#39;t right" in r.data
    assert client.get("/bills").status_code == 302


def test_duplicate_login_refused(client):
    create(client)
    client.get("/logout")
    r = create(client)
    assert b"already has an account" in r.data
