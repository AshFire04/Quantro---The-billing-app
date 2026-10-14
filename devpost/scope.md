---
doc: scope
status: approved
---

# Quantro

A simple, web-based billing and inventory system where creating one bill automatically updates stock, so a vendor never keeps two sets of records.

## The Unique Kernel
Billing and inventory are one thing. When a vendor creates a bill, the sold items' stock quantities update automatically. This removes separate billing and inventory records, a common source of errors. Later, the same update flows to the vendor's Shopify website.

## Who It's For
The learner's mom, who runs Sajja Home Furnishings (https://sajja.in/, a Shopify store selling bedsheets, table linen, mats, cushion covers and decor to customers worldwide). Today she writes each sale in a bill book (one copy for the customer), then notes the items and profit in a second notebook, and updates her website by hand when she can. When it's busy, the website falls behind. GST filing is hard because everything is on paper and depends on the customer's state. She has minimal technical experience, so the app must be very easy to use.

## The Core Loop
She opens Quantro on her laptop or phone, logs in, creates a bill for a sale (picks products, quantities, prices), saves it, and the stock drops on its own. She comes back for every sale, and to check what is running low.

## Inspiration & Identity
No app to imitate. The feel is simple and friendly, usable by someone with little technology experience, on both laptop and mobile. (Details come in the PRD.)

## Why This Matters to the Learner
"I want her business to be online so it becomes easier for her." It is a real tool for a real business, and also a college project. The learner also wants to learn how to work with an AI agent while making their own tool.

## What "Working" Looks Like
In a short demo video: open Quantro (logged in) and see the product list with current stock. Create a bill with two or three items. Invoice number, subtotal, discount, tax and final amount calculate automatically. Save it. Go back to the product list and see the quantities have dropped, with a low-stock warning on any item under its limit. The previous bill can be found again in a bill list.

## The POC Boundary
- One website that works on laptop and mobile, with login.
- Products: add, edit, remove; name, price, category, quantity; search; low-stock warning.
- Billing: unique invoice number, products and quantities, automatic totals with discount and a tax rate per bill, a "place of sale" (state/country) field on each bill, save and view previous bills.
- Stock decreases automatically when a bill is saved.
- One stock database that the whole app reads and writes.

## Later
- Update her Shopify store's stock when a bill is created (secondary feature; only once the rest works and is proven error-proof, since it touches her live store).
- Record new purchases to increase stock.
- Print/download bills as PDF.
- Dashboard: best sellers, daily and monthly summaries. (A simple Home page with today's sales, bills today, low stock, pending payments and charts was added to the proof of concept by the learner on 14 Oct 2026.)
- State-wise GST rules and filing summaries, using the stored place of sale.

## Explicitly Cut
- A separate customer storefront: she already has a Shopify site, so Quantro won't duplicate one.
- Online ordering by customers: handled by her existing Shopify checkout.
- Full GST filing: depends on state and country rules and is too large for a proof of concept.

