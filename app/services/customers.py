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
    * No phone and no name is refused: the customer's name is always needed.
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
    raise CustomerError("Please enter the customer's name")


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


UNDO_SECONDS = 30


def stats(db, shop_id, customer_id):
    """Saved-bill count, total billed and last bill date (ISO) of one customer."""
    row = db.execute("SELECT COUNT(*) AS n, COALESCE(SUM(total), 0) AS spent, MAX(created_at) AS last "
                     "FROM bills WHERE customer_id = ? AND shop_id = ? AND status = 'Saved'",
                     (customer_id, shop_id)).fetchone()
    return {"bill_count": row["n"], "spent": row["spent"], "last_bill": row["last"] or ""}


def bill_ids_of(db, customer_id):
    """Every bill linked to a customer, cancelled ones too."""
    return [r[0] for r in db.execute("SELECT id FROM bills WHERE customer_id = ? ORDER BY id",
                                     (customer_id,))]


def plan_for_bill(db, shop_id, bill, owner):
    """What "Yes, same person" would do when a bill's phone is changed to `owner`'s number.

    * the bill is a walk-in: only this bill is linked to the owner;
    * its customer has no phone, or this is their only bill: all their bills move to the owner
      and the now-empty customer is removed;
    * its customer has their own phone and other bills: only this bill moves, the customer stays.
    Returns {"mode": "link" | "all" | "one", "current": row or None, "bill_ids": [...]}.
    """
    current = get(db, shop_id, bill["customer_id"]) if bill["customer_id"] else None
    if current is None:
        return {"mode": "link", "current": None, "bill_ids": [bill["id"]]}
    mine = bill_ids_of(db, current["id"])
    if not current["phone"] or mine == [bill["id"]]:
        return {"mode": "all", "current": current, "bill_ids": mine}
    return {"mode": "one", "current": current, "bill_ids": [bill["id"]]}


def plan_for_customer(db, shop_id, customer, owner):
    """"Yes, same person" on Customer Details: all of this customer's bills move, and they go."""
    return {"mode": "all", "current": customer, "bill_ids": bill_ids_of(db, customer["id"])}


def combine(db, shop_id, owner_id, plan, return_to, bill_before=None):
    """Do what a plan says and remember how to undo it. Returns the Undo token.

    Only the link between a bill and its customer changes; what bills printed never does.
    The customer who owns the phone keeps their own details, with a blank location filled in
    from the other record. Call inside no other transaction.
    """
    import json
    import secrets
    import time
    owner = get(db, shop_id, owner_id)
    current = plan["current"]
    if owner is None:
        raise CustomerError("That customer wasn't found")
    marks = ",".join("?" * len(plan["bill_ids"])) or "NULL"
    with db:
        previous = [[r["id"], r["customer_id"]] for r in db.execute(
            f"SELECT id, customer_id FROM bills WHERE id IN ({marks}) AND shop_id = ?",
            [*plan["bill_ids"], shop_id])]
        db.execute(f"UPDATE bills SET customer_id = ? WHERE id IN ({marks}) AND shop_id = ?",
                   [owner["id"], *plan["bill_ids"], shop_id])
        if current is not None and not owner["location"] and current["location"]:
            db.execute("UPDATE customers SET location = ? WHERE id = ?",
                       (current["location"], owner["id"]))
        removed = None
        if plan["mode"] == "all" and current is not None:
            removed = dict(current)
            db.execute("DELETE FROM customers WHERE id = ?", (current["id"],))
        token = secrets.token_urlsafe(16)
        db.execute("DELETE FROM undo_actions WHERE created < ?", (time.time() - 86400,))
        db.execute("INSERT INTO undo_actions (token, shop_id, created, payload) VALUES (?, ?, ?, ?)",
                   (token, shop_id, time.time(), json.dumps({
                       "owner_id": owner["id"], "owner_location": owner["location"],
                       "previous_links": previous, "removed_customer": removed,
                       "bill_before": bill_before, "return_to": return_to})))
    return token


def undo_left(db, shop_id, token):
    """Whole seconds left to undo, or 0 if it is used up, too old or not this shop's."""
    import time
    row = db.execute("SELECT created, used FROM undo_actions WHERE token = ? AND shop_id = ?",
                     (token or "", shop_id)).fetchone()
    if row is None or row["used"]:
        return 0
    return max(0, int(UNDO_SECONDS - (time.time() - row["created"])))


def undo(db, shop_id, token):
    """Put back the links, the removed customer and the bill's printed details.

    Returns the address to go back to, or None when the Undo is no longer available.
    """
    import json
    if not undo_left(db, shop_id, token):
        return None
    row = db.execute("SELECT payload FROM undo_actions WHERE token = ?", (token,)).fetchone()
    data = json.loads(row["payload"])
    with db:
        removed = data["removed_customer"]
        if removed:
            columns = list(removed)
            try:
                db.execute(f"INSERT INTO customers ({', '.join(columns)}) "
                           f"VALUES ({', '.join('?' * len(columns))})", [removed[c] for c in columns])
            except sqlite3_integrity_error():
                removed["phone"] = ""       # somebody has taken the number meanwhile
                db.execute(f"INSERT INTO customers ({', '.join(columns)}) "
                           f"VALUES ({', '.join('?' * len(columns))})", [removed[c] for c in columns])
        for bill_id, customer_id in data["previous_links"]:
            db.execute("UPDATE bills SET customer_id = ? WHERE id = ? AND shop_id = ?",
                       (customer_id, bill_id, shop_id))
        db.execute("UPDATE customers SET location = ? WHERE id = ? AND shop_id = ?",
                   (data["owner_location"], data["owner_id"], shop_id))
        before = data["bill_before"]
        if before:
            db.execute("UPDATE bills SET customer_name = ?, customer_phone = ?, customer_location = ?, "
                       "place_of_sale = ?, customer_type = ? WHERE id = ? AND shop_id = ?",
                       (before["customer_name"], before["customer_phone"], before["customer_location"],
                        before["place_of_sale"], before["customer_type"], before["id"], shop_id))
        db.execute("UPDATE undo_actions SET used = 1 WHERE token = ?", (token,))
    return data["return_to"]


def sqlite3_integrity_error():
    import sqlite3
    return sqlite3.IntegrityError


def delete_if_unused(db, shop_id, customer_id):
    """Remove a customer who has no bills at all. Returns True if removed."""
    if get(db, shop_id, customer_id) is None:
        return False
    with db:
        if db.execute("SELECT 1 FROM bills WHERE customer_id = ?", (customer_id,)).fetchone():
            return False
        db.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
    return True
