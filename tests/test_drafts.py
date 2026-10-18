import glob
import os
from datetime import date, datetime

import pytest

from app.db import init_db
from app.services import customers as people
from app.services.billing import BillError, delete_draft, save_bill
from app.services.home import home_figures
from tests.test_billing import CASH, save, shop, stock_of   # noqa: F401  (shop is a fixture)
from tests.test_edit_bill import bill_row, count_bills

TRAY = 1
CUSHION = 2


def draft(db, items, name="Asha", phone="", **more):
    return save(db, items, name, phone, payments=None, draft=True, **more)


def test_draft_does_not_change_stock(shop):
    bill_id = draft(shop, [{"product_id": TRAY, "quantity": 4}])
    assert stock_of(shop, "Tray") == 10
    row = bill_row(shop, bill_id)
    assert row["status"] == "Draft" and row["draft_created_at"] and row["bill_label"]


def test_draft_keeps_entered_details_and_can_exceed_stock(shop):
    bill_id = draft(shop, [{"product_id": TRAY, "quantity": 12, "discount": "10"}], phone="9876543210",
                    customer_location="Indiranagar", shipping="80", whole_discount="5")
    row = bill_row(shop, bill_id)
    assert (row["customer_name"], row["customer_phone"], row["customer_location"]) == (
        "Asha", "9876543210", "Indiranagar")
    assert row["shipping"] == 8000 and row["whole_discount_pct"] == 5
    assert shop.execute("SELECT quantity, line_discount_pct FROM bill_lines WHERE bill_id = ?",
                        (bill_id,)).fetchone()[:] == (12, 10)
    assert stock_of(shop, "Tray") == 10
    # a draft makes no customer record until it is finalised
    assert shop.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0


def test_draft_shows_in_past_bills_with_draft_status_and_filter(client, shop):
    draft_id = draft(shop, [{"product_id": TRAY, "quantity": 1}], name="Draftie")
    save(shop, [{"product_id": TRAY, "quantity": 1}], "Finalone")
    page = client.get("/bills").data.decode()
    assert "Draftie" in page and 'status-draft">Draft</span>' in page
    assert f"/billing/edit/{draft_id}" in page and "Delete draft" in page
    only = client.get("/bills?status=draft").data.decode()
    assert "Draftie" in only and "Finalone" not in only


def test_editing_a_draft_keeps_id_and_number(client, shop):
    bill_id = draft(shop, [{"product_id": TRAY, "quantity": 1}])
    before = bill_row(shop, bill_id)
    page = client.get(f"/billing/edit/{bill_id}").data.decode()
    assert "Save bill &amp; update stock" in page and "Update draft" in page
    same = draft(shop, [{"product_id": TRAY, "quantity": 3}, {"product_id": CUSHION, "quantity": 1}],
                 draft_id=bill_id)
    after = bill_row(shop, bill_id)
    assert same == bill_id and count_bills(shop) == 1
    assert (after["bill_label"], after["invoice_number"], after["status"]) == (
        before["bill_label"], before["invoice_number"], "Draft")
    assert shop.execute("SELECT COUNT(*) FROM bill_lines WHERE bill_id = ?", (bill_id,)).fetchone()[0] == 2
    assert stock_of(shop, "Tray") == 10 and stock_of(shop, "Cushion") == 3


def test_finalising_reduces_stock_once_and_keeps_number(shop):
    bill_id = draft(shop, [{"product_id": TRAY, "quantity": 4}], phone="9876543210")
    before = bill_row(shop, bill_id)
    final = save(shop, [{"product_id": TRAY, "quantity": 4}], "Asha", "9876543210", draft_id=bill_id)
    after = bill_row(shop, bill_id)
    assert final == bill_id and after["status"] == "Saved"
    assert (after["bill_label"], after["invoice_number"]) == (before["bill_label"], before["invoice_number"])
    assert stock_of(shop, "Tray") == 6
    assert after["created_at"][:10] == date.today().isoformat()          # sale date = finalised
    assert after["draft_created_at"] == before["draft_created_at"]       # draft date kept
    assert after["customer_id"] > 0                                       # now a real customer
    with pytest.raises(BillError, match="not a draft"):                   # a second time does nothing
        save(shop, [{"product_id": TRAY, "quantity": 4}], "Asha", "9876543210", draft_id=bill_id)
    assert stock_of(shop, "Tray") == 6


def test_finalising_with_short_stock_changes_nothing(shop):
    bill_id = draft(shop, [{"product_id": TRAY, "quantity": 2}, {"product_id": CUSHION, "quantity": 5}])
    with pytest.raises(BillError, match=r"Cushion.*5.*3"):
        save(shop, [{"product_id": TRAY, "quantity": 2}, {"product_id": CUSHION, "quantity": 5}], "Asha",
             draft_id=bill_id)
    assert (stock_of(shop, "Tray"), stock_of(shop, "Cushion")) == (10, 3)
    row = bill_row(shop, bill_id)
    assert row["status"] == "Draft" and row["created_at"] == bill_row(shop, bill_id)["created_at"]
    assert shop.execute("SELECT COUNT(*) FROM bill_lines WHERE bill_id = ?", (bill_id,)).fetchone()[0] == 2


def test_drafts_are_left_out_of_home_and_customer_totals(shop):
    save(shop, [{"product_id": TRAY, "quantity": 1}], "Asha", "9876543210")        # ₹450 final
    asha = shop.execute("SELECT id FROM customers").fetchone()["id"]
    draft(shop, [{"product_id": TRAY, "quantity": 2}], name="Asha", phone="9876543210",
          customer_id=asha, due_amount="100")
    figures = home_figures(shop, 1, date.today())
    assert figures["today_sales"] == figures["month_sales"] == 45000
    assert figures["bills_today"] == figures["bills_month"] == 1
    assert figures["pending_amount"] == 0 and figures["pending_customers"] == 0
    assert figures["week"][-1]["amount"] == 45000
    assert people.stats(shop, 1, asha) == {"bill_count": 1, "spent": 45000,
                                           "last_bill": bill_row(shop, 1)["created_at"]}
    listed = people.listing(shop, 1)[0]
    assert (listed["bill_count"], listed["spent"]) == (1, 45000)


def test_delete_draft(client, shop):
    bill_id = draft(shop, [{"product_id": TRAY, "quantity": 1}])
    final = save(shop, [{"product_id": TRAY, "quantity": 1}], "Ravi")
    with pytest.raises(BillError, match="Only a draft"):
        delete_draft(shop, 1, final)
    delete_draft(shop, 1, bill_id)
    assert bill_row(shop, bill_id) is None and stock_of(shop, "Tray") == 9
    assert shop.execute("SELECT COUNT(*) FROM bill_lines WHERE bill_id = ?", (bill_id,)).fetchone()[0] == 0


def test_drafts_cannot_be_cancelled_or_paid(client, shop):
    bill_id = draft(shop, [{"product_id": TRAY, "quantity": 1}])
    client.post(f"/bills/{bill_id}/cancel")
    assert bill_row(shop, bill_id)["status"] == "Draft" and stock_of(shop, "Tray") == 10
    page = client.get(f"/bills/{bill_id}").data.decode()
    assert "Cancel bill" not in page and "Delete draft" in page and "DRAFT" in page


def test_draft_prints_with_draft_marked(client, shop):
    bill_id = draft(shop, [{"product_id": TRAY, "quantity": 1}])
    page = client.get(f"/bills/{bill_id}").data.decode()
    assert 'class="paper-draft">DRAFT</strong>' in page and "(DRAFT)" in page
    final = save(shop, [{"product_id": TRAY, "quantity": 1}], "Ravi")
    assert "paper-draft" not in client.get(f"/bills/{final}").data.decode()


def test_saved_bill_edit_is_still_cancel_and_recreate(client, shop):
    old = save(shop, [{"product_id": TRAY, "quantity": 4}], "Asha")
    page = client.get(f"/billing/edit/{old}").data.decode()
    assert "Save changes (replaces" in page and "Update draft" not in page and 'id="draft"' not in page
    new = save(shop, [{"product_id": TRAY, "quantity": 2}], "Asha", replaces=old)
    assert new != old and stock_of(shop, "Tray") == 8
    assert (bill_row(shop, old)["status"], bill_row(shop, old)["replaced_by"]) == ("Cancelled", new)
    assert bill_row(shop, new)["status"] == "Saved"


def test_save_route_makes_and_finalises_a_draft(client, shop):
    body = {"items": [{"product_id": TRAY, "quantity": 2}], "customer": "Asha", "order_source": "",
            "payments": [], "draft": True}
    res = client.post("/billing/save", json=body)
    assert res.status_code == 200 and "saved=draft" in res.get_json()["url"]
    bill_id = bill_row(shop, 1)["id"]
    assert stock_of(shop, "Tray") == 10
    body.update(draft=False, draft_id=bill_id, order_source="Walk-in", payments=CASH)
    assert client.post("/billing/save", json=body).status_code == 200
    assert stock_of(shop, "Tray") == 8 and bill_row(shop, bill_id)["status"] == "Saved"


def test_migration_adds_the_column_once_after_a_backup(app, shop):
    save(shop, [{"product_id": TRAY, "quantity": 1}], "Asha")
    shop.commit()
    shop.execute("ALTER TABLE bills DROP COLUMN draft_created_at")
    shop.commit()
    folder = os.path.dirname(app.config["DATABASE"])
    init_db()
    init_db()                                                            # safe to run twice
    assert len(glob.glob(os.path.join(folder, "quantro-backup-before-drafts-*.db"))) == 1
    row = shop.execute("SELECT status, draft_created_at FROM bills").fetchone()
    assert (row["status"], row["draft_created_at"]) == ("Saved", "")
