"""Creates a clearly labelled SAMPLE shop so you can try Quantro without typing in products.

    python seed.py

Sign in afterwards with:  sample@quantro.example  /  sample123
Everything here is made-up sample data. It is added to the same database the app uses
(instance/quantro.db). Running it twice does nothing the second time.
"""
import random
from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

from app import create_app
from app.db import get_db
from app.services.billing import save_bill
from app.services.choices import seed_defaults
from app.services.money import rupees_to_paise

LOGIN = "sample@quantro.example"
PASSWORD = "sample123"

# code, name, category, price (rupees), stock, low-stock level
PRODUCTS = [
    ("KA36", "Cotton bedsheet, double", "Bedsheets", 899, 24, 5),
    ("KA37", "Cotton bedsheet, single", "Bedsheets", 599, 3, 5),
    ("KA52", "Quilted bedcover", "Bedsheets", 1899, 9, 3),
    ("CU10", "Cushion cover, 16 inch", "Cushions", 199, 40, 10),
    ("CU12", "Velvet cushion, 18 inch", "Cushions", 349, 4, 6),
    ("CU20", "Floor cushion", "Cushions", 699, 12, 4),
    ("CR01", "Door curtain, 7 ft", "Curtains", 749, 15, 5),
    ("CR02", "Window curtain, 5 ft", "Curtains", 549, 0, 5),
    ("RG05", "Cotton rug, 3x5 ft", "Rugs", 1499, 7, 3),
    ("RG08", "Jute rug, round", "Rugs", 2299, 2, 3),
    ("TB04", "Table runner", "Table linen", 399, 18, 5),
    ("TB07", "Dining mat, set of 6", "Table linen", 649, 11, 4),
    ("TW02", "Bath towel", "Towels", 449, 30, 8),
    ("TW03", "Hand towel, pack of 3", "Towels", 299, 5, 6),
]

# Saved offers: name, percentage, applies to ('category' or 'bill'), category, minimum (rupees)
OFFERS = [
    ("Festive 10% off above Rs 2,500", 10, "bill", "", 2500),
    ("Cushion season sale", 15, "category", "Cushions", 0),
]

# Sample bills: days ago, customer, [(code, quantity)], extras for save_bill
BILLS = [
    (6, "Meena Stores", [("KA36", 3), ("TB04", 2)],
     {"order_source": "Walk-in", "customer_phone": "98450 11223"}),
    (5, "Anita Rao", [("CU10", 4)],
     {"order_source": "WhatsApp", "customer_phone": "98860 22334"}),
    (4, "", [("TW02", 2), ("TW03", 1)], {"order_source": "Walk-in"}),          # a walk-in: no name, no phone
    (3, "Ravi Kumar", [("RG05", 1), ("CR01", 2)],
     {"order_source": "Instagram", "payments": [{"mode": "UPI"}],
      "customer_phone": "97400 33445"}),
    (2, "Sunita Devi", [("KA52", 2), ("CU20", 2)],
     {"order_source": "WhatsApp", "payments": [{"mode": "Card"}],
      "customer_phone": "99000 44556"}),
    (1, "", [("TB07", 1)], {"order_source": "Walk-in"}),
    (0, "Priya Nair", [("KA37", 1), ("CU12", 1), ("CR01", 1)],
     {"order_source": "Walk-in", "whole_discount": "5"}),          # a name but no phone
    (0, "Meena Stores", [("TW02", 6), ("TB04", 4)],
     {"order_source": "Walk-in", "due_amount": "1200", "customer_type": "B2B",
      "customer_phone": "98450 11223"}),               # the same Meena Stores again
]


def main(app=None):
    app = app or create_app()
    with app.app_context():
        db = get_db()
        if db.execute("SELECT 1 FROM users WHERE login = ?", (LOGIN,)).fetchone():
            print("The sample shop already exists. Nothing changed.")
            return
        with db:
            shop_id = db.execute(
                "INSERT INTO shops (name, phone, bank_details, terms, monthly_target) "
                "VALUES (?, ?, ?, ?, ?)",
                ("Sample Home Furnishings (sample data)", "98765 43210",
                 "SAMPLE ONLY - A/c name: Sample Home Furnishings\nA/c no: 0000 0000 0000\nIFSC: SAMP0000001",
                 "Goods once sold will not be taken back. (sample terms)",
                 rupees_to_paise("25000"))).lastrowid
            seed_defaults(db, shop_id)
            db.execute("INSERT INTO users (shop_id, name, login, password_hash) VALUES (?, ?, ?, ?)",
                       (shop_id, "Sample Owner", LOGIN, generate_password_hash(PASSWORD)))
            for code, name, category, price, stock, low in PRODUCTS:
                db.execute("INSERT INTO products (shop_id, code, name, category, price, stock, "
                           "low_stock_level) VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (shop_id, code, name, category, rupees_to_paise(price), stock, low))
            for name, pct, applies_to, category, minimum in OFFERS:
                db.execute("INSERT INTO offers (shop_id, name, percentage, applies_to, category, "
                           "min_amount) VALUES (?, ?, ?, ?, ?, ?)",
                           (shop_id, name, pct, applies_to, category, rupees_to_paise(minimum)))

        ids = {r["code"]: r["id"] for r in db.execute(
            "SELECT id, code FROM products WHERE shop_id = ?", (shop_id,))}
        random.seed(7)                       # the same sample day-times every run
        for days_ago, customer, items, extras in BILLS:
            extras = dict(extras)
            extras.setdefault("payments", [{"mode": "Cash"}])
            when = (datetime.now() - timedelta(days=days_ago)).replace(
                hour=random.randint(10, 18), minute=random.randint(0, 59), second=0, microsecond=0)
            if days_ago == 0:
                when = min(when, datetime.now())
            # Dated on its own day, so its bill number belongs to the right financial year.
            bill_id = save_bill(db, shop_id,
                                [{"product_id": ids[c], "quantity": q} for c, q in items],
                                customer, order_date=when.strftime("%Y-%m-%d"), **extras)
            db.execute("UPDATE bills SET created_at = ? WHERE id = ?",
                       (when.isoformat(timespec="seconds"), bill_id))
            db.commit()
    print(f"Sample shop created. Sign in with {LOGIN} / {PASSWORD}")


if __name__ == "__main__":
    main()
