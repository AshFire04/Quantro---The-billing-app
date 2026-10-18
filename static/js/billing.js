// The Billing screen. The bill lives only in this page until Save is pressed.
// The server recalculates everything on Save, so the numbers here are a preview.

const products = JSON.parse(document.getElementById("products-data").textContent);
const byId = Object.fromEntries(products.map(p => [p.id, p]));
const bill = {};              // product id -> quantity
const defaultPlace = document.querySelector("#place option[selected]").value;
let activeCategory = "All";

const $ = id => document.getElementById(id);
const rupees = paise => "₹" + (paise / 100).toLocaleString("en-IN",
  { minimumFractionDigits: paise % 100 ? 2 : 0, maximumFractionDigits: 2 });

// ---- Item cards (left side) ----

function visibleProducts() {
  const q = $("search").value.trim().toLowerCase();
  return products.filter(p =>
    (activeCategory === "All" || p.category === activeCategory) &&
    (!q || p.name.toLowerCase().includes(q) || (p.code || "").toLowerCase().includes(q)));
}

function renderCategories() {
  const names = ["All", ...new Set(products.map(p => p.category).filter(Boolean))];
  $("categories").innerHTML = "";
  for (const name of names) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip" + (name === activeCategory ? " active" : "");
    b.setAttribute("aria-pressed", name === activeCategory);
    b.textContent = name;
    b.onclick = () => { activeCategory = name; renderCategories(); renderCards(); };
    $("categories").append(b);
  }
}

function renderCards() {
  const shown = visibleProducts();
  $("list").innerHTML = "";
  if (shown.length === 0) {
    $("list").innerHTML = `<div class="empty-note">No items match. Try a different code or name.</div>`;
    return;
  }
  for (const p of shown) {
    const left = p.stock - (bill[p.id] || 0);              // what would still be on the shelf
    const state = left <= 0 ? "out" : left <= p.low_stock_level ? "low" : "";
    const row = document.createElement("button");
    row.type = "button";
    row.className = "item-row";
    row.disabled = left <= 0;
    row.innerHTML = `<span class="info"><span class="name"></span><span class="code"></span></span>
      <span class="mono price"></span><span class="stock ${state}"></span>`;
    row.querySelector(".name").textContent = p.name;
    row.querySelector(".code").textContent = p.code || "";
    row.querySelector(".price").textContent = rupees(p.price);
    row.querySelector(".stock").textContent = left <= 0 ? "Out of stock" : `${left} in stock`;
    row.onclick = () => addItem(p.id);
    $("list").append(row);
  }
}
// ---- The bill (right side) ----

function addItem(id) {
  const p = byId[id];
  if (p.stock <= 0) return;
  bill[id] = Math.min((bill[id] || 0) + 1, p.stock);
  renderBill();
}

function changeQty(id, delta) {
  const next = (bill[id] || 0) + delta;
  if (next <= 0) { delete bill[id]; delete discounts[id]; }
  else bill[id] = Math.min(next, byId[id].stock);   // can never go above stock
  renderBill();
}

// Percentages are handled as whole hundredths (12.5% -> 1250) and amounts as whole paise,
// so the numbers here match the server exactly. The server still recalculates on Save.
const discounts = {};         // product id -> the percentage typed for that item
const lineCells = {};         // product id -> the amount cell on its row
const lineInputs = {};        // product id -> the discount box on its row

function hundredths(text) {
  const n = parseFloat(text);
  return n > 0 ? Math.min(Math.round(n * 100), 10000) : 0;
}

function takeOff(paise, hundredthsOff) {
  return Math.floor((paise * (10000 - hundredthsOff) + 5000) / 10000);   // rounds half up
}

// ---- Saved offers: a percentage typed by hand always wins; a blank box uses the best picked offer ----

const offers = JSON.parse(document.getElementById("offers-data").textContent);
const picked = new Set();     // ids of the offers ticked on this bill

function offerHundredths(offer) { return Math.round(offer.pct * 100); }

function bestCategoryOffer(id) {
  const category = (byId[id].category || "").trim().toLowerCase();
  if (!category) return null;
  const matching = offers.filter(o => picked.has(o.id) && o.applies_to === "category" &&
                                      o.category.trim().toLowerCase() === category);
  return matching.sort((a, b) => b.pct - a.pct)[0] || null;
}

function bestWholeOffer(subtotal) {
  const qualifying = offers.filter(o => picked.has(o.id) && o.applies_to === "bill" &&
                                        subtotal >= o.min_amount);
  return qualifying.sort((a, b) => b.pct - a.pct)[0] || null;
}

function isTyped(text) { return (text || "").trim() !== ""; }

function lineHundredths(id) {
  if (isTyped(discounts[id])) return hundredths(discounts[id]);
  const offer = bestCategoryOffer(id);
  return offer ? offerHundredths(offer) : 0;
}

function lineAmount(id) {
  return takeOff(byId[id].price * bill[id], lineHundredths(id));
}

function wholeHundredths(subtotal) {
  if (isTyped($("whole-discount").value)) return hundredths($("whole-discount").value);
  const offer = bestWholeOffer(subtotal);
  return offer ? offerHundredths(offer) : 0;
}

function computeTotals() {
  const subtotal = Object.keys(bill).reduce((sum, id) => sum + lineAmount(id), 0);
  const afterWhole = takeOff(subtotal, wholeHundredths(subtotal));
  const shipping = Math.max(Math.round((parseFloat($("shipping").value) || 0) * 100), 0);
  const exact = afterWhole + shipping;
  const total = Math.floor((exact + 50) / 100) * 100;           // whole rupees, half up
  return { subtotal, wholeOff: subtotal - afterWhole, shipping, roundOff: total - exact, total };
}

function renderBill() {
  const ids = Object.keys(bill).map(Number);
  $("lines").innerHTML = "";
  if (ids.length === 0) {
    $("lines").innerHTML = `<div class="lines-empty">Tap an item on the left to add it to the bill.</div>`;
  }
  for (const id of ids) {
    const p = byId[id], qty = bill[id];
    const row = document.createElement("div");
    row.className = "line";
    row.innerHTML = `<div class="line-name"><span class="n"></span><span class="c"></span></div>
      <div class="qty">
        <button type="button" class="minus" aria-label="One less">−</button>
        <span class="mono qty-num"></span>
        <button type="button" class="plus" aria-label="One more">+</button>
      </div>
      <div class="mono amt"></div>
      <label class="line-discount">Discount %
        <input class="mini-input" inputmode="decimal" placeholder="0">
      </label>`;
    row.querySelector(".n").textContent = p.name;
    row.querySelector(".c").textContent = `${p.code ? p.code + " · " : ""}${rupees(p.price)} each`;
    row.querySelector(".qty-num").textContent = qty;
    row.querySelector(".minus").onclick = () => changeQty(id, -1);
    const plus = row.querySelector(".plus");
    plus.disabled = qty >= p.stock;                  // plus stops at the stock limit
    plus.onclick = () => changeQty(id, 1);
    const box = row.querySelector(".line-discount input");
    box.value = discounts[id] || "";
    box.oninput = () => { discounts[id] = box.value; refreshTotals(); };
    lineInputs[id] = box;
    lineCells[id] = row.querySelector(".amt");
    $("lines").append(row);
  }
  $("save").disabled = ids.length === 0;
  if ($("draft")) $("draft").disabled = ids.length === 0;
  $("error").hidden = true;
  renderCards();                        // the stock left on each item changes as the bill changes
  refreshTotals();
}
// Updates every number on the right without rebuilding the rows (so typing isn't interrupted).
function refreshTotals() {
  for (const id of Object.keys(bill)) {
    const original = byId[id].price * bill[id], now = lineAmount(id);
    lineCells[id].innerHTML = now === original ? rupees(now)
      : `<s>${rupees(original)}</s>${rupees(now)}`;   // original, then discounted
  }
  // A blank discount box shows the offer percentage that would apply to it.
  for (const id of Object.keys(bill)) {
    const offer = bestCategoryOffer(id);
    lineInputs[id].placeholder = offer ? `${offer.pct} (${offer.name})` : "0";
  }
  const t = computeTotals();
  const wholeOffer = bestWholeOffer(t.subtotal);
  $("whole-discount").placeholder = wholeOffer ? `${wholeOffer.pct} (${wholeOffer.name})` : "0";
  $("subtotal").textContent = rupees(t.subtotal);
  $("whole-off").textContent = t.wholeOff ? "−" + rupees(t.wholeOff) : "";
  $("whole-off").hidden = $("whole-off-label").hidden = !t.wholeOff;
  $("round-off").textContent = (t.roundOff > 0 ? "+" : t.roundOff < 0 ? "−" : "") +
    rupees(Math.abs(t.roundOff));
  $("total").textContent = rupees(t.total);
  renderPayNow();                       // the total changed, so what is paid now changes too
}
$("whole-discount").oninput = refreshTotals;
$("shipping").oninput = refreshTotals;
// ---- Search box: typing filters; Enter adds an exact code, or the only match ----

$("search").addEventListener("input", renderCards);
$("search").addEventListener("keydown", e => {
  if (e.key !== "Enter") return;
  e.preventDefault();
  const q = $("search").value.trim().toLowerCase();
  const exact = products.find(p => p.code && p.code.toLowerCase() === q);
  const match = exact || (visibleProducts().length === 1 ? visibleProducts()[0] : null);
  if (match) { addItem(match.id); $("search").value = ""; renderCards(); }
});

$("clear").onclick = () => {
  for (const id of Object.keys(bill)) { delete bill[id]; delete discounts[id]; }
  $("whole-discount").value = "";
  $("shipping").value = "";
  picked.clear();
  for (const o of offers) picked.add(o.id);             // offers are ticked again on a fresh bill
  renderOffers();
  $("customer").value = "";
  $("phone").value = "";
  selectedCustomer = null;
  showNote("");
  $("location").value = "";
  $("place").value = defaultPlace;
  showOther($("place"), $("place-other"));
  $("place-other").value = "";
  document.querySelector('input[name="customer-type"]').checked = true;   // Retail
  $("order-date").value = today();
  if (dueOpen) $("due-toggle").onclick();   // closes the due panel and empties it
  renderBill();
};

// ---- Customers ----
// A customer is a saved record with an id. The phone number finds one exactly; the name box
// searches and only fills the form when you click a match. A name alone never merges anyone.

let selectedCustomer = null;                 // the saved customer this bill is for, or null

// The same tidy-up the server does: +91, 91, 0091 or a leading 0 come off, then 10 digits.
function phoneDigits(text) {
  let d = (text || "").replace(/\D/g, "");
  if (d.length === 14 && d.startsWith("0091")) d = d.slice(4);
  else if (d.length === 12 && d.startsWith("91")) d = d.slice(2);
  else if (d.length === 11 && d.startsWith("0")) d = d.slice(1);
  return d;
}
const isMobile = d => /^[6-9]\d{9}$/.test(d);
const typeRadios = () => document.querySelectorAll('input[name="customer-type"]');

function showNote(text, tone) {
  const note = $("phone-note");
  note.className = "small " + (tone || "muted");
  note.textContent = text;
  note.hidden = !text;
  if (selectedCustomer && tone === "ok") {
    const clear = document.createElement("button");
    clear.type = "button"; clear.className = "link-button"; clear.id = "not-them"; clear.textContent = "Not them";
    clear.onclick = notThem;
    note.append(" ", clear);
  }
}

// "Not them": the phone matched the wrong person. Forget the match and start the customer again;
// the items, discounts and Retail/B2B choice stay as they are. No confirmation.
function notThem() {
  clearTimeout(phoneTimer);
  selectedCustomer = null;                   // the bill is saved with no customer_id
  $("phone").value = "";
  $("customer").value = "";
  $("location").value = "";
  $("customer-results").hidden = true;
  showNote("");
  $("phone").focus();
}

function pickCustomer(c) {
  selectedCustomer = c;
  $("customer").value = c.name;
  $("location").value = c.location;
  if (c.phone) $("phone").value = c.phone;
  for (const r of typeRadios()) r.checked = r.value === c.customer_type;
  $("customer-results").hidden = true;
  showNote(`Saved customer: ${c.name}. Last bill ${c.last_bill || "none yet"} · ${c.bill_count} bill` +
           `${c.bill_count === 1 ? "" : "s"} · ${c.total} billed.`, "ok");
}

let phoneTimer = null;
$("phone").oninput = () => {
  clearTimeout(phoneTimer);
  const d = phoneDigits($("phone").value);
  if (selectedCustomer && selectedCustomer.phone !== d) selectedCustomer = null;   // a different number
  if (!d) return showNote("");
  if (d.length < 10 && !(d.length > 10)) return showNote("");
  if (!isMobile(d)) {
    return showNote("Enter a 10-digit mobile number starting with 6, 7, 8 or 9.", "bad");
  }
  if (selectedCustomer) return;
  phoneTimer = setTimeout(async () => {
    try {
      const data = await (await fetch("/customers/lookup?phone=" + encodeURIComponent(d))).json();
      if (phoneDigits($("phone").value) !== d) return;                  // they kept typing
      if (data.found) pickCustomer(data);
      else showNote("New customer. Enter their name; they are saved when you save the bill.");
    } catch (err) { /* offline: carry on and type the details */ }
  }, 250);
};

// The name box: matches by name or phone, with an "Add as new customer" choice at the end.
let nameTimer = null;
async function showNameMatches() {
  const q = $("customer").value.trim();
  let list = [];
  try {
    list = (await (await fetch("/customers/search?q=" + encodeURIComponent(q))).json()).customers;
  } catch (err) { return; }
  if ($("customer").value.trim() !== q) return;
  const box = $("customer-results");
  box.replaceChildren(...list.map(c => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "pick";
    const name = document.createElement("strong"); name.textContent = c.name;
    const rest = document.createElement("span");
    rest.textContent = [c.phone || (c.legacy ? "No phone, older bill" : "No phone"), c.location,
                        c.last_bill ? "last bill " + c.last_bill : "no bills yet"].filter(Boolean).join(" · ");
    b.append(name, rest);
    b.onmousedown = e => { e.preventDefault(); pickCustomer(c); };
    return b;
  }));
  if (q) {
    const add = document.createElement("button");
    add.type = "button"; add.className = "pick add";
    add.textContent = `+ Add “${q}” as new customer`;
    add.onmousedown = e => {
      e.preventDefault();
      selectedCustomer = null;
      box.hidden = true;
      showNote("New customer. They are saved when you save the bill.");
    };
    box.append(add);
  }
  box.hidden = box.children.length === 0;
}
$("customer").oninput = () => { clearTimeout(nameTimer); nameTimer = setTimeout(showNameMatches, 250); };
$("customer").onfocus = showNameMatches;
$("customer").onblur = () => setTimeout(() => { $("customer-results").hidden = true; }, 150);

// ---- The offer tick-boxes ----

function renderOffers() {
  $("offers-box").hidden = offers.length === 0;
  $("offers-list").innerHTML = "";
  for (const o of offers) {
    const label = document.createElement("label");
    label.className = "offer-pick";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = picked.has(o.id);
    box.onchange = () => { box.checked ? picked.add(o.id) : picked.delete(o.id); refreshTotals(); };
    const text = document.createElement("span");
    const where = o.applies_to === "category" ? `on ${o.category}`
      : (o.min_amount ? `on the bill above ${rupees(o.min_amount)}` : "on the whole bill");
    text.textContent = ` ${o.name}: ${o.pct}% off ${where}`;
    label.append(box, text);
    $("offers-list").append(label);
  }
}

// ---- Order source and payment ----

const modes = JSON.parse(document.getElementById("modes-data").textContent);
let splitting = false;
let splitRows = [];           // [{mode, other, amount}] used only while Split is on

function showOther(select, input) {
  input.hidden = select.value !== "Other";
}
$("source").onchange = () => showOther($("source"), $("source-other"));
$("place").onchange = () => showOther($("place"), $("place-other"));

// Today as YYYY-MM-DD, in the owner's own time zone.
const today = () => new Date().toLocaleDateString("en-CA");
const customerType = () => document.querySelector('input[name="customer-type"]:checked').value;
const placeOfSale = () => $("place").value === "Other" ? $("place-other").value : $("place").value;
$("order-date").max = $("order-date").value = today();
$("pay-mode").onchange = () => showOther($("pay-mode"), $("pay-other"));

function billTotal() { return computeTotals().total; }

// ---- Payment due: part of the bill the customer will pay later ----

let dueOpen = false;

function dueNow() {
  if (!dueOpen) return 0;
  const due = Math.round((parseFloat($("due-amount").value) || 0) * 100);
  return Math.min(Math.max(due, 0), billTotal());
}

function payNow() { return billTotal() - dueNow(); }

function renderPayNow() {
  const due = dueNow();
  $("pay-now").hidden = !dueOpen || billTotal() === 0;
  $("pay-now").textContent = due === billTotal() && due > 0
    ? "Nothing is paid now; the whole bill is due."
    : `Paid now: ${rupees(payNow())} · Due later: ${rupees(due)}`;
  // With nothing paid now there is no payment mode to choose.
  $("single-payment").hidden = splitting || (due > 0 && payNow() === 0);
  $("split-payment").hidden = !splitting || (due > 0 && payNow() === 0);
  if (splitting) renderSplitLeft();
}

$("due-toggle").onclick = () => {
  dueOpen = !dueOpen;
  $("due-panel").hidden = !dueOpen;
  $("due-toggle").textContent = dueOpen ? "No due" : "Add due";
  if (!dueOpen) $("due-amount").value = "";
  renderPayNow();
};
$("due-amount").oninput = renderPayNow;

function splitPaid() {
  // Amounts are typed in rupees; work in whole paise to avoid rounding drift.
  return splitRows.reduce((sum, r) => sum + Math.round((parseFloat(r.amount) || 0) * 100), 0);
}

function renderSplitLeft() {
  const left = payNow() - splitPaid();
  $("split-left").textContent = left === 0 ? "Payments match the amount being paid now."
    : left > 0 ? `Still to assign: ${rupees(left)}` : `Over by ${rupees(-left)}`;
}

function renderSplit() {
  $("split-rows").innerHTML = "";
  splitRows.forEach((row, i) => {
    const div = document.createElement("div");
    div.className = "split-row";
    div.innerHTML = `<select aria-label="Payment mode"><option value="">Mode…</option>
        ${modes.map(m => `<option>${m}</option>`).join("")}</select>
      <input class="amount-in" inputmode="decimal" placeholder="Amount ₹" aria-label="Amount">
      <button type="button" class="btn small" aria-label="Remove this payment">✕</button>
      <input class="other-input" placeholder="Type the payment mode">`;
    const [select, amount, remove, other] = div.children;
    select.value = row.mode; amount.value = row.amount; other.value = row.other;
    other.hidden = row.mode !== "Other";
    select.onchange = () => { row.mode = select.value; other.hidden = row.mode !== "Other"; };
    amount.oninput = () => { row.amount = amount.value; renderSplitLeft(); };
    other.oninput = () => { row.other = other.value; };
    remove.onclick = () => { splitRows.splice(i, 1); renderSplit(); };
    remove.hidden = splitRows.length <= 2;
    $("split-rows").append(div);
  });
  renderSplitLeft();
}

$("split-toggle").onclick = () => {
  splitting = !splitting;
  if (splitting) {
    splitRows = [{ mode: $("pay-mode").value, other: $("pay-other").value, amount: "" },
                 { mode: "", other: "", amount: "" }];
    renderSplit();
  }
  $("split-toggle").textContent = splitting ? "No split" : "Split";
  renderPayNow();
};
$("split-add").onclick = () => { splitRows.push({ mode: "", other: "", amount: "" }); renderSplit(); };

function paymentsForServer() {
  if (dueNow() > 0 && payNow() === 0) return [];
  if (!splitting) {
    return [{ mode: $("pay-mode").value, other: $("pay-other").value }];   // no amount = whole bill
  }
  return splitRows.map(r => ({ mode: r.mode, other: r.other, amount: r.amount }));
}

// ---- Save ----

// Draft bill / Update draft keep the bill as a draft (no stock change); Save finalises it.
async function submitBill(asDraft) {
  $("save").disabled = true;
  if ($("draft")) $("draft").disabled = true;
  const items = Object.entries(bill).map(([id, quantity]) =>
    ({ product_id: Number(id), quantity, discount: discounts[id] || "" }));
  try {
    const res = await fetch("/billing/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items, customer: $("customer").value, phone: $("phone").value,
                             customer_id: selectedCustomer ? selectedCustomer.id : null,
                             location: $("location").value,
                             whole_discount: $("whole-discount").value, shipping: $("shipping").value,
                             due_amount: dueOpen ? $("due-amount").value : "",
                             place_of_sale: placeOfSale(), customer_type: customerType(),
                             order_date: $("order-date").value,
                             order_source: $("source").value, order_source_other: $("source-other").value,
                             payments: paymentsForServer(),
                             replaces: prefill ? prefill.replaces : null,
                             draft_id: prefill ? prefill.draft_id : null,
                             draft: asDraft,
                             offer_ids: [...picked] }),
    });
    const data = await res.json();
    if (res.ok) { window.location = data.url; return; }
    $("error").textContent = data.error;
  } catch (err) {
    $("error").textContent = "Couldn't save the bill; nothing was changed";
  }
  $("error").hidden = false;
  $("save").disabled = false;
  if ($("draft")) $("draft").disabled = false;
}
$("save").onclick = () => submitBill(false);
if ($("draft")) $("draft").onclick = () => submitBill(true);

// ---- Editing a saved bill: fill the screen from the old bill's copy ----

const prefill = JSON.parse(document.getElementById("prefill-data").textContent);

function applyPrefill(old) {
  for (const item of old.items) {
    const p = byId[item.product_id];
    // p.stock already counts a saved bill's items. A draft keeps its quantity as saved, even if the
    // shelf has since run short: finalising is what checks the stock.
    bill[item.product_id] = old.draft_id ? item.quantity : Math.min(item.quantity, p.stock);
    if (item.discount) discounts[item.product_id] = item.discount;
  }
  $("customer").value = old.customer;
  $("phone").value = old.phone;
  if (old.customer_id) selectedCustomer = { id: old.customer_id, phone: phoneDigits(old.phone) };
  $("location").value = old.location;
  if ([...$("place").options].some(o => o.value === old.place && o.value !== "Other")) {
    $("place").value = old.place;
  } else if (old.place) {                                // typed under Other, or from an old bill
    $("place").value = "Other";
    $("place-other").value = old.place;
  }
  showOther($("place"), $("place-other"));
  for (const r of document.querySelectorAll('input[name="customer-type"]')) {
    r.checked = r.value === old.customer_type;
  }
  $("order-date").value = old.order_date;
  $("source").value = old.source;
  $("source-other").value = old.source_other;
  showOther($("source"), $("source-other"));
  for (const id of old.offer_ids) picked.add(id);
  $("whole-discount").value = old.whole_discount;
  $("shipping").value = old.shipping;
  if (old.due_amount) {
    $("due-toggle").onclick();
    $("due-amount").value = old.due_amount;
  }
  if (old.payments.length === 1) {
    $("pay-mode").value = old.payments[0].mode;
    $("pay-other").value = old.payments[0].other;
    showOther($("pay-mode"), $("pay-other"));
  } else if (old.payments.length > 1) {
    $("split-toggle").onclick();                       // switches Split on
    splitRows = old.payments.map(p => ({ mode: p.mode, other: p.other, amount: p.amount }));
    renderSplit();
  }
}

if (prefill) applyPrefill(prefill);
else for (const o of offers) picked.add(o.id);          // a new bill starts with every offer ticked
renderOffers();
renderCategories();
renderCards();
renderBill();





