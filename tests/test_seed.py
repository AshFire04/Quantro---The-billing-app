from app.db import get_db
from seed import LOGIN, PASSWORD, main


def test_seed_makes_a_working_sample_shop(app, client):
    main(app)
    main(app)                                           # a second run changes nothing
    with app.app_context():
        db = get_db()
        assert db.execute("SELECT COUNT(*) FROM shops").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM bills").fetchone()[0] == 8
        assert db.execute("SELECT COUNT(*) FROM products WHERE stock < 0").fetchone()[0] == 0
    assert client.post("/login", data={"login": LOGIN, "password": PASSWORD}).status_code == 302
    page = client.get("/home").data
    assert b"sample data" in page and b"Sales against target" in page
    assert b"Basmati" not in page
    for url in ("/inventory/", "/bills", "/billing", "/settings", "/bills/1"):
        assert client.get(url).status_code == 200, url
