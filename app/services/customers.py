"""The shop's saved customers. Plain Python, no Flask in here.

A customer with a phone number is found by that number alone, never by name. A customer
without one is saved under a label like "Retail - Asha" and found again by that label.
"""


def phone_key(phone):
    """'98765 43210' -> '9876543210': only the digits, so spacing never matters."""
    return "".join(c for c in str(phone or "") if c.isdigit())


def find_by_phone(db, shop_id, phone):
    key = phone_key(phone)
    if not key:
        return None
    return db.execute("SELECT * FROM customers WHERE shop_id = ? AND phone_key = ?",
                      (shop_id, key)).fetchone()


def save_customer(db, shop_id, name, phone, location, customer_type):
    """Add the customer, or update the saved one. Returns the customer's id.

    Call inside the transaction that saves the bill.
    """
    name, phone, location = name.strip(), phone.strip(), location.strip()
    key = phone_key(phone)
    if key:
        found = find_by_phone(db, shop_id, phone)
        label = name
    else:
        label = f"{customer_type} - {name}"
        found = db.execute("SELECT * FROM customers WHERE shop_id = ? AND phone_key = '' "
                           "AND lower(name) = lower(?)", (shop_id, label)).fetchone()
    if found is None:
        return db.execute(
            "INSERT INTO customers (shop_id, name, phone, phone_key, location, customer_type) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (shop_id, label, phone, key, location, customer_type)).lastrowid
    # The latest bill's details win, but a blank never wipes out something already saved.
    db.execute("UPDATE customers SET name = ?, phone = ?, location = ?, customer_type = ? "
               "WHERE id = ?", (label, phone or found["phone"], location or found["location"],
                                customer_type, found["id"]))
    return found["id"]
