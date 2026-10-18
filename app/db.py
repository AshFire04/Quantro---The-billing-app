import sqlite3

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS shops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT DEFAULT '',
    website TEXT DEFAULT '',
    bank_details TEXT DEFAULT '',
    terms TEXT DEFAULT '',
    next_invoice_number INTEGER NOT NULL DEFAULT 1,
    monthly_target INTEGER NOT NULL DEFAULT 0,  -- paise; the sales goal for a month (0 = not set)
    logo TEXT NOT NULL DEFAULT '',              -- file name of the shop's logo in instance/uploads/
    email TEXT NOT NULL DEFAULT '',
    default_source TEXT NOT NULL DEFAULT '',    -- what a new bill's "Order came through" starts as
    default_method TEXT NOT NULL DEFAULT '',    -- what a new bill's payment method starts as
    gstin TEXT NOT NULL DEFAULT ''              -- optional, printed in the bill's header
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id INTEGER NOT NULL REFERENCES shops(id),
    name TEXT NOT NULL,
    login TEXT NOT NULL UNIQUE,        -- email or phone
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'owner'
);
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id INTEGER NOT NULL REFERENCES shops(id),
    code TEXT COLLATE NOCASE,          -- optional; unique within a shop
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    price INTEGER NOT NULL,            -- in paise (1 rupee = 100 paise)
    stock INTEGER NOT NULL DEFAULT 0,
    low_stock_level INTEGER NOT NULL DEFAULT 5,
    hsn TEXT NOT NULL DEFAULT '',      -- HSN or SAC number (optional)
    supplier TEXT NOT NULL DEFAULT '', -- who the item is bought from (optional)
    cost_price INTEGER NOT NULL DEFAULT 0,  -- paise; what it cost the shop (0 = not entered)
    gst_rate REAL,                     -- percent, like 18 (empty = not entered)
    active INTEGER NOT NULL DEFAULT 1, -- 0 = removed (hidden, kept for old bills)
    UNIQUE (shop_id, code)
);
CREATE TABLE IF NOT EXISTS bills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id INTEGER NOT NULL REFERENCES shops(id),
    invoice_number INTEGER NOT NULL,   -- counts up by one per shop
    created_at TEXT NOT NULL,
    customer_name TEXT NOT NULL DEFAULT '',
    customer_phone TEXT NOT NULL DEFAULT '',
    customer_location TEXT NOT NULL DEFAULT '',
    customer_other_phone TEXT NOT NULL DEFAULT '',
    due_amount INTEGER NOT NULL DEFAULT 0,  -- paise still to be paid (0 = paid in full)
    due_date TEXT NOT NULL DEFAULT '',      -- old bills only: when the rest was expected
    customer_type TEXT NOT NULL DEFAULT 'Retail',  -- Retail or B2B
    round_off INTEGER NOT NULL DEFAULT 0,   -- paise added or taken off to reach a whole rupee
    customer_id INTEGER NOT NULL DEFAULT 0, -- the saved customer (0 = none)
    fy INTEGER NOT NULL DEFAULT 0,          -- financial year (April to March) as two digits: 26
    bill_seq INTEGER NOT NULL DEFAULT 0,    -- counts up from 1 within that financial year
    bill_label TEXT NOT NULL DEFAULT '',    -- what the owner sees: '26/1'
    place_of_sale TEXT NOT NULL DEFAULT '',
    order_source TEXT NOT NULL DEFAULT '',  -- Store (walk-in), Stall, Website or Other: ...
    whole_discount_pct REAL NOT NULL DEFAULT 0,
    shipping INTEGER NOT NULL DEFAULT 0,  -- paise
    total INTEGER NOT NULL,               -- paise
    status TEXT NOT NULL DEFAULT 'Saved', -- Saved (final), Draft or Cancelled
    draft_created_at TEXT NOT NULL DEFAULT '', -- drafts: when the draft was first saved; kept when finalised
    replaced_by INTEGER REFERENCES bills(id),
    replaces INTEGER REFERENCES bills(id),
    offer_ids TEXT NOT NULL DEFAULT '',      -- offers picked on the bill, like '1,3'
    offers_applied TEXT NOT NULL DEFAULT '', -- names of offers that changed a price (kept as text)
    UNIQUE (shop_id, invoice_number)
);
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,   -- a customer is this id, never the name
    shop_id INTEGER NOT NULL REFERENCES shops(id),
    name TEXT NOT NULL,
    phone TEXT NOT NULL DEFAULT '',         -- mobile, 10 digits, unique in a shop when not empty
    other_phone TEXT NOT NULL DEFAULT '',   -- landline or second number; never used for matching
    location TEXT NOT NULL DEFAULT '',
    customer_type TEXT NOT NULL DEFAULT 'Retail',
    legacy INTEGER NOT NULL DEFAULT 0       -- 1 = a customer with no phone from before the upgrade
);
CREATE TABLE IF NOT EXISTS undo_actions (  -- "Combined. Undo": kept for a short while
    token TEXT PRIMARY KEY,
    shop_id INTEGER NOT NULL REFERENCES shops(id),
    created REAL NOT NULL,                 -- seconds since 1970; Undo works for 30 seconds
    payload TEXT NOT NULL,                 -- what to put back, as JSON
    used INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS order_sources (   -- the shop's "Order came through" choices
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id INTEGER NOT NULL REFERENCES shops(id),
    name TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS payment_methods (  -- the shop's payment method choices
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id INTEGER NOT NULL REFERENCES shops(id),
    name TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS product_categories (  -- the shop's own product categories
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id INTEGER NOT NULL REFERENCES shops(id),
    name TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS suppliers (            -- the shop's own suppliers
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id INTEGER NOT NULL REFERENCES shops(id),
    name TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id INTEGER NOT NULL REFERENCES shops(id),
    name TEXT NOT NULL,
    percentage REAL NOT NULL,
    applies_to TEXT NOT NULL,               -- 'category' or 'bill'
    category TEXT NOT NULL DEFAULT '',
    min_amount INTEGER NOT NULL DEFAULT 0,  -- paise; the bill must reach this (whole-bill offers)
    exclude_category TEXT NOT NULL DEFAULT '', -- whole-bill offers: items in this category get no discount
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS shop_qr_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id INTEGER NOT NULL REFERENCES shops(id),
    label TEXT NOT NULL,
    filename TEXT NOT NULL,                 -- file inside instance/uploads/
    position INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS bill_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id INTEGER NOT NULL REFERENCES bills(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    code TEXT,                         -- copied at the time of sale
    name TEXT NOT NULL,                -- copied at the time of sale
    quantity INTEGER NOT NULL,
    rate INTEGER NOT NULL,             -- paise, copied at the time of sale
    line_discount_pct REAL NOT NULL DEFAULT 0,
    line_amount INTEGER NOT NULL,      -- paise, after the line discount
    cost INTEGER NOT NULL DEFAULT 0,   -- paise per item, the product's cost price at the time of sale
    gst_rate REAL NOT NULL DEFAULT 0   -- percent, the product's GST % at the time of sale (0 = none saved)
);
CREATE TABLE IF NOT EXISTS payments (  -- a bill has one or more; together they equal its total
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id INTEGER NOT NULL REFERENCES bills(id),
    mode TEXT NOT NULL,                -- UPI, Cash, Net-banking or Other: ...
    amount INTEGER NOT NULL,           -- paise
    paid_at TEXT NOT NULL DEFAULT ''   -- set only when a due amount was received later
);
"""


def get_db():
    """One connection per request, closed automatically afterwards."""
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def backup_database(db, label):
    """Copy the whole database to a dated file beside it, before a risky change.

    Returns the file's path, or None for a database with no bills yet (nothing to lose).
    """
    if db.execute("SELECT 1 FROM bills LIMIT 1").fetchone() is None:
        return None
    import os
    from datetime import datetime
    path = db.execute("PRAGMA database_list").fetchone()["file"]
    if not path:
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = os.path.join(os.path.dirname(path), f"quantro-backup-{label}-{stamp}.db")
    db.commit()
    copy = sqlite3.connect(target)
    try:
        db.backup(copy)
    finally:
        copy.close()
    return target


def migrate_customers(db):
    """Upgrade customers from "found by name" to "found by id" without losing anything.

    Runs once, on a database whose customers table still has the old phone_key column:
    * a dated backup of the database is made first;
    * every customer keeps its id, so every bill stays linked to the same customer;
    * phones are tidied to 10-digit mobile numbers; two customers that turn out to have the
      same number are joined (their bills moved to the older one);
    * a customer with no usable mobile number is kept, marked "No phone, older bill", and
      anything that was in the phone box (a landline, say) is kept as Other phone;
    * what each bill printed is never touched.
    Everything happens in one transaction: if anything fails, nothing changes.
    """
    from .services.customers import normalize_phone
    if "phone_key" not in [r["name"] for r in db.execute("PRAGMA table_info(customers)")]:
        return
    backup = backup_database(db, "before-customer-upgrade")
    old = db.execute("SELECT * FROM customers ORDER BY id").fetchall()
    keep, joined, owner = [], 0, {}
    for c in old:
        typed = (c["phone"] or "").strip()
        digits, error = normalize_phone(typed or c["phone_key"])
        other = "" if digits or not typed else typed
        row = {"id": c["id"], "shop_id": c["shop_id"], "name": c["name"], "phone": digits,
               "other": other, "location": c["location"], "type": c["customer_type"],
               "legacy": 0 if digits else 1, "merged_into": None}
        if digits and (c["shop_id"], digits) in owner:
            row["merged_into"] = owner[(c["shop_id"], digits)]
            joined += 1
        elif digits:
            owner[(c["shop_id"], digits)] = c["id"]
        keep.append(row)
    try:
        db.execute("BEGIN")
        db.execute("""CREATE TABLE customers_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_id INTEGER NOT NULL REFERENCES shops(id),
            name TEXT NOT NULL,
            phone TEXT NOT NULL DEFAULT '',
            other_phone TEXT NOT NULL DEFAULT '',
            location TEXT NOT NULL DEFAULT '',
            customer_type TEXT NOT NULL DEFAULT 'Retail',
            legacy INTEGER NOT NULL DEFAULT 0)""")
        by_id = {r["id"]: r for r in keep}
        for r in keep:
            if r["merged_into"] is None:
                continue
            target = by_id[r["merged_into"]]
            if not target["location"] and r["location"]:
                target["location"] = r["location"]
            db.execute("UPDATE bills SET customer_id = ? WHERE customer_id = ?",
                       (target["id"], r["id"]))
        for r in keep:
            if r["merged_into"] is None:
                db.execute("INSERT INTO customers_new (id, shop_id, name, phone, other_phone, "
                           "location, customer_type, legacy) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (r["id"], r["shop_id"], r["name"], r["phone"], r["other"],
                            r["location"], r["type"], r["legacy"]))
        db.execute("DROP TABLE customers")
        db.execute("ALTER TABLE customers_new RENAME TO customers")
        db.execute("UPDATE bills SET customer_id = 0 WHERE customer_id != 0 AND customer_id "
                   "NOT IN (SELECT id FROM customers)")
        db.commit()
    except Exception:
        db.rollback()
        raise
    print(f"Customer upgrade done: {len(keep) - joined} customers kept, {joined} joined "
          f"(same mobile number), {sum(1 for r in keep if r['legacy'] and r['merged_into'] is None)} "
          f"without a mobile number marked 'No phone, older bill'."
          + (f" Backup: {backup}" if backup else ""))


def init_db():
    db = get_db()
    has_bills = db.execute("SELECT 1 FROM sqlite_master WHERE name = 'bills'").fetchone()
    if has_bills and "draft_created_at" not in [r["name"] for r in db.execute("PRAGMA table_info(bills)")]:
        backup_database(db, "before-drafts")       # once: the column added below makes this false
    had_lists = db.execute("SELECT 1 FROM sqlite_master WHERE name = 'payment_methods'").fetchone()
    had_catalog = db.execute("SELECT 1 FROM sqlite_master WHERE name = 'suppliers'").fetchone()
    db.executescript(SCHEMA)
    if not had_catalog:
        # Shops that already have products keep the categories and suppliers they typed,
        # now as a list they can manage in Shop Details.
        for shop in db.execute("SELECT id FROM shops").fetchall():
            for table, column in (("product_categories", "category"), ("suppliers", "supplier")):
                try:
                    found = [r[0] for r in db.execute(
                        f"SELECT DISTINCT {column} FROM products WHERE shop_id = ? AND {column} != '' "
                        f"ORDER BY {column} COLLATE NOCASE", (shop["id"],))]
                except sqlite3.OperationalError:     # a very old products table with no supplier yet
                    found = []
                for position, name in enumerate(found):
                    db.execute(f"INSERT INTO {table} (shop_id, name, position) VALUES (?, ?, ?)",
                               (shop["id"], name, position))
    if not had_lists:
        # Shops that already exist keep exactly what they had: the old fixed choices, plus
        # anything their bills used, so no old bill is left without its choice.
        for shop in db.execute("SELECT id FROM shops").fetchall():
            for table, old_defaults, query in (
                    ("order_sources", ["Store (walk-in)", "Stall", "Website"],
                     "SELECT DISTINCT order_source FROM bills WHERE shop_id = ?"),
                    ("payment_methods", ["UPI", "Cash", "Net-banking"],
                     "SELECT DISTINCT p.mode FROM payments p JOIN bills b ON b.id = p.bill_id "
                     "WHERE b.shop_id = ?")):
                used = sorted(r[0] for r in db.execute(query, (shop["id"],))
                              if r[0] and not r[0].startswith("Other") and r[0] not in old_defaults)
                for position, name in enumerate(old_defaults + used):
                    db.execute(f"INSERT INTO {table} (shop_id, name, position) VALUES (?, ?, ?)",
                               (shop["id"], name, position))
    # Databases made before a column existed get it added here.
    columns = [row["name"] for row in db.execute("PRAGMA table_info(bills)")]
    added = {"customer_phone": "TEXT", "order_source": "TEXT", "customer_location": "TEXT",
             "due_date": "TEXT", "due_amount": "INTEGER", "offer_ids": "TEXT",
             "offers_applied": "TEXT", "round_off": "INTEGER", "customer_type": "TEXT",
             "customer_id": "INTEGER", "fy": "INTEGER", "bill_seq": "INTEGER",
             "bill_label": "TEXT", "customer_other_phone": "TEXT", "draft_created_at": "TEXT"}
    for name, kind in added.items():
        if name not in columns:
            default = ("0" if kind == "INTEGER" else "'Retail'" if name == "customer_type"
                       else "''")
            db.execute(f"ALTER TABLE bills ADD COLUMN {name} {kind} NOT NULL DEFAULT {default}")
    if "bill_label" not in columns:
        # Bills made before: number them 26/1, 26/2 ... in the order they were made.
        from .services.billing import fiscal_year
        from datetime import datetime
        seen = {}
        for b in db.execute("SELECT id, shop_id, created_at FROM bills ORDER BY id").fetchall():
            fy = fiscal_year(datetime.strptime(b["created_at"][:10], "%Y-%m-%d").date())
            seen[(b["shop_id"], fy)] = seq = seen.get((b["shop_id"], fy), 0) + 1
            db.execute("UPDATE bills SET fy = ?, bill_seq = ?, bill_label = ? WHERE id = ?",
                       (fy, seq, f"{fy}/{seq}", b["id"]))
    migrate_customers(db)
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS customers_phone_unique "
               "ON customers (shop_id, phone) WHERE phone != ''")
    if "exclude_category" not in [row["name"] for row in db.execute("PRAGMA table_info(offers)")]:
        db.execute("ALTER TABLE offers ADD COLUMN exclude_category TEXT NOT NULL DEFAULT ''")
    shop_columns = [row["name"] for row in db.execute("PRAGMA table_info(shops)")]
    if "monthly_target" not in shop_columns:
        db.execute("ALTER TABLE shops ADD COLUMN monthly_target INTEGER NOT NULL DEFAULT 0")
    product_columns = [row["name"] for row in db.execute("PRAGMA table_info(products)")]
    if "vendor" in product_columns:                 # it was called vendor for a while
        db.execute("ALTER TABLE products RENAME COLUMN vendor TO supplier")
        product_columns = [row["name"] for row in db.execute("PRAGMA table_info(products)")]
    for name, definition in {"hsn": "TEXT NOT NULL DEFAULT ''", "supplier": "TEXT NOT NULL DEFAULT ''",
                             "cost_price": "INTEGER NOT NULL DEFAULT 0", "gst_rate": "REAL"}.items():
        if name not in product_columns:
            db.execute(f"ALTER TABLE products ADD COLUMN {name} {definition}")
    line_columns = [row["name"] for row in db.execute("PRAGMA table_info(bill_lines)")]
    if "gst_rate" not in line_columns:
        backup_database(db, "before-gst")           # once: the column added below makes this false
        db.execute("ALTER TABLE bill_lines ADD COLUMN gst_rate REAL NOT NULL DEFAULT 0")
    if "gstin" not in shop_columns:
        db.execute("ALTER TABLE shops ADD COLUMN gstin TEXT NOT NULL DEFAULT ''")
    if db.execute("SELECT 1 FROM products WHERE gst_rate IS NULL LIMIT 1").fetchone():
        db.execute("UPDATE products SET gst_rate = 0 WHERE gst_rate IS NULL")     # no GST % means 0
    if "cost" not in line_columns:
        db.execute("ALTER TABLE bill_lines ADD COLUMN cost INTEGER NOT NULL DEFAULT 0")
    for name in ("logo", "email", "default_source", "default_method"):
        if name not in shop_columns:
            db.execute(f"ALTER TABLE shops ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
    payment_columns = [row["name"] for row in db.execute("PRAGMA table_info(payments)")]
    if "paid_at" not in payment_columns:
        db.execute("ALTER TABLE payments ADD COLUMN paid_at TEXT NOT NULL DEFAULT ''")
    db.commit()


def init_app(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()

