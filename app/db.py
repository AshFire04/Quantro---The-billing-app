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
    next_invoice_number INTEGER NOT NULL DEFAULT 1
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
    due_date TEXT NOT NULL DEFAULT '',      -- when the rest is expected (YYYY-MM-DD)
    place_of_sale TEXT NOT NULL DEFAULT '',
    order_source TEXT NOT NULL DEFAULT '',  -- Store (walk-in), Stall, Website or Other: ...
    whole_discount_pct REAL NOT NULL DEFAULT 0,
    shipping INTEGER NOT NULL DEFAULT 0,  -- paise
    total INTEGER NOT NULL,               -- paise
    status TEXT NOT NULL DEFAULT 'Saved', -- Saved or Cancelled
    replaced_by INTEGER REFERENCES bills(id),
    replaces INTEGER REFERENCES bills(id),
    UNIQUE (shop_id, invoice_number)
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
             "due_date": "TEXT", "due_amount": "INTEGER"}
    for name, kind in added.items():
        if name not in columns:
            default = "0" if kind == "INTEGER" else "''"
            db.execute(f"ALTER TABLE bills ADD COLUMN {name} {kind} NOT NULL DEFAULT {default}")
    payment_columns = [row["name"] for row in db.execute("PRAGMA table_info(payments)")]
    if "paid_at" not in payment_columns:
        db.execute("ALTER TABLE payments ADD COLUMN paid_at TEXT NOT NULL DEFAULT ''")
    db.commit()


def init_app(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()

