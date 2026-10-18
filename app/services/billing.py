"""The money and stock rules. Plain Python, no Flask in here, so tests can call it directly.

All amounts are whole paise. The browser's numbers are never trusted: everything is
recalculated here from the products in the database.
"""
from datetime import datetime
from decimal import Decimal, InvalidOperation

from . import choices
from .customers import CustomerError, resolve_for_bill
from .money import format_rupees, rupees_to_paise, take_percent_off

CUSTOMER_TYPES = ["Retail", "B2B"]


class BillError(Exception):
    """A bill that can't be saved. The message is shown to the owner as-is."""


def clean_choice(value, other, allowed, what):
    """A dropdown answer. `allowed` is the shop's list plus 'Other', which needs the typed
    text and is stored as 'Other: text'."""
    value = (value or "").strip()
    other = (other or "").strip()
    if value not in allowed:
        raise BillError(f"Please choose {what}")
    if value == "Other":
        if not other:
            raise BillError(f"Please type the {what} for 'Other'")
        return f"Other: {other}"
    return value


def parse_percent(value, what):
    """A discount percentage typed on the page: 0 to 100, at most two decimal places."""
    text = str(value if value is not None else "").strip()
    if text == "":
        return Decimal(0)
    try:
        pct = Decimal(text)
    except InvalidOperation:
        raise BillError(f"{what} must be a number, like 10 or 7.5")
    if not pct.is_finite() or not 0 <= pct <= 100:
        raise BillError(f"{what} must be between 0 and 100")
    if pct != pct.quantize(Decimal("0.01")):
        raise BillError(f"{what} can have at most two decimal places")
    return pct


def parse_shipping(value):
    """The optional shipping & handling amount, in paise."""
    if str(value if value is not None else "").strip() == "":
        return 0
    try:
        return rupees_to_paise(value)
    except ValueError:
        raise BillError("Enter shipping & handling as an amount, like 80 or 80.50")


def check_due(due_amount, total):
    """The part of the bill still to be paid, in paise."""
    try:
        due = rupees_to_paise(due_amount) if str(due_amount or "").strip() else 0
    except ValueError:
        raise BillError("Enter the amount due as a number, like 500 or 500.50")
    if due > total:
        raise BillError("The amount due can't be more than the bill total")
    return due


def fiscal_year(day):
    """The financial year a day falls in, as two digits: April 2026 to March 2027 is 26."""
    return (day.year if day.month >= 4 else day.year - 1) % 100


def next_bill_label(db, shop_id, day):
    """(financial year, number, label) the next bill dated `day` will get, like (26, 1, '26/1')."""
    fy = fiscal_year(day)
    last = db.execute("SELECT MAX(bill_seq) FROM bills WHERE shop_id = ? AND fy = ?",
                      (shop_id, fy)).fetchone()[0] or 0
    return fy, last + 1, f"{fy}/{last + 1}"


def check_order_date(order_date):
    """The day the order was placed. Blank means today; a day in the future is refused."""
    text = str(order_date or "").strip()
    today = datetime.now().date()
    if not text:
        return today
    try:
        day = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise BillError("Please choose the date the order was placed")
    if day > today:
        raise BillError("The order date can't be in the future")
    return day


def check_payments(payments, total, modes):
    """Turn the payments from the page into [(mode, paise)] that add up to `total`.

    `total` is what is being paid now: the bill total minus any amount left due.
    One payment with no amount means "all of it". Several payments (a split) must
    each have an amount, and the amounts must add up exactly. `modes` is what the shop's
    payment dropdown offers (its payment methods plus 'Other').
    """
    if total == 0:
        return []                     # the whole bill is due later, so nothing is paid now
    if not payments:
        raise BillError("Please choose how the customer paid")
    checked = []
    whole_bill = len(payments) == 1 and str(payments[0].get("amount") or "").strip() == ""
    for p in payments:
        mode = clean_choice(p.get("mode"), p.get("other"), modes, "payment mode")
        if whole_bill:
            amount = total
        else:
            try:
                amount = rupees_to_paise(p.get("amount", ""))
            except ValueError:
                raise BillError("Enter each payment amount as a number, like 500 or 500.50")
            if amount <= 0:
                raise BillError("Each payment needs an amount above zero")
        checked.append((mode, amount))
    paid = sum(amount for _, amount in checked)
    if paid != total:
        raise BillError(f"The payments add up to {format_rupees(paid)} but the amount "
                        f"being paid now is {format_rupees(total)}")
    return checked


def load_offers(db, shop_id, offer_ids):
    """The saved offers picked on a bill. Each must still exist and be switched on."""
    offers, seen = [], set()
    for raw in offer_ids or []:
        try:
            offer_id = int(raw)
        except (TypeError, ValueError):
            raise BillError("An offer on this bill is no longer available")
        if offer_id in seen:
            continue
        seen.add(offer_id)
        offer = db.execute("SELECT * FROM offers WHERE id = ? AND shop_id = ? AND active = 1",
                           (offer_id, shop_id)).fetchone()
        if offer is None:
            raise BillError("An offer on this bill is no longer available")
        offers.append({"id": offer["id"], "name": offer["name"],
                       "pct": Decimal(str(offer["percentage"])),
                       "applies_to": offer["applies_to"],
                       "category": offer["category"].strip().lower(),
                       "exclude": {c.strip().lower() for c in offer["exclude_category"].split("|") if c.strip()},
                       "min_amount": offer["min_amount"]})
    return offers


def price_details(db, shop_id, items, whole_discount_pct=None, shipping=0, offers=(),
                  check_stock=True):
    """Work out the lines and total for a bill, and which offers changed the price.

    items: [{"product_id": 3, "quantity": 2, "discount": "10"}, ...]
    The order is: each item's own discount first, then the whole-bill discount on the sum
    of those, then shipping & handling is added last.

    A percentage typed by hand always wins. Where none was typed (blank), the best picked
    offer is used: a category offer for an item of that category, and a whole-bill offer
    once the bill (after item discounts) reaches its minimum. `whole_discount_pct=None`
    means "nothing typed".

    Returns {"lines", "total", "whole_pct", "offers_applied"}. Raises BillError if a product
    is missing or stock is short.
    """
    # The same product added twice becomes one line.
    wanted = {}
    for item in items:
        try:
            product_id = int(item["product_id"])
            quantity = int(item["quantity"])
        except (KeyError, TypeError, ValueError):
            raise BillError("Something is wrong with an item on the bill")
        if quantity < 1:
            raise BillError("Each item needs a quantity of at least 1")
        typed = str(item.get("discount") if item.get("discount") is not None else "").strip()
        discount = parse_percent(typed, "An item discount") if typed else None
        if product_id in wanted:
            wanted[product_id][0] += quantity       # the first discount typed is kept
        else:
            wanted[product_id] = [quantity, discount]
    if not wanted:
        raise BillError("Add at least one item to the bill")

    applied = {}                                    # offer id -> name, in the order they won
    lines = []
    categories = []                                 # each line's category, same order as lines
    for product_id, (quantity, discount) in wanted.items():
        product = db.execute(
            "SELECT * FROM products WHERE id = ? AND shop_id = ? AND active = 1",
            (product_id, shop_id)).fetchone()
        if product is None:
            raise BillError("An item on this bill is no longer in Inventory")
        if check_stock and quantity > product["stock"]:
            raise BillError(f"Only {product['stock']} left of {product['name']}; "
                            "please change the quantity")
        if discount is None:
            category = product["category"].strip().lower()
            matching = [o for o in offers if o["applies_to"] == "category"
                        and category and o["category"] == category]
            best = max(matching, key=lambda o: o["pct"], default=None)
            discount = best["pct"] if best else Decimal(0)
            if best and best["pct"] > 0:
                applied[best["id"]] = best["name"]
        categories.append(product["category"].strip().lower())
        lines.append({
            "product_id": product_id,
            "code": product["code"],
            "name": product["name"],
            "quantity": quantity,
            "rate": product["price"],
            "cost": product["cost_price"],
            "gst_rate": product["gst_rate"] or 0,
            "line_discount_pct": float(discount),
            "line_amount": take_percent_off(product["price"] * quantity, discount),
        })
    subtotal = sum(line["line_amount"] for line in lines)
    skipped = 0                                     # items an offer's "except category" leaves alone
    if whole_discount_pct is None:
        qualifying = [o for o in offers if o["applies_to"] == "bill"
                      and subtotal >= o["min_amount"]]
        best = max(qualifying, key=lambda o: o["pct"], default=None)
        whole_discount_pct = best["pct"] if best else Decimal(0)
        if best and best["pct"] > 0:
            applied[best["id"]] = best["name"]
            if best["exclude"]:
                skipped = sum(line["line_amount"] for line, c in zip(lines, categories)
                              if c in best["exclude"])
    exact = take_percent_off(subtotal - skipped, whole_discount_pct) + skipped + shipping
    total = (exact + 50) // 100 * 100               # rounded off to the nearest rupee, half up
    return {"lines": lines, "total": total, "round_off": total - exact,
            "whole_pct": whole_discount_pct, "offers_applied": list(applied.values())}


def price_bill(db, shop_id, items, whole_discount_pct=Decimal(0), shipping=0, offers=()):
    """Same as price_details, but returns just (lines, total)."""
    result = price_details(db, shop_id, items, whole_discount_pct, shipping, offers)
    return result["lines"], result["total"]

def check_stock(db, shop_id, items):
    """Finalising a draft: every item must be on the shelf. Names the first one that is short."""
    wanted = {}
    for item in items:
        try:
            pid, qty = int(item["product_id"]), int(item["quantity"])
        except (KeyError, TypeError, ValueError):
            raise BillError("Something is wrong with an item on the bill")
        wanted[pid] = wanted.get(pid, 0) + qty
    for pid, qty in wanted.items():
        product = db.execute("SELECT name, stock FROM products WHERE id = ? AND shop_id = ? "
                             "AND active = 1", (pid, shop_id)).fetchone()
        if product is None:
            raise BillError("An item on this bill is no longer in Inventory")
        if qty > product["stock"]:
            raise BillError(f"Not enough stock of {product['name']}: the bill needs {qty} but "
                            f"only {product['stock']} left. Nothing was changed.")


def save_bill(db, shop_id, items, customer_name, customer_phone="", place_of_sale="",
              order_source="", order_source_other="", payments=None,
              customer_location="", due_amount="", whole_discount="",
              shipping="", replaces=None, offer_ids=(), customer_type="Retail",
              order_date="", customer_id=None, draft=False, draft_id=None):
    """Save a bill and lower the stock, all in one go. Returns the bill's id.

    With `replaces` (the id of a saved bill), this is an edit: the old bill's items go back
    into stock, the new bill takes its items out, and the old bill is marked Cancelled with a
    link to the new one. It is still one transaction.

    With `draft=True` the bill is kept as a Draft: stock is not touched or checked, and no
    customer record is made. With `draft_id` (a Draft's id) that same bill is updated in place
    (still a draft with `draft=True`), or finalised with `draft=False`: the stock is checked for
    every item and then taken out, and the bill keeps its number.

    If anything fails, nothing is changed: not the bills, not the invoice number, not the stock.
    """
    if draft_id is not None and replaces is not None:
        raise BillError("Something is wrong with this bill")
    # Who the bill is for is worked out inside the transaction (see resolve_for_bill); here we
    # only check what can be checked without touching the database.
    customer_name = (customer_name or "").strip()
    customer_phone = str(customer_phone or "")
    from .customers import normalize_phone
    _, phone_error = normalize_phone(customer_phone)
    if phone_error:
        raise BillError(phone_error)
    if draft and not (order_source or "").strip():
        source = ""                                 # a draft may be saved before it is complete
    else:
        source = clean_choice(order_source, order_source_other,
                              choices.with_other(db, shop_id, "source"), "order source")
    pay_modes = choices.with_other(db, shop_id, "method")
    typed_whole = str(whole_discount if whole_discount is not None else "").strip()
    whole_pct = parse_percent(typed_whole, "The whole-bill discount") if typed_whole else None
    shipping_paise = parse_shipping(shipping)
    if customer_type not in CUSTOMER_TYPES:
        raise BillError("Please choose Retail or B2B")
    now = datetime.now()
    # A bill finalised from a draft is dated the day it is finalised.
    day = now.date() if (draft_id is not None and not draft) else check_order_date(order_date)
    # The chosen day with the time of saving, so bills on the same day stay in order.
    created_at = datetime.combine(day, now.time()).isoformat(timespec="seconds")
    try:
        with db:  # one transaction: commits at the end, or undoes everything on an error
            old_draft = None
            if draft_id is not None:
                old_draft = db.execute("SELECT * FROM bills WHERE id = ? AND shop_id = ?",
                                       (draft_id, shop_id)).fetchone()
                if old_draft is None:
                    raise BillError("That bill wasn't found")
                if old_draft["status"] != "Draft":
                    raise BillError("This bill is not a draft any more")
                if not draft:
                    check_stock(db, shop_id, items)
            if replaces is not None:
                put_old_items_back(db, shop_id, replaces)
            # Priced inside the transaction, so an edit sees the stock the old bill gave back.
            offers = load_offers(db, shop_id, offer_ids)
            priced = price_details(db, shop_id, items, whole_pct, shipping_paise, offers,
                                   check_stock=not draft)
            lines, total = priced["lines"], priced["total"]
            due = check_due(due_amount, total)
            if draft and not any((p.get("mode") or "").strip() for p in payments or []):
                payments = []                       # no payment chosen yet
            else:
                payments = check_payments(payments, total - due, pay_modes)
            # The bill keeps its own copy of the name and phone it was made with.
            if draft:
                from .customers import WALK_IN, get as get_customer
                customer_name = customer_name or WALK_IN
                customer_phone, _ = normalize_phone(customer_phone)
                customer_id = (customer_id if customer_id and
                               get_customer(db, shop_id, customer_id) else 0)
            else:
                customer_id, customer_name, customer_phone = resolve_for_bill(
                    db, shop_id, customer_id, customer_name, customer_phone,
                    customer_location, customer_type)
            values = (customer_name, customer_phone, (customer_location or "").strip(),
                      place_of_sale.strip(), source, total, due, float(priced["whole_pct"]),
                      shipping_paise, ",".join(str(o["id"]) for o in offers),
                      ", ".join(priced["offers_applied"]), customer_type, priced["round_off"],
                      customer_id)
            if old_draft is not None:
                # The same bill, in place: id, bill number and draft date stay as they were.
                bill_id = draft_id
                db.execute(
                    "UPDATE bills SET customer_name = ?, customer_phone = ?, customer_location = ?, "
                    "place_of_sale = ?, order_source = ?, total = ?, due_amount = ?, "
                    "whole_discount_pct = ?, shipping = ?, offer_ids = ?, offers_applied = ?, "
                    "customer_type = ?, round_off = ?, customer_id = ?, status = ?, created_at = ? "
                    "WHERE id = ?",
                    values + ("Draft" if draft else "Saved", created_at, bill_id))
                db.execute("DELETE FROM payments WHERE bill_id = ?", (bill_id,))
                db.execute("DELETE FROM bill_lines WHERE bill_id = ?", (bill_id,))
            else:
                shop = db.execute("SELECT next_invoice_number FROM shops WHERE id = ?",
                                  (shop_id,)).fetchone()
                number = shop["next_invoice_number"]       # internal; the owner sees the label
                fy, seq, label = next_bill_label(db, shop_id, day)
                db.execute("UPDATE shops SET next_invoice_number = ? WHERE id = ?",
                           (number + 1, shop_id))
                bill_id = db.execute(
                    "INSERT INTO bills (shop_id, invoice_number, created_at, customer_name, "
                    "customer_phone, customer_location, place_of_sale, order_source, total, "
                    "due_amount, whole_discount_pct, shipping, offer_ids, "
                    "offers_applied, customer_type, round_off, customer_id, replaces, fy, "
                    "bill_seq, bill_label, status, draft_created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (shop_id, number, created_at) + values + (
                        replaces, fy, seq, label, "Draft" if draft else "Saved",
                        now.isoformat(timespec="seconds") if draft else "")).lastrowid
            if replaces is not None:
                db.execute("UPDATE bills SET status = 'Cancelled', replaced_by = ? "
                           "WHERE id = ?", (bill_id, replaces))
            for mode, amount in payments:
                db.execute("INSERT INTO payments (bill_id, mode, amount) VALUES (?, ?, ?)",
                           (bill_id, mode, amount))
            for line in lines:
                db.execute(
                    "INSERT INTO bill_lines (bill_id, product_id, code, name, quantity, "
                    "rate, line_discount_pct, line_amount, cost, gst_rate) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (bill_id, line["product_id"], line["code"], line["name"],
                     line["quantity"], line["rate"], line["line_discount_pct"],
                     line["line_amount"], line["cost"], line["gst_rate"]))
                if draft:
                    continue                        # a draft never touches stock
                # The "stock >= ?" check makes this safe even if the page was out of date.
                changed = db.execute(
                    "UPDATE products SET stock = stock - ? WHERE id = ? AND stock >= ?",
                    (line["quantity"], line["product_id"], line["quantity"])).rowcount
                if changed != 1:
                    raise BillError(f"Not enough stock of {line['name']}; "
                                    "please change the quantity")
    except BillError:
        raise
    except CustomerError as e:
        raise BillError(str(e))
    except Exception:
        raise BillError("Couldn't save the bill; nothing was changed")
    return bill_id


def delete_draft(db, shop_id, bill_id):
    """Throw a draft away. It never took any stock, so there is nothing to put back."""
    with db:
        bill = db.execute("SELECT status FROM bills WHERE id = ? AND shop_id = ?",
                          (bill_id, shop_id)).fetchone()
        if bill is None:
            raise BillError("That bill wasn't found")
        if bill["status"] != "Draft":
            raise BillError("Only a draft can be deleted")
        db.execute("DELETE FROM payments WHERE bill_id = ?", (bill_id,))
        db.execute("DELETE FROM bill_lines WHERE bill_id = ?", (bill_id,))
        db.execute("DELETE FROM bills WHERE id = ?", (bill_id,))


def put_old_items_back(db, shop_id, bill_id):
    """Give a saved bill's items back to stock, ready for it to be replaced.

    Must be called inside the transaction that then saves the replacement bill.
    """
    old = db.execute("SELECT * FROM bills WHERE id = ? AND shop_id = ?",
                     (bill_id, shop_id)).fetchone()
    if old is None:
        raise BillError("That bill wasn't found")
    if old["status"] == "Draft":
        raise BillError("A draft hasn't taken any stock. Delete the draft instead")
    if old["status"] != "Saved" or old["replaced_by"] is not None:
        raise BillError("This bill has already been cancelled or replaced")
    for line in db.execute("SELECT product_id, quantity FROM bill_lines WHERE bill_id = ?",
                           (bill_id,)).fetchall():
        # By product id, even if the product has since been removed from Inventory.
        db.execute("UPDATE products SET stock = stock + ? WHERE id = ? AND shop_id = ?",
                   (line["quantity"], line["product_id"], shop_id))

def cancel_bill(db, shop_id, bill_id):
    """Cancel a saved bill without replacing it (for example, everything was returned).

    The items go back into stock and the bill stays in Past bills, marked Cancelled.
    """
    with db:
        put_old_items_back(db, shop_id, bill_id)
        db.execute("UPDATE bills SET status = 'Cancelled' WHERE id = ?", (bill_id,))

def bill_status(bill):
    """The status the owner sees on a bill, and the colour class for it.

    Draft and Cancelled win; otherwise a bill with money still due is 'Payment due', else 'Paid'.
    """
    if bill["status"] == "Draft":
        return "Draft", "draft"
    if bill["status"] == "Cancelled":
        return "Cancelled", "cancelled"
    if bill["due_amount"] > 0:
        return "Payment due", "due"
    return "Paid", "paid"

def receive_due(db, shop_id, bill_id, mode, other=""):
    """The customer has paid what was due. Records it as a payment and clears the due amount."""
    mode = clean_choice(mode, other, choices.with_other(db, shop_id, "method"), "payment mode")
    with db:
        bill = db.execute("SELECT * FROM bills WHERE id = ? AND shop_id = ?",
                          (bill_id, shop_id)).fetchone()
        if bill is None:
            raise BillError("That bill wasn't found")
        if bill["status"] == "Draft":
            raise BillError("This bill is still a draft. Save it as a bill first")
        if bill["status"] != "Saved":
            raise BillError("This bill is cancelled")
        if bill["due_amount"] <= 0:
            raise BillError("Nothing is due on this bill")
        db.execute("INSERT INTO payments (bill_id, mode, amount, paid_at) VALUES (?, ?, ?, ?)",
                   (bill_id, mode, bill["due_amount"],
                    datetime.now().isoformat(timespec="seconds")))
        db.execute("UPDATE bills SET due_amount = 0, due_date = '' WHERE id = ?", (bill_id,))


def change_payment_modes(db, shop_id, bill_id, picks):
    """Change only the payment method of each payment on a bill; amounts never change.

    picks: {payment id: (mode, text typed under Other)}. Every payment of the bill is needed.
    """
    modes = choices.with_other(db, shop_id, "method")
    with db:
        bill = db.execute("SELECT status FROM bills WHERE id = ? AND shop_id = ?",
                          (bill_id, shop_id)).fetchone()
        if bill is None:
            raise BillError("That bill wasn't found")
        if bill["status"] == "Draft":
            raise BillError("This bill is still a draft, so it has no payments yet")
        rows = db.execute("SELECT id FROM payments WHERE bill_id = ?", (bill_id,)).fetchall()
        if not rows:
            raise BillError("This bill has no payments to change")
        new = {}
        for r in rows:
            mode, other = picks.get(r["id"], ("", ""))
            new[r["id"]] = clean_choice(mode, other, modes, "payment method")
        for payment_id, mode in new.items():
            db.execute("UPDATE payments SET mode = ? WHERE id = ? AND bill_id = ?",
                       (mode, payment_id, bill_id))


def prepare_bill_customer(db, shop_id, bill_id, name, phone, location, place, customer_type):
    """Check the "Edit customer" form for one bill, without saving anything.

    Returns (clean values, owner), where owner is the customer the new phone number belongs to
    when that is somebody other than the bill's own customer, otherwise None.
    """
    from .customers import find_by_phone, normalize_phone
    name, location, place = (name or "").strip(), (location or "").strip(), (place or "").strip()
    digits, error = normalize_phone(phone)
    if error:
        raise BillError(error)
    if customer_type not in CUSTOMER_TYPES:
        raise BillError("Please choose Retail or B2B")
    bill = db.execute("SELECT * FROM bills WHERE id = ? AND shop_id = ?", (bill_id, shop_id)).fetchone()
    if bill is None:
        raise BillError("That bill wasn't found")
    if not name:
        if bill["customer_id"]:
            raise BillError("Please enter the customer's name")
        name = "Walk-in customer"
    clean = {"customer_name": name, "customer_phone": digits, "customer_location": location,
             "place_of_sale": place, "customer_type": customer_type}
    owner = find_by_phone(db, shop_id, digits)
    return clean, (owner if owner is not None and owner["id"] != bill["customer_id"] else None)


def save_bill_customer(db, shop_id, bill_id, clean):
    """Write the checked "Edit customer" details onto this one bill. Returns what it said before."""
    before = db.execute("SELECT id, customer_name, customer_phone, customer_location, "
                        "place_of_sale, customer_type FROM bills WHERE id = ? AND shop_id = ?",
                        (bill_id, shop_id)).fetchone()
    try:
        with db:
            db.execute("UPDATE bills SET customer_name = ?, customer_phone = ?, "
                       "customer_location = ?, place_of_sale = ?, customer_type = ? WHERE id = ?",
                       (clean["customer_name"], clean["customer_phone"], clean["customer_location"],
                        clean["place_of_sale"], clean["customer_type"], bill_id))
    except Exception:
        raise BillError("Couldn't save the changes; nothing was changed")
    return dict(before)
