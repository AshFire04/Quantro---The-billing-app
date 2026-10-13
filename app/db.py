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
    get_db().executescript(SCHEMA)


def init_app(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()
