import html
from io import BytesIO

from openpyxl import Workbook

from app.db import get_db
from app.services import inventory_import
from tests.test_auth import create
from tests.test_inventory import add

HEAD = ["Item Code/Bar Code", "Name", "Category", "Selling Price", "Stock", "Low-stock level",
        "HSN/SAC number", "Supplier", "Cost price", "GST rate"]


def sheet(rows, head=HEAD):
    wb = Workbook()
    ws = wb.active
    ws.append(head)
    for r in rows:
        ws.append(r)
    out = BytesIO()
    wb.save(out)
    out.seek(0)
    return out


def upload(client, rows, head=HEAD, name="products.xlsx"):
    res = client.post("/inventory/import", data={"file": (sheet(rows, head), name)},
                      content_type="multipart/form-data", follow_redirects=True)
    return html.unescape(res.data.decode())


def products(app):
    with app.app_context():
        return [tuple(r) for r in get_db().execute(
            "SELECT code, name, category, price, stock, low_stock_level, hsn, supplier, cost_price, "
            "gst_rate FROM products ORDER BY id")]


def test_import_adds_products_with_categories_and_suppliers_already_in_the_lists(client, app):
    create(client)
    for kind, name in (("categories", "Trays"), ("suppliers", "Sai")):
        client.post(f"/settings/{kind}", data={"name": name})
    page = upload(client, [["KA36", "Tray", "Trays", 450.5, 10.0, 3, "6302", "Sai", 300, 5],
                           [36, "Cushion", None, 299, None, None, None, None, None, None]])
    assert "2 products added" in page
    assert products(app) == [("KA36", "Tray", "Trays", 45050, 10, 3, "6302", "Sai", 30000, 5.0),
                             ("36", "Cushion", "", 29900, 0, 5, "", "", 0, 0.0)]


def test_a_category_or_supplier_not_in_the_lists_is_an_error_and_is_not_created(client, app):
    create(client)
    page = upload(client, [["A1", "Tray", "Trays", 450, 1, 1, "", "", "", ""],
                           ["A2", "Mat", "", 100, 1, 1, "", "Sai", "", ""]])
    assert "0 products added" in page and page.count("Please choose a") == 2
    assert products(app) == []
    with app.app_context():
        from app.services import choices
        assert "Trays" not in choices.names(get_db(), 1, "category")
        assert "Sai" not in choices.names(get_db(), 1, "supplier")


def test_bad_rows_are_skipped_and_named_and_good_rows_still_import(client, app):
    create(client)
    add(client, code="KA36", name="Tray", price="450", stock="10")
    page = upload(client, [["KA36", "Again", "", 100, 1, 1, "", "", "", ""],      # code in use
                           ["N1", "", "", 100, 1, 1, "", "", "", ""],             # no name
                           ["N2", "Lamp", "", "lots", 1, 1, "", "", "", ""],      # bad price
                           ["N3", "Vase", "", 100, -2, 1, "", "", "", ""],        # negative stock
                           ["N4", "Mat", "", 100, 1, 1, "", "", "", ""],
                           ["n4", "Mat 2", "", 100, 1, 1, "", "", "", ""]])        # twice in the sheet
    assert "1 product added" in page
    for row in ("Row 2", "Row 3", "Row 4", "Row 5", "Row 7"):
        assert row in page
    assert "Row 6" not in page
    assert [p[1] for p in products(app)] == ["Tray", "Mat"]


def test_headings_are_matched_loosely_and_name_and_price_are_needed(client, app):
    create(client)
    upload(client, [["Dhoti", 250, 4]], head=["product NAME", "price", "Qty"])
    assert products(app)[0][1:5] == ("Dhoti", "", 25000, 4)
    assert "needs a column called Name and Selling Price" in upload(client, [["x"]], head=["Colour"])


def test_wrong_files_are_refused_and_other_shops_are_separate(client, app):
    create(client)
    res = client.post("/inventory/import", data={"file": (BytesIO(b"not a spreadsheet"), "x.xlsx")},
                      content_type="multipart/form-data", follow_redirects=True)
    assert "doesn't look like an Excel" in html.unescape(res.data.decode())
    assert products(app) == []
    assert inventory_import.read_products(inventory_import.template_bytes())[0][1]["name"] == "Cotton bedsheet"


def test_import_needs_sign_in_and_template_downloads(client):
    assert client.get("/inventory/import").status_code == 302
    create(client)
    res = client.get("/inventory/import/template")
    assert res.status_code == 200 and res.data[:2] == b"PK"
    assert "Import from Excel" in html.unescape(client.get("/inventory/").data.decode())
