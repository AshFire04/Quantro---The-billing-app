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
    monthly_target INTEGER NOT NULL DEFAULT 0   -- paise; the sales goal for a month (0 = not set)
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
    vendor TEXT NOT NULL DEFAULT '',   -- who the item is bought from (optional)
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
    status TEXT NOT NULL DEFAULT 'Saved', -- Saved or Cancelled
    replaced_by INTEGER REFERENCES bills(id),
    replaces INTEGER REFERENCES bills(id),
    offer_ids TEXT NOT NULL DEFAULT '',      -- offers picked on the bill, like '1,3'
    offers_applied TEXT NOT NULL DEFAULT '', -- names of offers that changed a price (kept as text)
    UNIQUE (shop_id, invoice_number)
);
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id INTEGER NOT NULL REFERENCES shops(id),
    name TEXT NOT NULL,                -- 'Asha', or 'Retail - Asha' when there is no phone number
    phone TEXT NOT NULL DEFAULT '',    -- as typed
    phone_key TEXT NOT NULL DEFAULT '',  -- digits only; how a customer is found again
    location TEXT NOT NULL DEFAULT '',
    customer_type TEXT NOT NULL DEFAULT 'Retail'
);
CREATE INDEX IF NOT EXISTS customers_phone ON customers (shop_id, phone_key);
CREATE TABLE IF NOT EXISTS offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id INTEGER NOT NULL REFERENCES shops(id),
    name TEXT NOT NULL,
    percentage REAL NOT NULL,
    applies_to TEXT NOT NULL,               -- 'category' or 'bill'
    category TEXT NOT NULL DEFAULT '',
    min_amount INTEGER NOT NULL DEFAULT 0,  -- paise; the bill must reach this (whole-bill offers)
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
    line_amount INTEGER NOT NULL       -- paise, after the line discount
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


def init_db():
    db = get_db()
    db.executescript(SCHEMA)
    # Databases made before a column existed get it added here.
    columns = [row["name"] for row in db.execute("PRAGMA table_info(bills)")]
    added = {"customer_phone": "TEXT", "order_source": "TEXT", "customer_location": "TEXT",
             "due_date": "TEXT", "due_amount": "INTEGER", "offer_ids": "TEXT",
             "offers_applied": "TEXT", "round_off": "INTEGER", "customer_type": "TEXT",
             "customer_id": "INTEGER", "fy": "INTEGER", "bill_seq": "INTEGER",
             "bill_label": "TEXT"}
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
    if "customer_id" not in columns:
        # Bills made before Customer Details existed: save their customers, oldest first.
        from .services.customers import save_customer
        for b in db.execute("SELECT id, shop_id, customer_name, customer_phone, "
                            "customer_location, customer_type FROM bills ORDER BY id").fetchall():
            cid = save_customer(db, b["shop_id"], b["customer_name"], b["customer_phone"],
                                b["customer_location"], b["customer_type"] or "Retail")
            db.execute("UPDATE bills SET customer_id = ? WHERE id = ?", (cid, b["id"]))
    # Customers without a phone number were once saved as 'Retail - Asha': use the plain name.
    for old in db.execute("SELECT id, shop_id, name FROM customers WHERE phone_key = '' AND "
                          "(name LIKE 'Retail - %' OR name LIKE 'B2B - %')").fetchall():
        plain = old["name"].split(" - ", 1)[1].strip()
        twin = db.execute("SELECT id FROM customers WHERE shop_id = ? AND phone_key = '' AND "
                          "lower(name) = lower(?) AND id != ? ORDER BY id",
                          (old["shop_id"], plain, old["id"])).fetchone()
        if twin is None:
            db.execute("UPDATE customers SET name = ? WHERE id = ?", (plain, old["id"]))
        else:                                          # the same person twice: join them up
            db.execute("UPDATE bills SET customer_id = ? WHERE customer_id = ?",
                       (twin["id"], old["id"]))
            db.execute("DELETE FROM customers WHERE id = ?", (old["id"],))
    shop_columns = [row["name"] for row in db.execute("PRAGMA table_info(shops)")]
    if "monthly_target" not in shop_columns:
        db.execute("ALTER TABLE shops ADD COLUMN monthly_target INTEGER NOT NULL DEFAULT 0")
    product_columns = [row["name"] for row in db.execute("PRAGMA table_info(products)")]
    for name, definition in {"hsn": "TEXT NOT NULL DEFAULT ''", "vendor": "TEXT NOT NULL DEFAULT ''",
                             "cost_price": "INTEGER NOT NULL DEFAULT 0", "gst_rate": "REAL"}.items():
        if name not in product_columns:
            db.execute(f"ALTER TABLE products ADD COLUMN {name} {definition}")
    payment_columns = [row["name"] for row in db.execute("PRAGMA table_info(payments)")]
    if "paid_at" not in payment_columns:
        db.execute("ALTER TABLE payments ADD COLUMN paid_at TEXT NOT NULL DEFAULT ''")
    db.commit()


def init_app(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()

