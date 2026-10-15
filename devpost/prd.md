---
doc: prd
status: approved
---

# Quantro — Product Requirements

Quantro is a simple website, usable on a laptop or a phone, where a shop owner makes a bill and the stock updates by itself. First real user: the learner's mom, who runs Sajja Home Furnishings. It is built shop-neutral so other shops can use it later.
Source: `scope.md > The Unique Kernel`, `The Core Loop`, `Who It's For`.

## The Core Journey
1. The owner opens Quantro and signs in.
2. She lands on the **Billing** screen, ready to make a bill.
3. She types a customer name, and the date is already filled in.
4. She adds items to the bill: by typing an item code (like KA36), by searching the item name, or by tapping an item card. Each added item appears as a line with quantity, rate and amount.
5. She changes quantities with plus and minus. The plus button is disabled once the bill's quantity equals the stock.
6. She applies discounts if any: a one-off percentage on a single item, a one-off percentage on the whole bill, or a saved offer.
7. The bill shows the original amount, the discount and the final total. A green box, **Stock after saving this bill**, previews the new stock (for example, Tray 9.5 x 9.5: 8 → 7).
8. She presses **Save bill & update stock**. The bill gets the next invoice number, the stock drops, and the bill appears in **Past bills**.
9. She can print the bill. It carries her shop header and footer (shop details and QR codes).
10. Later she opens **Inventory** and sees the lower quantities and any low-stock warnings.

Success is the moment in step 8 to step 10: one save changes both the sales record and the stock.

## Screens and Layout
Four screens, plus a settings area. Source: `scope.md > The POC Boundary`.

- **Sign in.** Email or phone, password, and a way to create a shop account.
- **Billing** (first screen after sign-in). Left: search box and item cards, with category filters. Right: the current bill with customer name, date, bill number, line items, discounts, totals, the stock-after preview, and the Print and Save buttons. On a phone the item list and the bill sit one above the other, not side by side.
- **Inventory.** A list of products with code, name, category, stock, price and a status (In stock, Low, Out). Search and filter. A side panel or form for adding and editing a product.
- **Past bills.** A list of saved bills with number, date, customer, amount and status (Saved or Cancelled). Opening a bill shows it in full, with Print and Edit.
- **Settings.** Shop name, contact details, bank details and "terms" line, QR codes (images, with a label like "Follow us"), and the list of saved offers with an **Add offer** button.

Navigation: a top bar or menu with Billing, Inventory, Past bills and Settings.

## Look and Feel
- Established: simple, friendly and uncluttered, readable by someone with little technology experience; works on laptop and mobile.
- Starting point only: the mock-ups' look (deep teal/green, off-white background, amber for "low", a monospace font for numbers, large rounded buttons). Mock-ups are in the project folder (A to D).
- **The colour theme is not decided.** The learner will choose the final palette later, so colours must be easy to change in one place.
- The mock-ups use grocery examples. Real sample data should be home furnishings (trays, bedsheets, cushion covers, table runners).

## Features and Behavior

### Products and stock (Inventory)
Source: `scope.md > The POC Boundary`.
- As the owner, I want to add, edit and remove products so that my stock list matches my shop.
  - [ ] A product has an optional item code, a name (sizes go in the name, for example "Tray 9.5 x 9.5 x 1.5"), a category, a price and a stock quantity.
  - [ ] Adding a product makes it show up in Inventory and on the Billing screen.
  - [ ] Editing changes what is shown; removing takes it off both screens.
  - [ ] Searching by name or code narrows the list.
- As the owner, I want to see what's running low so that I can reorder in time.
  - [ ] Each product has a low-stock level. At or below it, the product shows "Low"; at zero, "Out".
  - [ ] Filters show All, Low and Out.

### Making a bill (Billing)
Source: `scope.md > The Core Loop`.
- As the owner, I want to make a bill quickly so that the customer isn't waiting.
  - [ ] Typing a code (like KA36) adds that item to the bill; items without a code are found by name search.
  - [ ] Each line shows name, quantity, rate and amount.
  - [ ] The date is filled in automatically and the customer name can be typed (shown on the bill).
  - [ ] An optional "shipping & handling" amount can be added, as on her paper bill. (Assumption: see Open Questions.)
  - [ ] Each bill has a unique invoice number that increases by one.
  - [ ] Each bill records a **place of sale** (state or country), so state-wise GST can be done later.
  - [ ] Prices already include GST, so no separate tax line is added (see Product Decisions).
- As the owner, I want to stop myself from selling what I don't have.
  - [ ] The plus button is disabled when the bill's quantity equals the item's stock.
  - [ ] An item with zero stock cannot be added.

### Discounts and offers
- As the owner, I want flexible discounts so that I can match festival offers and demand.
  - [ ] I can enter a **percentage discount on one item** and a **percentage discount on the whole bill** by hand, and both can be on one bill.
  - [ ] For a discounted line the bill shows the **original amount, then the discounted amount**, for transparency.
  - [ ] An **Add offer** button lets me save an offer once (a name, a percentage, applies to a category or to the whole bill, and an optional minimum bill amount, for example "Diwali, 15% off bedsheets" or "10% off above ₹2,500").
  - [ ] On a bill I can pick a saved offer and it applies the discount; the offer can be turned off or deleted.
  - [ ] The bill total and the stock-after preview update as discounts change.

### Saving, editing and cancelling a bill
- As the owner, I want a saved bill to update my stock automatically.
  - [ ] Pressing Save lowers each sold item's stock by the bill quantity.
  - [ ] The new bill appears at the top of Past bills.
  - [ ] The Inventory screen shows the new quantities straight away.
- As the owner, I want to fix a mistake, or handle a return or replacement.
  - [ ] Opening a saved bill and pressing Edit gives me a copy to change.
  - [ ] Saving the copy creates a **new bill with a new number**.
  - [ ] The old bill stays in Past bills, marked **Cancelled** with a note pointing to the new bill.
  - [ ] The cancelled bill's items go back into stock, and the new bill takes its items out, so the stock ends up correct.
  - [ ] Returns and replacements use the same Edit flow.

### Printing and shop settings
- As the owner, I want bills that look like my paper bill.
  - [ ] A printed bill shows the shop header (name, website, phone numbers), "Cash / Credit Memo", bill number, date and customer, the item table, totals, bank details, a terms line, and the QR codes with labels.
  - [ ] All of the header and footer content comes from Settings, not from the code, so another shop can fill in its own.
  - [ ] Sajja's real details are entered as the test shop.

### Past bills
- [ ] The list shows number, date, customer, amount and status, newest first, and can be searched by bill number or customer name.
- [ ] Opening a bill shows exactly what was printed.

## States and Boundaries
- **First use (no products).** Inventory and Billing say "No products yet" with an Add product button.
- **First use (no bills).** Past bills says "No bills yet".
- **Item out of stock.** It shows as Out, and can't be added to a bill.
- **Quantity at the stock limit.** The plus button is disabled.
- **Empty bill.** The Save button is disabled until at least one item is added.
- **Wrong sign-in.** A clear message and no entry.
- **Persistence.** Products, stock, bills, offers and settings are kept after closing and reopening, and are the same on laptop and phone.
- **Cancelled bills.** They are never deleted.
- **One shop at a time.** A signed-in owner sees only their own shop's data.

## Product Decisions
- **One website that works on laptop and phone, with sign-in** — she needs to use it on either device, and it needs maintaining only once. (`scope.md > The Core Loop`)
- **Billing is the first screen after sign-in** — making a bill is what she does most.
- **Stock updates only when a bill is saved** — the sale and the stock stay one action.
- **The plus button is disabled at the stock limit, instead of a warning** — she wants to be unable to oversell.
- **Edit creates a new bill and cancels the old one** — it keeps a record of changes and handles returns the same way.
- **Prices already include GST, so there is no separate tax line** — that is how her business prices today. This replaces the scope's "tax rate per bill".
- **Place of sale is stored on each bill** — it lets state-wise GST be added later.
- **Discounts are percentages, per item or whole bill, with the original price and the discount shown** — it matches how she writes her bills.
- **Both manual discounts and saved offers** — the app should be flexible, and an offer saved once needn't be repeated.
- **Item codes are optional** — most of her products have one, some don't.
- **Header, footer and QR codes are editable settings, and nothing is hard-coded to Sajja** — other shops should be able to use it; Sajja is the real-world test.
- **Shopify stock sync stays secondary** — her live store is only touched once everything else works and is proven safe.
- **Colour theme is decided later** — the mock-up colours are a placeholder.

## What We're Building
- Sign in and one shop account at a time, with data kept per shop.
- Inventory: add, edit, remove, search, filter, and low and out status.
- Billing: item codes, name search, quantities, stock limit, invoice number, date, customer, place of sale, optional shipping & handling.
- Discounts: manual per item and whole bill, and saved offers with an Add offer button.
- Stock-after preview and automatic stock update on save.
- Past bills with search, view, Edit (replace) and Cancelled status.
- Print layout with editable header, footer, bank details and QR codes.
- Settings for the shop details and offers.
- A Home page (added by the learner on 14 Oct 2026, modelled on mock-up A): a greeting, tiles for today's sales, bills today, items running low and payments pending, a sales-this-week chart, a pie chart, a running-low list and recent bills. Simple version only; best sellers, monthly reports, the reorder list and the Customers page stay deferred.
- Mobile and laptop layouts.

## Deferred From the POC
- **Shopify stock sync** — touches her live store; only after everything else is proven safe.
- **Several shops signing up with separate accounts** — needs sign-up flows and separate data; the build stays shop-neutral so this is possible later.
- **State-wise GST rules and filing summaries** — depends on state and country rules.
- **Recording purchases to increase stock** — only manual stock edits are in the proof of concept.
- **Reports beyond the Home page** — best sellers, daily and monthly summaries. (A simple Home page with today's figures and charts is now in the proof of concept.)
- **PDF download** — print is in; saving as PDF may come free with the browser's print dialog.

## Possible Later Enhancements
- Reorder list for suppliers, and suggested restock quantities.
- Customers list and pending payments.
- Barcode scanning.
- Import products from a spreadsheet (Excel or CSV): columns for code, name, category, price, stock and low-stock level, with a check on every row. Requested by the learner after the Inventory slice.
- Offers with start and end dates.

## Non-Goals
- A customer-facing storefront or online ordering — her Shopify store already does that.
- Full GST filing.
- Payment processing.

## Open Questions
- **Dropping the tax rate** (prices already include GST): confirm. Needed before `4-spec`.
- **Shipping & handling field:** it's on her paper bill, but wasn't discussed. Keep or cut? Needed before `4-spec`.
- **Low-stock level:** one level per product that she sets, or a single default? Can wait for the build.
- **Sign-up:** can anyone create an account, or does the first shop get an account made for them? Can wait for `4-spec`.
- **Final colour theme and the shop's logo:** can wait for the build.


