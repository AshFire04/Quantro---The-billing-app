import json
import os
import shutil
import subprocess

import pytest

from tests.test_billing import CASH, save, shop, stock_of   # noqa: F401  (shop is a fixture)

HARNESS = os.path.join(os.path.dirname(__file__), "js", "not_them_harness.js")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_not_them_clears_the_customer_but_keeps_the_items(client, shop):
    # Look up a customer by phone on the real Billing script, then tap "Not them".
    out = subprocess.run(["node", HARNESS], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                         timeout=60, check=True)
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert result["matched"] == {"name": "Asha", "location": "Indiranagar"} and result["button"]
    after = result["after"]
    assert (after["phone"], after["name"], after["location"]) == ("", "", "")      # the three fields
    assert after["focus"] == "phone" and after["noteHidden"]                      # cursor back on phone
    assert after["type"] == "B2B"                                                  # type left alone
    sent = result["saved"]
    assert sent["customer_id"] is None                                             # no customer link
    assert sent["items"] == [{"product_id": 1, "quantity": 1, "discount": ""}]    # items remain

    # Saving what the page sent leaves the bill with no customer record, and its items.
    sent.update(order_source="Walk-in", payments=CASH)
    assert client.post("/billing/save", json=sent).status_code == 200
    bill = shop.execute("SELECT * FROM bills").fetchone()
    assert bill["customer_id"] == 0 and bill["customer_phone"] == ""
    assert shop.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0
    assert shop.execute("SELECT quantity FROM bill_lines WHERE bill_id = ?", (bill["id"],)).fetchone()[0] == 1
    assert stock_of(shop, "Tray") == 9
