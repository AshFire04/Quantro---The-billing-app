"""The shop's customers. Plain Python, no Flask in here.

A customer is identified by their id, never by their name. The phone number is the one thing
that can find a customer again, and it is unique within a shop when it is not empty. Only
Indian mobile numbers count (10 digits, starting 6 to 9).

A bill keeps its own copy of the name, phone and location it was made with, so changing a
customer later never changes what was printed.
"""
WALK_IN = "Walk-in customer"
MOBILE_MESSAGE = "Enter a 10-digit mobile number starting with 6, 7, 8 or 9."


class CustomerError(Exception):
    """Something about the customer that the owner must fix. The message is shown as-is."""


class PhoneTaken(CustomerError):
    """The phone number already belongs to another customer (`owner`)."""

    def __init__(self, owner):
        super().__init__(f"The number {owner['phone']} already belongs to {owner['name']}.")
        self.owner = owner


def normalize_phone(text):
    """'+91 98765-43210' or '098765 43210' -> '9876543210'. Returns (digits, error).

    Spaces, dashes, brackets, a +91 / 91 / 0091 start and a leading 0 are taken off. What is
    left must be 10 digits starting 6 to 9. An empty box is fine and gives ('', None).
    """
    digits = "".join(c for c in str(text or "") if c.isdigit())
    if not digits:
        return "", (MOBILE_MESSAGE if str(text or "").strip() else None)   # letters only: not a number
    if len(digits) == 14 and digits.startswith("0091"):
        digits = digits[4:]
    elif len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10 and digits[0] in "6789":
        return digits, None
    return "", MOBILE_MESSAGE


def get(db, shop_id, customer_id):
    try:
        customer_id = int(customer_id)
    except (TypeError, ValueError):
        return None
    return db.execute("SELECT * FROM customers WHERE id = ? AND shop_id = ?",
                      (customer_id, shop_id)).fetchone()


def find_by_phone(db, shop_id, digits):
    if not digits:
        return None
    return db.execute("SELECT * FROM customers WHERE shop_id = ? AND phone = ?",
                      (shop_id, digits)).fetchone()


def listing(db, shop_id, q="", order="c.name COLLATE NOCASE", limit=None, start="", end="",
            customer_type=""):
    """Customers with their bill count, total billed and last bill date.

    With `start` and/or `end` ('YYYY-MM-DD'), only bills in that period are counted and only
    customers who have one are listed. `customer_type` ('Retail' or 'B2B') narrows the list.
    """
    join, join_params = "b.customer_id = c.id AND b.status = 'Saved'", []
    if start:
        join += " AND substr(b.created_at, 1, 10) >= ?"
        join_params.append(start)
    if end:
        join += " AND substr(b.created_at, 1, 10) <= ?"
        join_params.append(end)
    sql = ("SELECT c.*, COUNT(b.id) AS bill_count, COALESCE(SUM(b.total), 0) AS spent, "
           f"MAX(b.created_at) AS last_bill FROM customers c LEFT JOIN bills b ON {join} "
           "WHERE c.shop_id = ?")
    params = join_params + [shop_id]
    if customer_type:
        sql += " AND c.customer_type = ?"
        params.append(customer_type)
    q = q.strip()
    if q:
        digits = "".join(c for c in q if c.isdigit())
        clauses = ["c.name LIKE ?", "c.location LIKE ?"]
        params += [f"%{q}%"] * 2
        if len(digits) >= 3:
            clauses.append("c.phone LIKE ?")
            params.append(f"%{digits}%")
        sql += " AND (" + " OR ".join(clauses) + ")"
    sql += " GROUP BY c.id"
    if start or end:
        sql += " HAVING COUNT(b.id) > 0"
    sql += f" ORDER BY {order}"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return db.execute(sql, params).fetchall()


def create(db, shop_id, name, phone, location, customer_type):
    """Add a customer (phone already checked and normalised). Returns the new id."""
    return db.execute(
        "INSERT INTO customers (shop_id, name, phone, location, customer_type) "
        "VALUES (?, ?, ?, ?, ?)",
        (shop_id, name.strip(), phone, location.strip(), customer_type)).lastrowid


def resolve_for_bill(db, shop_id, customer_id, name, phone_text, location, customer_type):
    """Decide which customer a new bill belongs to. Returns (customer id, name, phone).

    Call inside the transaction that saves the bill. Saving a bill never edits an existing
    customer; it only links to one or creates a new one.

    * A customer picked on the screen (customer_id) is used, unless the phone typed belongs
      to somebody else.
    * Otherwise a phone number that already exists is that customer, so there are no duplicates.
    * A new phone number makes a new customer (the name is needed).
    * No phone but a name makes a new customer without a phone. The name never finds anyone.
    * No phone and no name is a walk-in: no customer record (id 0).
    """
    digits, error = normalize_phone(phone_text)
    if error:
        raise CustomerError(error)
    name = name.strip()
    owner = find_by_phone(db, shop_id, digits)
    if customer_id:
        picked = get(db, shop_id, customer_id)
        if picked is None:
            raise CustomerError("That customer wasn't found. Please pick them again.")
        if owner is not None and owner["id"] != picked["id"]:
            raise CustomerError(f"The number {digits} belongs to {owner['name']}. "
                                "Pick that customer, or clear the customer to continue.")
        return picked["id"], name or picked["name"], digits
    if owner is not None:
        return owner["id"], name or owner["name"], digits
    if digits:
        if not name:
            raise CustomerError("Please enter the customer's name for a new phone number")
        return create(db, shop_id, name, digits, location, customer_type), name, digits
    if name:
        return create(db, shop_id, name, "", location, customer_type), name, ""
    return 0, WALK_IN, ""


def update(db, shop_id, customer_id, name, phone_text, location, customer_type):
    """Change a customer's record. It affects future bills only; printed bills keep their copy.

    Raises PhoneTaken if the number belongs to another customer.
    """
    customer = get(db, shop_id, customer_id)
    if customer is None:
        raise CustomerError("That customer wasn't found")
    name = name.strip()
    if not name:
        raise CustomerError("Please enter the customer's name")
    digits, error = normalize_phone(phone_text)
    if error:
        raise CustomerError(error)
    owner = find_by_phone(db, shop_id, digits)
    if owner is not None and owner["id"] != customer["id"]:
        raise PhoneTaken(owner)
    with db:
        db.execute("UPDATE customers SET name = ?, phone = ?, location = ?, "
                   "customer_type = ?, legacy = ? WHERE id = ?",
                   (name, digits, location.strip(), customer_type,
                    1 if customer["legacy"] and not digits else 0, customer["id"]))


def merge(db, shop_id, source_id, target_id):
    """Join two customers: every bill of `source` moves to `target`, and `source` is removed.

    The target keeps its own details, except that if it has no phone and the source has one,
    the number is copied over. Printed bills are not touched. Returns what happened.
    """
    source, target = get(db, shop_id, source_id), get(db, shop_id, target_id)
    if source is None or target is None:
        raise CustomerError("That customer wasn't found")
    if source["id"] == target["id"]:
        raise CustomerError("Pick a different customer to merge into")
    with db:
        moved = db.execute("UPDATE bills SET customer_id = ? WHERE customer_id = ?",
                           (target["id"], source["id"])).rowcount
        db.execute("DELETE FROM customers WHERE id = ?", (source["id"],))
        copied = bool(source["phone"] and not target["phone"])
        if copied:                       # after the delete, so the number is never in two rows
            db.execute("UPDATE customers SET phone = ?, legacy = 0 WHERE id = ?",
                       (source["phone"], target["id"]))
    return {"moved": moved, "copied_phone": copied,
            "dropped_phone": source["phone"] if source["phone"] and target["phone"]
            and source["phone"] != target["phone"] else ""}


def move_bill(db, shop_id, bill_id, customer_id):
    """Link one bill to another customer. What the bill printed stays as it was."""
    bill = db.execute("SELECT id FROM bills WHERE id = ? AND shop_id = ?",
                      (bill_id, shop_id)).fetchone()
    if bill is None:
        raise CustomerError("That bill wasn't found")
    if get(db, shop_id, customer_id) is None:
        raise CustomerError("That customer wasn't found")
    with db:
        db.execute("UPDATE bills SET customer_id = ? WHERE id = ?", (int(customer_id), bill_id))


def delete_if_unused(db, shop_id, customer_id):
    """Remove a customer who has no bills at all. Returns True if removed."""
    if get(db, shop_id, customer_id) is None:
        return False
    with db:
        if db.execute("SELECT 1 FROM bills WHERE customer_id = ?", (customer_id,)).fetchone():
            return False
        db.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
    return True
