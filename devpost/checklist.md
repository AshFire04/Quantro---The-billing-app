---
doc: checklist
status: approved
---

# Build Checklist

Build mode: fast

## Slices

- [x] **1. You can create your shop, sign in and see the app**
  Becomes usable: A running website where you create a shop, sign in, see the top menu (Billing, Inventory, Past bills, Settings), and sign out. Wrong passwords are refused.
  Why now: Bootstrapping (Flask on Python 3.14, the database file, the theme) lives here, and it is the riskiest unknown. Every later slice is scoped to a signed-in shop.
  PRD ref: `prd.md > Screens and Layout` (Sign in), `prd.md > States and Boundaries` (Wrong sign-in, One shop at a time)
  Spec ref: `spec.md > Components > Auth and "Create your shop"`, `spec.md > File Structure`, `spec.md > Stack`, `spec.md > Data Model`
  Build: Scaffold per the file structure, `requirements.txt`, database schema, `theme.css`/`app.css`, base template with menu, create-shop, sign-in, sign-out, login-required.
  Verify (mechanical): `pip install -r requirements.txt` works; app starts with no errors; create a shop, sign out, sign in with right and wrong passwords, and check that a page needing sign-in redirects when signed out.
  Learner check: Open http://localhost:5000, create your shop, sign out, sign in again, and try a wrong password.
  Commit: `Add shop creation, sign in and app shell`

- [x] **2. You can manage your products in Inventory**
  Becomes usable: Add, edit, remove, search and filter products, with In stock, Low and Out status.
  Why now: Stock must exist before a bill can lower it, and it is the first half of the kernel.
  PRD ref: `prd.md > Features and Behavior > Products and stock (Inventory)`, `prd.md > States and Boundaries` (First use)
  Spec ref: `spec.md > Components > Inventory`, `spec.md > Data Model`
  Build: Inventory route and template, product form, search and All/Low/Out filter, remove as hide, "No products yet" state.
  Verify (mechanical): Run through add, edit, remove, search and each filter against the running app; check that a second shop cannot see the first shop's products.
  Learner check: Add a few home-furnishing products (one with a code like KA36, one without, one at or under its low level) and check the statuses and filters.
  Commit: `Add Inventory screen`

- [x] **3. You can make a bill and the stock drops (the kernel)**
  Becomes usable: On Billing, add items by code, name or card, change quantity (plus stops at stock), see the total and "Stock after saving", press Save, and see Inventory show the lower stock.
  Why now: This is the Unique Kernel, so it goes right after products exist. The server-side money and stock rules are tested here before anything is layered on.
  PRD ref: `prd.md > The Core Journey` (steps 2-8, 10), `prd.md > Features and Behavior > Making a bill (Billing)`
  Spec ref: `spec.md > Components > Billing screen`, `spec.md > Components > Billing rules (server)`, `spec.md > Important Failure Modes`
  Build: `app/services/billing.py` (price, check stock, save bill and lower stock in one transaction, invoice numbers, paise), `tests/test_billing.py`, Billing route/template/`billing.js`, the bill confirmation page. No discounts yet. Open issue to confirm first: tax dropped and prices include GST.
  Verify (mechanical): `pytest` passes (including a failed save changing nothing, and overselling being refused); in the running app save a bill and confirm Inventory stock dropped.
  Learner check: Open Inventory and note a product's stock, make a bill with it, save, and go back to Inventory to see the drop and any Low warning.
  Commit: `Add billing that updates stock on save`

- [x] **4. You can find old bills in Past bills**
  Becomes usable: A newest-first list of bills with search by number or customer, and a full view of each bill.
  Why now: It completes the "previous bill can be found again" part of the demo flow.
  PRD ref: `prd.md > Past bills`
  Spec ref: `spec.md > Components > Past bills`
  Build: `bills.py` routes, `bills.html`, `bill_view.html` (on-screen), "No bills yet" state.
  Verify (mechanical): Save two bills, check order, search by number and by customer, and open each.
  Learner check: Make two bills for different customers and find each by searching.
  Commit: `Add Past bills`

- [x] **5. You can give discounts and shipping**
  Becomes usable: Per-item % and whole-bill % discounts, shipping & handling, original vs discounted amount shown, totals and stock preview updating live.
  Why now: Layers on a bill that already saves correctly. The server recalculates everything.
  PRD ref: `prd.md > Discounts and offers` (manual), `prd.md > Features and Behavior > Making a bill` (shipping)
  Spec ref: `spec.md > Components > Billing rules (server)` (discount order)
  Build: Extend the pricing function and tests; add the discount and shipping inputs and live totals in `billing.js`. Open issues to confirm first: shipping & handling, and the discount order (an example bill from her would settle it).
  Verify (mechanical): `pytest` for discount maths (line, whole bill, both, rounding); compare browser total with the saved bill total.
  Learner check: Make a bill with a 10% item discount and a 5% whole-bill discount, and check the total against a hand calculation.
  Commit: `Add discounts and shipping to bills`

- [x] **6. You can edit a saved bill (replace, cancel, return)**
  Becomes usable: Edit opens a copy; saving makes a new numbered bill, marks the old one Cancelled with a link, and restores then removes stock correctly.
  Why now: It is the riskiest stock logic after the kernel, so test it before printing and polish.
  PRD ref: `prd.md > Features and Behavior > Saving, editing and cancelling a bill`
  Spec ref: `spec.md > Core Journey` (step 8), `spec.md > Components > Past bills`
  Build: Replace function in the billing service (one transaction), Edit flow reusing the Billing screen, Cancelled status and note.
  Verify (mechanical): `pytest` that stock ends correct after replacing, that a failure changes nothing, and that cancelled bills are never deleted.
  Learner check: Edit a bill to change a quantity, then check that Past bills and Inventory both look right.
  Commit: `Add edit and cancel for saved bills`

- [x] **7. You can set up your shop details and saved offers**
  Becomes usable: Settings for shop details, bank details, terms and QR images; Add offer (category or whole bill, optional minimum); picking an offer on a bill.
  Why now: The print layout needs the settings, and offers extend the discount rules.
  PRD ref: `prd.md > Printing and shop settings`, `prd.md > Discounts and offers` (saved offers)
  Spec ref: `spec.md > Components > Settings and offers`
  Build: `settings.py`, `settings.html`, QR upload with size and type checks, offers table, offer picker and pricing in the billing service.
  Verify (mechanical): `pytest` for offer maths; upload a good and a bad image; turn an offer on and off.
  Learner check: Enter Sajja's details, add "10% off above ₹2,500", and apply it to a bill.
  Commit: `Add shop settings and saved offers`

- [x] **8. You can print a bill that looks like her paper bill**
  Becomes usable: Print button gives a bill with the shop header, item table, totals, bank details, terms and labelled QR codes.
  Why now: It needs saved bills, discounts and settings to exist first.
  PRD ref: `prd.md > Printing and shop settings`
  Spec ref: `spec.md > Components > Print layout`, `spec.md > Look and Feel` (Print)
  Build: `print.css` and the print-ready `bill_view.html`.
  Verify (mechanical): Open the print preview or save as PDF and check that every section is present and the menu is hidden.
  Learner check: Print a bill to PDF and compare it with `Billing book.jpeg`.
  Commit: `Add printable bill layout`

- [x] **9. You can see how the shop is doing on a Home page**
  Becomes usable: A Home page, modelled on `A · Dashboard home@2x.png`: greeting, tiles (today's sales, bills today, items running low, payments pending), a sales-this-week chart, a pie chart, a running-low list and recent bills.
  Why now: It only reads data the earlier slices already save, so it comes after everything it summarises (bills, payments, dues, stock) is settled.
  PRD ref: `prd.md > What We're Building` (Home page), `prd.md > Deferred From the POC`
  Spec ref: `spec.md > Components > Home page (added late)`, `spec.md > Look and Feel`
  Build: `app/routes/home.py`, `templates/home.html`, plain SVG/CSS charts, Home as the first menu item and the page opened after sign-in. Open question to settle first: what the pie chart splits (for example payment mode or order source).
  Verify (mechanical): `pytest` that each tile and chart figure matches bills made in the test (cancelled bills excluded, shops kept separate); look at the page with no data and with some.
  Learner check: Make a few bills, one with a due amount, and check that every tile and chart matches what you expect.
  Commit: `Add Home page`

- [x] **10. It works on a phone, with sample data and a README**
  Becomes usable: One-column phone layout with large tap targets (including Home), `seed.py` for a labelled sample home-furnishings shop, and a README with the start steps.
  Why now: Final polish needed for the demo and for others to try it.
  PRD ref: `prd.md > Look and Feel`, `prd.md > Screens and Layout`
  Spec ref: `spec.md > Look and Feel`, `spec.md > Where It Runs and How Someone Tries It`
  Build: Responsive CSS, `seed.py`, `README.md`.
  Verify (mechanical): Follow the README from a fresh clone-like state (install, seed, run); check layout at a narrow width.
  Learner check: Open the app on your phone over the same Wi-Fi and make a bill.
  Commit: `Add phone layout, sample data and README`

## Hands-on Checkpoints

- [x] Early usable behavior explored — after slice 3 (the kernel: make a bill and see stock drop)
- [ ] Final kick-the-tires exploration and feedback completed

## Final Review

- [ ] Final review complete — feedback resolved and learner confirms ready to ship

## Code Tour and App Map

- [ ] Learning activity complete — guided route, focused alternative, prior practice connected, or brief recap
- [ ] Optional edit and transfer reflection addressed — offered/declined/already covered/not applicable as appropriate
- [ ] `devpost/app-map.html` generated from finished code, checked, and shown, including a project-grounded practice to reuse

Activity and evidence: [not started]
Route and stops: [not started]
Edit outcome: [not started]
Reflection: [not started]
Activity mode: [not started]

## Revisions

- Open issues settled by the learner — tax line dropped (prices include GST); shipping & handling kept as an optional amount because it varies by location and mode of transport; discount order confirmed as item discount first, then whole-bill discount.
- Slice 3 additions requested by the learner: customer name required and an optional phone number; an "Order came through" dropdown (Store (walk-in), Stall, Website, Other typed); a payment mode dropdown (UPI, Cash, Net-banking, Other typed) with a Split button for several payments (mode and amount each) that must add up to the bill total, stored in a new payments table.
- Slice 3: the "Stock after saving this bill" preview box was removed at the learner's request; Inventory shows the new stock after saving.
- Slice 4 additions requested by the learner: optional customer location on a bill; part payments with an amount due and a due date (the simple version of "pending payments", moved in from Deferred); a "Mark payment received" button on the bill page that records the received amount as a payment with the mode chosen; Past bills filters for order source, payment mode, has payment due and a date range (a status filter was added and then removed at the learner's request).
- Slice 5: discounts are per item and whole bill (item first, then whole bill, shipping added last and never discounted), percentages up to 2 decimal places, amounts rounded half up to the paisa, with the browser and server maths checked against each other. Dates now show as `10 Oct 2026` without the time (learner request).
- Slice 6 additions requested by the learner: a plain **Cancel bill** button (restores stock, marks the bill Cancelled, no replacement), since returning everything otherwise needed a replacement bill; a **Place of sale** column in Past bills.
- New slice 9 (Home page) added at the learner's request on 14 Oct 2026; the phone layout, sample data and README slice moved to 10. The Home page is modelled on mock-up A with a pie chart; the learner chose to place it near the end. This reverses the earlier decision to leave mock-up A out of the proof of concept; `prd.md`, `scope.md` and `spec.md` were updated to match.
- Slice 7: offers can be ticked on a bill; a discount typed by hand always beats an offer (even 0), the best matching offer wins, and a whole-bill offer is judged on the bill after item discounts. Bills store the names of offers applied as text so deleting an offer never changes an old bill. QR images are checked by their real file type, limited to 1 MB and 6 per shop, and served only to the shop that owns them.
- Learner-requested restyle (14 Oct 2026): the colour palette from `Colour.jpeg`; the Settings page renamed **Shop Details** (menu and page title); the Billing screen restyled to follow the learner's `Billing.html` mock-up (item list as rows with live stock left, a 3-column customer form, tinted offers box, summary grid), keeping every existing feature. Dark mode from the mock-up was not added.
- Slice 9 decisions (learner, 15 Oct 2026): the pie chart became two pies. **Sales against target** shows this month's sales against a monthly target the owner types in Shop Details (a new `monthly_target` on the shop; Home hides the pie and links to Shop Details until one is set). **Inventory by category** splits stock by product category; the build chose stock value (price x stock) as the measure, with products that have no category grouped as "No category" and more than five categories grouped as "Other categories". Home is the first menu item and the page opened after sign in. "Items running low" counts Low and Out of stock together.
- Slice 10: the README start command is `python -m flask --app app run --host 0.0.0.0` instead of `flask --app app run ...`, because the `flask` command is not always on the PATH (it was not in the Git Bash shell used to test). The phone layout was checked only through the page CSS and the pages loading, not on a real phone; that is for the final kick-the-tires check.
- Learner request (15 Oct 2026): skip the phone check for now. Home, Inventory, Past bills and Shop Details now fill 90% of the screen width with space at the sides (the Billing screen and the bill page keep their own widths).
- Learner request (15 Oct 2026): the wide pages were reduced from 90% to 80% of the screen width.
- Final-review feedback round 1 (learner, 16 Oct 2026): the bill total is rounded off to the nearest rupee (half up) with a **Round off** line shown on the Billing screen and the bill page; the place of sale became a **State** dropdown of every Indian state and union territory plus **Other** (Karnataka by default); the due-date calendar was removed from **Payment due** (only the amount is asked; old bills keep any date they had); a **Customer type** choice of **Retail** (default) or **B2B** was added next to **Order came through** (the build used round radio buttons so only one can be picked); and an **Order placed on** date (today by default, never in the future) sits before **Clear** so a bill forgotten at the end of the day can be dated correctly. Two columns (`customer_type`, `round_off`) were added to `bills`, and existing databases are upgraded automatically.
- Final-review feedback round 2 (learner, 16 Oct 2026): a new **Customer Details** tab keeps a list of every customer (name, phone, location, type, number of bills, total billed, last bill), with search and a link from the bill count to that customer's Past bills. Customers are saved automatically when a bill is saved. On Billing, **Phone number** now comes before **Customer Name**; typing a phone number fills in the saved customer's name, location and type, and a customer is found by phone number only, never by name. With no phone number the customer is saved as **Retail - Name** (the build used **B2B - Name** for a B2B customer, since "Retail" would be wrong). Blank details never wipe out saved ones. A new `customers` table and a `customer_id` on bills were added, and bills made earlier were turned into customers automatically. This adds a feature beyond the original scope, requested by the learner; editing or deleting a customer by hand was not built.
- Final-review feedback round 3 (learner, 16 Oct 2026): in Past bills the old **Due** column (amount and date) was replaced by four columns after **Status**: **UPI**, **Cash**, **Net-banking** and **Due**. Every bill shows an amount in each, with ₹0.00 where nothing was paid that way or nothing is due; a cancelled bill shows ₹0.00 due. Payments made with "Other" modes are not given a column of their own (they still show on the bill page).
- Final-review feedback round 4 (learner, 16 Oct 2026): (1) bill numbers now look like **26/1**, **26/2**: the first part is the financial year (April to March, so April 2026 to March 2027 is 26) and the number starts again at 1 each April. The year follows the **Order placed on** date, so a bill dated in March goes into the earlier year. Old bills were renumbered 26/1, 26/2 in the order they were made; an internal number is kept underneath. Past bills search accepts 26/1 or just 1. (2) Past bills shows **-** instead of ₹0.00 in the UPI, Cash, Net-banking and Due columns. (3) On Billing the bill panel now takes 70% of the width and the item list 30%. (4) Add/Edit product has two columns, with HSN/SAC number, Vendor name, Cost price and GST rate on the right; the build made all four optional so existing products still save. (5) This reverses part of round 2: customers without a phone number are saved under their plain name, with no "Retail - " or "B2B - " in front; the ones already saved were renamed.
- Final-review feedback round 5 (learner, 16 Oct 2026): (1) **Vendor** was renamed **Supplier** everywhere (the database column was renamed too). A new **Profit Statement** tab (the learner wrote "stating profit"; the build chose this name) lists every product with its supplier, cost price, selling price, profit per item, quantity sold, sales, cost, profit and margin, plus totals, with a From/To date filter. Profit is the amount an item sold for after the item discount and its share of any whole-bill discount, minus its cost; shipping, the rupee round-off and cancelled bills are left out. Each bill item now keeps the product's cost price from the time of sale (older bills use the product's cost price today). Items with no cost price anywhere are listed and counted apart instead of guessed. (2) On Home, the **Sales against target** card has a **Target | Profit** switch (the Profit view splits this month's sales into cost and profit), and the inventory card has a **By category | By supplier** switch (stock value supplied by each supplier, using the same selling-price measure as the category pie, with "No supplier" for products without one). (3) Past bills has a **Download Excel** button that gives an `.xlsx` of the bills on screen (every bill when nothing is filtered), with a **Bills** sheet and an **Items** sheet; it adds the `openpyxl` library to `requirements.txt`.
- Final-review feedback round 6, part 1 (learner, 17 Oct 2026): the **Profit Statement** tab and page were renamed **Profit**; the Profit page got a **Download Excel** button (one sheet, a row per product and a totals row, following the From/To dates); on Home the first two tiles are now **Today's sales** (with "N bills today" underneath) and **October's sales** (the current month, with "N bills this month" underneath), replacing the separate Bills today tile. Two other requests in the same message, an "inactive code button" and "offer enabled always", were unclear and are waiting for the learner to explain them.
- Final-review feedback round 6, part 2 (learner, 17 Oct 2026): an **item code is now used for good**: removing a product keeps its code, so neither a new product nor an edit can take it again (codes already cleared by earlier removals cannot be recovered). **Saved offers are ticked automatically** on every new bill, and the owner unticks one to switch it off for that bill; pressing Clear ticks them all again, and editing a saved bill keeps the offers that were ticked on it.
- Final-review feedback round 7 (learner, 17 Oct 2026): (1) Customer Details has a **Sort by** choice: Name (A to Z), Total billed highest to lowest, or lowest to highest. (2) On a bill page the **Past bills** and **New bill** buttons were removed; **Edit** was renamed **Edit product** (the existing replace-and-cancel flow, unchanged); and a new **Edit customer** button opens a form for the customer's phone, name, location, state and type only. Saving changes the bill in place: same bill number, items, stock, payments and total, with no cancelled or replacement bill. It also updates the saved customer in Customer Details (a customer left with no bills, such as a mistyped name, is removed from the list). It works on cancelled bills too. Order source and order date are not part of Edit customer.
- Final-review feedback round 8 (learner, 17 Oct 2026): (1) **Shop Details** was rebuilt to match the learner's `Shop-Details.html` mock-up: a "Shop details" heading, a section menu (Shop profile, Monthly target, QR codes, Offers, Order source, Payment methods), a card for each section, an offers list with an on/off switch and a delete button, chip lists for sources and methods, and a live **Bill preview** on the right. Differences from the mock-up, all to keep working features: whole-bill offers keep their optional minimum amount (shown when "All items" is chosen); the Offers subtitle says offers are ticked automatically on every bill (the mock-up said "pick it on a bill"); and **Terms** now print one per line on the bill. (2) **Order came through** and **Payment method** are no longer fixed in the code: each shop keeps its own lists in Shop Details (add or remove), and Billing, the bill page, Past bills (filters and one column per payment method, plus an "Other" column when needed), and the Excel download all read them. "Other", with typed text, is always offered on a bill as well. A new shop starts with Walk-in, WhatsApp, Instagram, Phone call and Cash, UPI, Card, Bank transfer; shops that already existed kept their old choices (Store (walk-in), Stall, Website and UPI, Cash, Net-banking, plus anything their bills used). Removing a choice never changes old bills; they keep the name, and it still works as a filter. Two new tables, `order_sources` and `payment_methods`, were added.
- Final-review feedback round 9 (learner, 17 Oct 2026): a **shop logo**. Shop Details has a new **Logo** section (and menu entry) to add, replace or remove one PNG or JPG under 1 MB; the file type is checked by its real contents, stored under a random name, and served only to the shop that owns it. The logo shows in the Bill preview and at the top left of the printed bill. It was not added to the top menu bar. A `logo` column was added to `shops`.
