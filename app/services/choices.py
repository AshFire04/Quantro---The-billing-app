"""The shop's own lists of order sources ("Order came through") and payment methods.

Each shop picks these in Shop Details. The Billing screen, Past bills, the bill page and the
Excel downloads all read them from here. "Other" is always available on a bill as well, for
anything that isn't in the list, and is not stored in the list itself.
"""

KINDS = {
    "source": {"table": "order_sources", "what": "order source"},
    "method": {"table": "payment_methods", "what": "payment method"},
    "category": {"table": "product_categories", "what": "category"},
    "supplier": {"table": "suppliers", "what": "supplier"},
}
# Order sources and payment methods are picked on a bill (with "Other" typed there), and one
# of each can be the starting choice. Categories and suppliers are picked when adding a product.
DEFAULT_COLUMN = {"source": "default_source", "method": "default_method"}

DEFAULT_SOURCES = ["Walk-in", "WhatsApp", "Instagram", "Phone call"]
DEFAULT_METHODS = ["Cash", "UPI", "Card", "Bank transfer"]
MAX_NAME = 40


def table_for(kind):
    return KINDS[kind]["table"]


def names(db, shop_id, kind):
    """The shop's list, in the order the owner added it."""
    return [r["name"] for r in db.execute(
        f"SELECT name FROM {table_for(kind)} WHERE shop_id = ? ORDER BY position, id", (shop_id,))]


def rows(db, shop_id, kind):
    return db.execute(f"SELECT id, name FROM {table_for(kind)} WHERE shop_id = ? "
                      "ORDER BY position, id", (shop_id,)).fetchall()


def with_other(db, shop_id, kind):
    """What a bill's dropdown offers: the shop's list, then 'Other' (typed on the bill)."""
    return names(db, shop_id, kind) + ["Other"]


def seed_defaults(db, shop_id):
    """A new shop starts with a few common choices it can change."""
    for kind, defaults in (("source", DEFAULT_SOURCES), ("method", DEFAULT_METHODS)):
        for position, name in enumerate(defaults):
            db.execute(f"INSERT INTO {table_for(kind)} (shop_id, name, position) VALUES (?, ?, ?)",
                       (shop_id, name, position))


def add(db, shop_id, kind, name):
    """Add a choice. Returns an error message, or None when it was added."""
    name = " ".join(str(name or "").split())
    what = KINDS[kind]["what"]
    if not name:
        return f"Please type the {what} to add"
    if len(name) > MAX_NAME:
        return f"Keep the {what} under {MAX_NAME} characters"
    if kind in DEFAULT_COLUMN and (name.lower() == "other" or name.lower().startswith("other:")):
        return "\"Other\" is always there on a bill, so it doesn't need adding"
    if name.lower() in [n.lower() for n in names(db, shop_id, kind)]:
        return f"\"{name}\" is already in the list"
    table = table_for(kind)
    last = db.execute(f"SELECT COALESCE(MAX(position), -1) FROM {table} WHERE shop_id = ?",
                      (shop_id,)).fetchone()[0]
    with db:
        db.execute(f"INSERT INTO {table} (shop_id, name, position) VALUES (?, ?, ?)",
                   (shop_id, name, last + 1))
    return None


def remove(db, shop_id, kind, choice_id):
    """Remove a choice from the list. Bills (and products) already made keep the name as text."""
    table = table_for(kind)
    with db:
        row = db.execute(f"SELECT name FROM {table} WHERE id = ? AND shop_id = ?",
                         (choice_id, shop_id)).fetchone()
        if row is None:
            return False
        db.execute(f"DELETE FROM {table} WHERE id = ?", (choice_id,))
        column = DEFAULT_COLUMN.get(kind)
        if column:                       # the starting choice can't be one that no longer exists
            db.execute(f"UPDATE shops SET {column} = '' WHERE id = ? AND {column} = ?",
                       (shop_id, row["name"]))
    return True


def default_of(db, shop_id, kind):
    """The choice a new bill starts with, or '' when none is set (or it was removed)."""
    column = DEFAULT_COLUMN.get(kind)
    if not column:
        return ""
    value = db.execute(f"SELECT {column} FROM shops WHERE id = ?", (shop_id,)).fetchone()[0]
    return value if value in names(db, shop_id, kind) else ""


def set_default(db, shop_id, kind, name):
    """Choose which of the shop's choices a new bill starts with ('' for none).
    Returns an error message, or None when saved."""
    column = DEFAULT_COLUMN[kind]
    name = (name or "").strip()
    if name and name not in names(db, shop_id, kind):
        return f"Please choose one of the {KINDS[kind]['what']}s in the list"
    with db:
        db.execute(f"UPDATE shops SET {column} = ? WHERE id = ?", (name, shop_id))
    return None


def used_by_products(db, shop_id, kind):
    """Categories or suppliers that active products already carry (maybe not in the list)."""
    column = "category" if kind == "category" else "supplier"
    return [r[0] for r in db.execute(
        f"SELECT DISTINCT {column} FROM products WHERE shop_id = ? AND active = 1 "
        f"AND {column} != '' ORDER BY {column} COLLATE NOCASE", (shop_id,))]


def product_filter_options(db, shop_id, kind):
    """For the Inventory filters: the shop's list, then anything products still carry."""
    listed = names(db, shop_id, kind)
    extra = [v for v in used_by_products(db, shop_id, kind) if v not in listed]
    return listed + extra


def used_values(db, shop_id, kind):
    """Names that appear on this shop's bills, so filters can still find old bills after a
    choice was removed. 'Other: ...' entries are left out (they are filtered as 'Other')."""
    if kind == "source":
        sql = "SELECT DISTINCT order_source FROM bills WHERE shop_id = ?"
    else:
        sql = ("SELECT DISTINCT p.mode FROM payments p JOIN bills b ON b.id = p.bill_id "
               "WHERE b.shop_id = ?")
    return [r[0] for r in db.execute(sql, (shop_id,)) if r[0] and not r[0].startswith("Other")]


def filter_options(db, shop_id, kind):
    """For the Past bills filters: the list, anything older bills used, then 'Other'."""
    listed = names(db, shop_id, kind)
    old = sorted(v for v in used_values(db, shop_id, kind) if v not in listed)
    return listed + old + ["Other"]
