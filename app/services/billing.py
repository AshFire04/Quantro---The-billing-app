"""The money and stock rules. Plain Python, no Flask in here, so tests can call it directly.

All amounts are whole paise. The browser's numbers are never trusted: everything is
recalculated here from the products in the database.
"""
from datetime import datetime
from decimal import Decimal, InvalidOperation

from .money import format_rupees, rupees_to_paise, take_percent_off

PAYMENT_MODES = ["UPI", "Cash", "Net-banking", "Other"]
ORDER_SOURCES = ["Store (walk-in)", "Stall", "Website", "Other"]


class BillError(Exception):
    """A bill that can't be saved. The message is shown to the owner as-is."""


def clean_choice(value, other, allowed, what):
    """A dropdown answer. 'Other' needs the typed text and is stored as 'Other: text'."""
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


def check_due(due_amount, due_date, total):
    """The part of the bill still to be paid, and when. Returns (paise, 'YYYY-MM-DD' or '')."""
    try:
        due = rupees_to_paise(due_amount) if str(due_amount or "").strip() else 0
    except ValueError:
        raise BillError("Enter the amount due as a number, like 500 or 500.50")
    if due == 0:
        return 0, ""
    if due > total:
        raise BillError("The amount due can't be more than the bill total")
    try:
        date = datetime.strptime(str(due_date or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        raise BillError("Please choose the date the payment is due")
    if date < datetime.now().date():
        raise BillError("The due date can't be in the past")
    return due, date.isoformat()


def check_payments(payments, total):
    """Turn the payments from the page into [(mode, paise)] that add up to `total`.

    `total` is what is being paid now: the bill total minus any amount left due.
    One payment with no amount means "all of it". Several payments (a split) must
    each have an amount, and the amounts must add up exactly.
    """
    if total == 0:
        return []                     # the whole bill is due later, so nothing is paid now
    if not payments:
        raise BillError("Please choose how the customer paid")
    checked = []
    whole_bill = len(payments) == 1 and str(payments[0].get("amount") or "").strip() == ""
    for p in payments:
        mode = clean_choice(p.get("mode"), p.get("other"), PAYMENT_MODES, "payment mode")
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


def price_bill(db, shop_id, items, whole_discount_pct=Decimal(0), shipping=0):
    """Work out the lines and total for a bill.

    items: [{"product_id": 3, "quantity": 2, "discount": "10"}, ...]  (discount is optional)
    The order is: each item's own discount first, then the whole-bill discount on the
    sum of those, then shipping & handling is added last.
    Returns (lines, total). Raises BillError if a product is missing or stock is short.
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
        discount = parse_percent(item.get("discount"), "An item discount")
        if product_id in wanted:
            wanted[product_id][0] += quantity       # the first discount typed is kept
        else:
            wanted[product_id] = [quantity, discount]
    if not wanted:
        raise BillError("Add at least one item to the bill")

    lines = []
    for product_id, (quantity, discount) in wanted.items():
        product = db.execute(
            "SELECT * FROM products WHERE id = ? AND shop_id = ? AND active = 1",
            (product_id, shop_id)).fetchone()
        if product is None:
            raise BillError("An item on this bill is no longer in Inventory")
        if quantity > product["stock"]:
            raise BillError(f"Only {product['stock']} left of {product['name']}; "
                            "please change the quantity")
        lines.append({
            "product_id": product_id,
            "code": product["code"],
            "name": product["name"],
            "quantity": quantity,
            "rate": product["price"],
            "line_discount_pct": float(discount),
            "line_amount": take_percent_off(product["price"] * quantity, discount),
        })
    subtotal = sum(line["line_amount"] for line in lines)
    total = take_percent_off(subtotal, whole_discount_pct) + shipping
    return lines, total


def save_bill(db, shop_id, items, customer_name, customer_phone="", place_of_sale="",
              order_source="", order_source_other="", payments=None,
              customer_location="", due_amount="", due_date="", whole_discount="",
              shipping="", replaces=None):
    """Save a bill and lower the stock, all in one go. Returns the new bill's id.

    With `replaces` (the id of a saved bill), this is an edit: the old bill's items go back
    into stock, the new bill takes its items out, and the old bill is marked Cancelled with a
    link to the new one. It is still one transaction.

    If anything fails, nothing is changed: not the bills, not the invoice number, not the stock.
    """
    customer_name = customer_name.strip()
    customer_phone = customer_phone.strip()
    if not customer_name:
        raise BillError("Please enter the customer's name")
    if customer_phone and not 7 <= sum(c.isdigit() for c in customer_phone) <= 15:
        raise BillError("The phone number doesn't look right")
    source = clean_choice(order_source, order_source_other, ORDER_SOURCES, "order source")
    whole_pct = parse_percent(whole_discount, "The whole-bill discount")
    shipping_paise = parse_shipping(shipping)
    try:
        with db:  # one transaction: commits at the end, or undoes everything on an error
            if replaces is not None:
                put_old_items_back(db, shop_id, replaces)
            # Priced inside the transaction, so an edit sees the stock the old bill gave back.
            lines, total = price_bill(db, shop_id, items, whole_pct, shipping_paise)
            due, due_on = check_due(due_amount, due_date, total)
            payments = check_payments(payments, total - due)
            shop = db.execute("SELECT next_invoice_number FROM shops WHERE id = ?",
                              (shop_id,)).fetchone()
            number = shop["next_invoice_number"]
            db.execute("UPDATE shops SET next_invoice_number = ? WHERE id = ?",
                       (number + 1, shop_id))
            bill_id = db.execute(
                "INSERT INTO bills (shop_id, invoice_number, created_at, customer_name, "
                "customer_phone, customer_location, place_of_sale, order_source, total, "
                "due_amount, due_date, whole_discount_pct, shipping, replaces) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (shop_id, number, datetime.now().isoformat(timespec="seconds"),
                 customer_name, customer_phone, customer_location.strip(),
                 place_of_sale.strip(), source, total, due, due_on, float(whole_pct),
                 shipping_paise, replaces)).lastrowid
            if replaces is not None:
                db.execute("UPDATE bills SET status = 'Cancelled', replaced_by = ? "
                           "WHERE id = ?", (bill_id, replaces))
            for mode, amount in payments:
                db.execute("INSERT INTO payments (bill_id, mode, amount) VALUES (?, ?, ?)",
                           (bill_id, mode, amount))
            for line in lines:
                db.execute(
                    "INSERT INTO bill_lines (bill_id, product_id, code, name, quantity, "
                    "rate, line_discount_pct, line_amount) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (bill_id, line["product_id"], line["code"], line["name"],
                     line["quantity"], line["rate"], line["line_discount_pct"],
                     line["line_amount"]))
                # The "stock >= ?" check makes this safe even if the page was out of date.
                changed = db.execute(
                    "UPDATE products SET stock = stock - ? WHERE id = ? AND stock >= ?",
                    (line["quantity"], line["product_id"], line["quantity"])).rowcount
                if changed != 1:
                    raise BillError(f"Not enough stock of {line['name']}; "
                                    "please change the quantity")
    except BillError:
        raise
    except Exception:
        raise BillError("Couldn't save the bill; nothing was changed")
    return bill_id


def put_old_items_back(db, shop_id, bill_id):
    """Give a saved bill's items back to stock, ready for it to be replaced.

    Must be called inside the transaction that then saves the replacement bill.
    """
    old = db.execute("SELECT * FROM bills WHERE id = ? AND shop_id = ?",
                     (bill_id, shop_id)).fetchone()
    if old is None:
        raise BillError("That bill wasn't found")
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

def receive_due(db, shop_id, bill_id, mode, other=""):
    """The customer has paid what was due. Records it as a payment and clears the due amount."""
    mode = clean_choice(mode, other, PAYMENT_MODES, "payment mode")
    with db:
        bill = db.execute("SELECT * FROM bills WHERE id = ? AND shop_id = ?",
                          (bill_id, shop_id)).fetchone()
        if bill is None:
            raise BillError("That bill wasn't found")
        if bill["status"] != "Saved":
            raise BillError("This bill is cancelled")
        if bill["due_amount"] <= 0:
            raise BillError("Nothing is due on this bill")
        db.execute("INSERT INTO payments (bill_id, mode, amount, paid_at) VALUES (?, ?, ?, ?)",
                   (bill_id, mode, bill["due_amount"],
                    datetime.now().isoformat(timespec="seconds")))
        db.execute("UPDATE bills SET due_amount = 0, due_date = '' WHERE id = ?", (bill_id,))




