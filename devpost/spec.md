---
doc: spec
status: approved
---

# Quantro — Technical Spec

## How This Works, In Plain Language
Quantro is a website that runs on your own laptop. You start it with one command, and then open it in a browser (on the laptop, or on a phone on the same Wi-Fi).

It has three pieces:
- **The pages** (HTML, CSS and a little JavaScript) are what you see and tap: sign in, Billing, Inventory, Past bills and Settings. The JavaScript only handles the live parts of the Billing screen: the total updating as she types, the "stock after saving" box, and the plus button turning off at the stock limit.
- **The server** is a Python program using **Flask**. It receives what you do in the browser ("save this bill"), applies the rules, and sends back the next page.
- **The database** is one **SQLite** file (`quantro.db`) on your laptop. It's like a spreadsheet the Python program reads and writes. It has separate sheets (tables) for shops, users, products, bills, bill lines and offers.

The key idea, from `scope.md > The Unique Kernel`: bills and stock live in the **same database**. When "Save bill" runs, the server saves the bill and lowers the stock in one all-or-nothing step. If any part fails, nothing is saved, so a bill can never exist without its stock change.

Why this shape: it's one language you already know (Python), one program and one file, and nothing to sign up for. Putting it online later is possible because the data is already kept per shop.

## The Core Journey Through the System
PRD ref: `prd.md > The Core Journey`.

1. **Sign in** — She enters her email or phone and password. The server finds her user, checks the password against the scrambled (hashed) copy, and remembers her in a signed browser cookie (a "session"). → `app/auth.py`
2. **Billing screen opens** — The server reads her shop's products and settings from the database and builds the page. → `app/routes/billing.py`, `templates/billing.html`
3. **Adding items** — Typing a code or a name searches the products already loaded in the page, so it's instant. Tapping an item adds a line. → `static/js/billing.js`
4. **Quantity and discounts** — Plus and minus change the line. Plus is disabled at the stock limit. Typing a per-item or whole-bill percentage, or picking a saved offer, changes the totals live. The "Stock after saving this bill" box is recalculated as she goes. → `static/js/billing.js`
5. **Save bill & update stock** — The browser sends the bill to the server. The server **recalculates the prices, discounts and totals itself** (it never trusts the browser's numbers), checks stock again, then in one database transaction: takes the next invoice number, saves the bill and its lines, and lowers each product's stock. → `app/routes/billing.py`, `app/services/billing.py`
6. **Confirmation and Past bills** — She is taken to the saved bill, which shows in Past bills and can be printed. → `templates/bill_view.html`
7. **Inventory** — The next time Inventory is opened, it reads the same database, so it shows the lower quantities and any Low or Out status. → `app/routes/inventory.py`
8. **Edit a saved bill** — Edit opens a copy in the Billing screen. Saving it runs one transaction: mark the old bill Cancelled and put its items back into stock, then create the new bill with a new number and take its items out. → `app/services/billing.py`

## Stack
- **Python 3** (already installed on your laptop; 3.14 detected) — the language you know.
- **Flask** (web framework) — https://flask.palletsprojects.com/ — small, readable, widely documented. *Accepted tradeoff:* the Billing screen needs some JavaScript, which is new for you; we'll write it in small, explained pieces.
- **SQLite** through Python's built-in `sqlite3` module — https://docs.python.org/3/library/sqlite3.html and https://www.sqlite.org/docs.html — one file, no database server to install.
- **Jinja templates** (come with Flask) — https://jinja.palletsprojects.com/ — HTML pages filled in by Python.
- **Werkzeug password hashing** (comes with Flask) — https://werkzeug.palletsprojects.com/en/stable/utils/#module-werkzeug.security — stores passwords scrambled.
- **Plain CSS and JavaScript**, no build step, no framework — keeps the theme colours in one file and avoids tooling setup.
- **pytest** — https://docs.pytest.org/ — to test the stock and billing maths.

Unverified, to check first in the build: the current Flask version and that it installs cleanly on Python 3.14 (`pip install flask`).

## Where It Runs and How Someone Tries It
- **Runs:** locally, as a Python process on the learner's laptop. Learner-agreed: local first, online later.
- **Needs:** Python 3 and the packages in `requirements.txt`. No API keys, no accounts.
- **Start (intended):**
  1. `pip install -r requirements.txt`
  2. `python seed.py` (optional: creates a clearly labelled sample shop with sample home-furnishing products)
  3. `flask --app app run --host 0.0.0.0`
  4. Open `http://localhost:5000`. On a phone on the same Wi-Fi, open `http://<laptop-IP>:5000`.
- **Demo recording:** screen-record the flow in `scope.md > What "Working" Looks Like`: open Inventory, make a bill, save it, return to Inventory and see the drop and the Low warning.
- **Submission:** a short demo video and a public GitHub repository. No deployment is planned. If chosen later, it needs a host with permanent storage for the database file, and that decision is left for `6-ship` or after.

## Look and Feel
Carried forward from `prd.md > Look and Feel`.
- **Palette:** the learner chose the palette in `Colour.jpeg` on 14 Oct 2026: #3368A0 (blue, buttons and top bar), #66A3BF (soft blue accent), #C8DFDB (light mint tint) and #F2EFE7 (cream background). All colours are CSS variables in one file (`static/css/theme.css`), so it can still be changed there.
- **Type:** a clean, friendly sans-serif for text and a monospace face for numbers (amounts, quantities, invoice numbers), as in the mock-ups. System fonts first, so it works offline.
- **Density:** spacious, with large tap targets (buttons at least about 44px high) for phone and for people with little technology experience.
- **Tone of copy:** short and plain ("Save bill & update stock", "No products yet").
- **Layout:** two columns on a laptop (items left, bill right); one column on a phone (items, then the bill). Reference mock-ups: `B · Billing first@2x.png`, `D · Inventory first@2x.png`, `C · Welcome and sign in@2x.png`. Mock-up A (dashboard) is the reference for the Home page, added late by the learner (a simple version, built near the end).
- **Print:** a separate print stylesheet formats the bill like her paper bill (header, item table, totals, bank details, terms, QR codes with labels).
- Mock-up data is groceries; sample data in the build will be home furnishings.

## Components

### Auth and "Create your shop"
Sign in, sign out, and "Create your shop" (shop name, owner name, email or phone, password). Creating a shop makes one `shop` and one `user` linked to it. Every page except sign-in and create-shop requires a signed-in user, and every database query is limited to that user's shop.
PRD ref: `prd.md > Screens and Layout`, `prd.md > States and Boundaries` ("One shop at a time").
Files: `app/auth.py`, `templates/login.html`, `templates/create_shop.html`.

### Inventory
List, search by name or code, filter (All, Low, Out), add, edit and remove products. Remove hides the product (it's marked inactive), so old bills still show the item they sold.
PRD ref: `prd.md > Features and Behavior > Products and stock (Inventory)`.
Files: `app/routes/inventory.py`, `templates/inventory.html`.

### Billing screen
Item search and cards, the live bill, discounts, the stock-after preview, and Save. Starts from the data the server puts in the page (products and offers as JSON).
PRD ref: `prd.md > Features and Behavior > Making a bill (Billing)`, `prd.md > Discounts and offers`.
Files: `app/routes/billing.py`, `templates/billing.html`, `static/js/billing.js`.

### Billing rules (server)
The one place the money and stock rules live: price a bill (line discounts, offers, whole-bill discount, shipping & handling), check stock, save, cancel and replace. Written as plain Python functions without Flask in them, so they can be tested directly.
PRD ref: `prd.md > Saving, editing and cancelling a bill`, `prd.md > Discounts and offers`.
Files: `app/services/billing.py`, `tests/test_billing.py`.

Rules, derived from the PRD:
- Money is kept as whole **paise** (integers), so rounding never drifts.
- Prices already include GST; there is no tax line. The place of sale is stored on the bill.
- Order of discounts: line discounts first (a manual per-item percentage, or an offer for a category), then the whole-bill discount (a manual percentage, or an offer with a minimum amount, judged on the bill after line discounts). Shipping & handling is added last. *This order is my assumption; see Open Issues.*
- A bill line keeps a **copy** of the item's code, name and price at the time of sale, so later price edits never change old bills.

### Home page (added late)
A signed-in landing page modelled on mock-up A. Every figure is read from the same database tables as the rest of the app (cancelled bills are left out of sales). Tiles: today's sales, bills today, items running low, payments pending (the sum of amounts still due on saved bills). Charts drawn with plain SVG/CSS (no chart library): sales over the last seven days, and a pie chart (what it splits, such as payment mode, is decided when the slice is built). A running-low list and the latest bills.
PRD ref: `prd.md > What We're Building`.
Files: `app/routes/home.py`, `templates/home.html`.
### Past bills
List with search by bill number or customer, newest first; view a bill; Edit (replace) and Cancelled status.
PRD ref: `prd.md > Past bills`, `prd.md > Saving, editing and cancelling a bill`.
Files: `app/routes/bills.py`, `templates/bills.html`, `templates/bill_view.html`.

### Print layout
The Print button calls the browser's print dialog, which also offers "Save as PDF". A print-only stylesheet lays out the bill using the shop's settings.
PRD ref: `prd.md > Printing and shop settings`.
Files: `templates/bill_view.html`, `static/css/print.css`.

### Settings and offers
Shop name, contact details, website, bank details, terms line, QR code images with labels, and the list of saved offers with an **Add offer** button (name, percentage, applies to a category or the whole bill, optional minimum amount, on/off). QR images are uploaded and stored in a local folder.
PRD ref: `prd.md > Printing and shop settings`, `prd.md > Discounts and offers`.
Files: `app/routes/settings.py`, `templates/settings.html`, `instance/uploads/`.

## Data Model
All data lives in the one SQLite file `instance/quantro.db`, and persists when the app is closed and reopened. Every table except `shops` has a `shop_id`, so each shop's data stays separate.

| Table | What it holds |
|---|---|
| `shops` | name, contact details, website, bank details, terms line, next invoice number |
| `users` | shop_id, name, email or phone, password hash, role (always "owner" for now) |
| `shop_qr_codes` | shop_id, label, image file name, display order |
| `products` | shop_id, code (optional, unique within the shop), name, category, price (paise), stock, low_stock_level, active |
| `bills` | shop_id, invoice number (unique within the shop), date, customer name, place of sale, whole-bill discount %, shipping & handling, total, status (Saved or Cancelled), replaced_by bill, replaces bill |
| `bill_lines` | bill_id, product_id, copied code and name, quantity, rate, line discount %, line amount |
| `offers` | shop_id, name, percentage, applies to (category or whole bill), category, minimum amount, active |

Where each thing is updated and what happens on return:
- **Stock** changes only when a bill is saved, cancelled or replaced, or when a product is edited by hand. It is read fresh from the database on every page.
- **A bill in progress** lives only in the browser page until saved. Closing the page loses an unsaved bill. (Acceptable for the proof of concept.)
- **Sign-in** lives in a signed cookie, so she stays signed in until she signs out or closes the browser.

## File Structure
```
Quantro - First of many/
├── app/
│   ├── __init__.py          # creates the Flask app, opens the database, registers the routes
│   ├── db.py                # database connection and the table definitions (schema)
│   ├── auth.py              # sign in, sign out, Create your shop, "login required"
│   ├── routes/
│   │   ├── inventory.py     # Inventory screen
│   │   ├── billing.py       # Billing screen and the Save request
│   │   ├── bills.py         # Past bills, view, edit/replace
│   │   └── settings.py      # shop settings, QR uploads, offers
│   └── services/
│       └── billing.py       # pricing, stock checks, save/cancel/replace (no Flask in here)
├── templates/               # HTML pages (Jinja)
│   ├── base.html            # shared top bar / menu
│   ├── login.html
│   ├── create_shop.html
│   ├── inventory.html
│   ├── billing.html
│   ├── bills.html
│   ├── bill_view.html       # on-screen and printable bill
│   └── settings.html
├── static/
│   ├── css/
│   │   ├── theme.css        # the colour variables (change the palette here)
│   │   ├── app.css          # layout and components
│   │   └── print.css        # printed bill layout
│   └── js/
│       └── billing.js       # live totals, stock-after preview, plus-button limit
├── instance/                # created at run time (not committed): quantro.db, uploads/
├── tests/
│   └── test_billing.py      # stock and money tests
├── seed.py                  # clearly labelled sample shop and products for the demo
├── requirements.txt
├── .gitignore
├── README.md                # how to run it
└── devpost/                 # Devpost learning workspace
```

## External Services and Dependencies
None outside the codebase. No network calls, no API keys, no cost. Python packages only (Flask and its bundled Jinja and Werkzeug, plus pytest for tests). Docs are linked under **Stack**.

Deferred integration: **Shopify stock sync** (`prd.md > Deferred From the POC`). When we get there, the Shopify Admin API docs are at https://shopify.dev/docs/api/admin. Not researched yet; it must be proven safe before it touches her live store.

## Important Failure Modes
- **Two screens, or a stale page, try to sell the last item** → the server re-checks stock when saving. If it isn't enough, nothing is saved and she sees "Only N left of <item>; please change the quantity".
- **Anything fails halfway through saving** → the single transaction undoes everything. She sees "Couldn't save the bill; nothing was changed", and stock is untouched.
- **A QR image is too big or the wrong kind** → upload is rejected with a plain message. The bill prints without it.
- **Wrong password** → "That email/phone or password isn't right", with no hint about which.
- **Laptop closed or app stopped** → the data is safe in the database file; restarting the app brings everything back.

## What Was Simplified and Why
- **A local SQLite file** instead of a hosted database — no accounts or infrastructure. The same table design moves to a hosted database later.
- **Run locally** instead of deploying — hosting is optional for the hackathon and brings storage and cost questions. It can come later.
- **Browser print and "Save as PDF"** instead of generating PDF files in code — same result, far less code.
- **One owner role per shop** instead of staff accounts with different access — the `users.role` column is there so staff access can be added later (`prd.md > Deferred From the POC`).
- **Plain CSS and JavaScript** instead of a front-end framework — no build step, easier to read line by line.
- **An unsaved bill is lost if the page closes** instead of saving drafts — drafts add rules the proof of concept doesn't need.
- **Sample data** in `seed.py` is clearly labelled as sample, and is not part of the real shop's data. The core stock update is real, not faked.

## Decisions and Open Issues

### Decisions the learner made or agreed to
- **Python** — the language they know. *Learner's choice.*
- **Flask + SQLite, server pages with a little JavaScript** — recommended; accepted. Tradeoff: the JavaScript on the Billing screen is new.
- **Run locally for the proof of concept, online later** — recommended; accepted. Tradeoff: others can't use it from their own phone yet.
- **"Create your shop" sign-up is in** — the learner's choice.
- **Multiple users per shop with different access** — the learner's later goal, deferred.

### Implementation details derived from those (not separately asked)
- Money in whole paise; discounts applied line first, then whole bill; invoice numbers per shop; bill lines keep a copy of the product details; unsaved bills live only in the page; low-stock level is a per-product setting; removing a product hides it, not deletes it.

### The learner's question
- **"I want to know how the code works for every part."** Clarified in this conversation by walking "Save bill" through browser, server and database. During the build, `5-build` learn mode explains each part before and after it's built, and the learning wrap-up/app map ties files to behaviors. Evidence to check: the learner can explain, in their own words, what happens between pressing Save and the stock changing.

### Still open
- **Dropping the tax rate** (prices already include GST) — carried from `prd.md > Open Questions`. Confirm before building billing.
- **Shipping & handling line** — on her paper bill but not discussed; the spec keeps it as an optional amount. Confirm or cut.
- **Discount order** — line discounts first, then the whole-bill discount, with the offer minimum judged after line discounts. Confirm that this matches how she calculates by hand (an example bill would settle it).
- **Final colour theme and logo** — can wait for the build (`prd.md > Open Questions`).
- **Flask on Python 3.14** — check at the start of the build.



