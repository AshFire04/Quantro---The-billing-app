// The Billing screen. The bill lives only in this page until Save is pressed.
// The server recalculates everything on Save, so the numbers here are a preview.

const products = JSON.parse(document.getElementById("products-data").textContent);
const byId = Object.fromEntries(products.map(p => [p.id, p]));
const bill = {};              // product id -> quantity
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
    b.textContent = name;
    b.onclick = () => { activeCategory = name; renderCategories(); renderCards(); };
    $("categories").append(b);
  }
}

function renderCards() {
  const shown = visibleProducts();
  $("cards").innerHTML = "";
  $("no-match").hidden = shown.length > 0;
  for (const p of shown) {
    const out = p.stock <= 0;
    const b = document.createElement("button");
    b.type = "button";
    b.className = "card item-card";
    b.disabled = out;
    const left = out ? "Out of stock" : `${p.stock} in stock`;
    b.innerHTML = `<strong></strong><span class="muted code"></span>
      <span class="item-foot"><span class="mono price"></span><span class="stock-note ${out ? "out" : ""}"></span></span>`;
    b.querySelector("strong").textContent = p.name;
    b.querySelector(".code").textContent = p.code || "";
    b.querySelector(".price").textContent = rupees(p.price);
    b.querySelector(".stock-note").textContent = left;
    b.onclick = () => addItem(p.id);
    $("cards").append(b);
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
  if (next <= 0) delete bill[id];
  else bill[id] = Math.min(next, byId[id].stock);   // can never go above stock
  renderBill();
}

function renderBill() {
  const ids = Object.keys(bill).map(Number);
  $("lines").innerHTML = "";
  let total = 0;
  for (const id of ids) {
    const p = byId[id], qty = bill[id], amount = p.price * qty;
    total += amount;
    const row = document.createElement("div");
    row.className = "line";
    row.innerHTML = `<div class="line-name"><strong></strong><span class="muted mono each"></span></div>
      <div class="qty">
        <button type="button" class="btn small minus" aria-label="One less">−</button>
        <span class="mono qty-num"></span>
        <button type="button" class="btn small plus" aria-label="One more">+</button>
      </div>
      <span class="mono amount"></span>`;
    row.querySelector("strong").textContent = p.name;
    row.querySelector(".each").textContent = `${rupees(p.price)} each`;
    row.querySelector(".qty-num").textContent = qty;
    row.querySelector(".amount").textContent = rupees(amount);
    row.querySelector(".minus").onclick = () => changeQty(id, -1);
    const plus = row.querySelector(".plus");
    plus.disabled = qty >= p.stock;                  // plus stops at the stock limit
    plus.onclick = () => changeQty(id, 1);
    $("lines").append(row);
  }
  $("empty-bill").hidden = ids.length > 0;
  $("total").textContent = rupees(total);
  $("save").disabled = ids.length === 0;

  $("error").hidden = true;
  renderPayNow();                       // the total changed, so what is paid now changes too
}

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
  for (const id of Object.keys(bill)) delete bill[id];
  $("customer").value = "";
  $("phone").value = "";
  $("location").value = "";
  if (dueOpen) $("due-toggle").onclick();   // closes the due panel and empties it
  renderBill();
};

// ---- Order source and payment ----

const modes = JSON.parse(document.getElementById("modes-data").textContent);
let splitting = false;
let splitRows = [];           // [{mode, other, amount}] used only while Split is on

function showOther(select, input) {
  input.hidden = select.value !== "Other";
}
$("source").onchange = () => showOther($("source"), $("source-other"));
$("pay-mode").onchange = () => showOther($("pay-mode"), $("pay-other"));

function billTotal() {
  return Object.entries(bill).reduce((sum, [id, qty]) => sum + byId[id].price * qty, 0);
}

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
  if (!dueOpen) { $("due-amount").value = ""; $("due-date").value = ""; }
  else $("due-date").min = new Date().toLocaleDateString("en-CA");   // today, as YYYY-MM-DD
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

$("save").onclick = async () => {
  $("save").disabled = true;
  const items = Object.entries(bill).map(([id, quantity]) => ({ product_id: Number(id), quantity }));
  try {
    const res = await fetch("/billing/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items, customer: $("customer").value, phone: $("phone").value,
                             location: $("location").value,
                             due_amount: dueOpen ? $("due-amount").value : "",
                             due_date: dueOpen ? $("due-date").value : "",
                             place_of_sale: $("place").value,
                             order_source: $("source").value, order_source_other: $("source-other").value,
                             payments: paymentsForServer() }),
    });
    const data = await res.json();
    if (res.ok) { window.location = data.url; return; }
    $("error").textContent = data.error;
  } catch (err) {
    $("error").textContent = "Couldn't save the bill; nothing was changed";
  }
  $("error").hidden = false;
  $("save").disabled = false;
};

renderCategories();
renderCards();
renderBill();

