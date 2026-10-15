# Quantro

A simple website for a shop owner to **make a bill and have the stock update by itself**.
Built first for Sajja Home Furnishings, and kept shop-neutral so other shops can use it later.

Billing and inventory are one thing: when a bill is saved, the stock of every item on it goes down.
Editing or cancelling a bill puts the stock back correctly.

## What it does

- **Home**: today's sales, bills today, items running low, payments pending, sales this week,
  sales against a monthly target, inventory split by category, and recent bills.
- **Billing**: add items by code, name or card; item and whole-bill discounts, saved offers,
  shipping, part payments with a due date; save and the stock drops.
- **Inventory**: add, edit, remove, search, and filter by In stock / Low / Out.
- **Past bills**: search and filter, view, print, edit (replace) or cancel.
- **Shop Details**: shop and bank details, terms, QR codes for the printed bill, monthly target, offers.

## Try it

You need Python 3 (built and tested on 3.14). No accounts or API keys.

```
pip install -r requirements.txt
python seed.py
python -m flask --app app run --host 0.0.0.0
```

1. `python seed.py` is optional. It creates a clearly labelled **sample shop** with home-furnishing
   products and a few bills. Sign in with `sample@quantro.example` / `sample123`.
   Without it, open the site and choose **Create your shop** to start empty.
2. Open <http://localhost:5000>.
3. **On a phone** on the same Wi-Fi, open `http://<your-laptop-IP>:5000`
   (find the IP with `ipconfig` on Windows or `ifconfig` on Mac/Linux).
   If it does not load, allow Python through the laptop's firewall.

The data lives in one file, `instance/quantro.db`. Delete it to start again.

## Check that it works

```
pytest
```

## Notes

- Money is stored as whole paise, so rounding never drifts. Prices include GST; there is no separate tax line.
- This is a proof of concept for running on one laptop. The secret key in `app/__init__.py` is a
  placeholder: change it before putting the app on the internet.
- Not built yet: Shopify stock sync, recording purchases to raise stock, state-wise GST,
  best-seller and monthly reports, and several shops with separate sign-ups.
