// Runs the real static/js/billing.js against a tiny fake page, to try the "Not them" button.
// Prints one line of JSON describing what happened. Used by tests/test_not_them.py.
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const script = fs.readFileSync(path.join(__dirname, "..", "..", "static", "js", "billing.js"), "utf8");
const els = {};
const activeLog = [];

function makeEl(id) {
  const el = {
    id, value: "", hidden: false, checked: false, disabled: false, className: "", innerHTML: "",
    children: [], style: {}, options: [], dataset: {},
    classList: { add() {}, remove() {}, toggle() {} },
    append(...nodes) { this.children.push(...nodes); },
    replaceChildren(...nodes) { this.children = nodes; },
    setAttribute() {}, addEventListener() {}, removeAttribute() {},
    focus() { activeLog.push(id); },
    querySelector() { return makeEl("child"); },
    querySelectorAll() { return []; },
  };
  let text = "";
  Object.defineProperty(el, "textContent", {
    get() { return text; }, set(v) { text = v; el.children = []; },
  });
  return el;
}

const radios = [Object.assign(makeEl("retail"), { value: "Retail", checked: true }),
                Object.assign(makeEl("b2b"), { value: "B2B" })];
const dataScripts = {
  "products-data": [{ id: 1, code: "KA36", name: "Tray", category: "", price: 45000, stock: 10, low_stock_level: 5 }],
  "offers-data": [], "prefill-data": null, "modes-data": ["Cash", "UPI", "Other"],
};

const document = {
  getElementById(id) {
    if (!els[id]) {
      els[id] = makeEl(id);
      if (id in dataScripts) els[id].textContent = JSON.stringify(dataScripts[id]);
    }
    return els[id];
  },
  querySelector(sel) {
    if (sel === "#place option[selected]") return { value: "Karnataka" };
    if (sel.startsWith('input[name="customer-type"]')) {
      return sel.endsWith(":checked") ? radios.find(r => r.checked) : radios[0];
    }
    return makeEl("other");
  },
  querySelectorAll(sel) { return sel.startsWith('input[name="customer-type"]') ? radios : []; },
  createElement(tag) { return makeEl(tag); },
};

let saved = null;
const asha = { found: true, id: 7, name: "Asha", phone: "9876543210", location: "Indiranagar",
               customer_type: "B2B", last_bill: "", bill_count: 2, total: "₹900" };
async function fetch(url, opts) {
  if (url.startsWith("/customers/lookup")) return { ok: true, json: async () => asha };
  if (url === "/billing/save") {
    saved = JSON.parse(opts.body);
    return { ok: true, json: async () => ({ url: "/bills/1" }) };
  }
  return { ok: true, json: async () => ({ customers: [] }) };
}

const sandbox = { document, fetch, setTimeout, clearTimeout, console, window: {}, Date, Intl };
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(script, sandbox);

(async () => {
  const $ = id => document.getElementById(id);
  $("list").children[0].onclick();                       // add one Tray to the bill
  $("phone").value = "98765 43210";
  $("phone").oninput();
  await new Promise(r => setTimeout(r, 500));            // the phone lookup runs after a short wait
  const matched = { name: $("customer").value, location: $("location").value };
  const button = $("phone-note").children.find(c => c.id === "not-them");
  activeLog.length = 0;
  button.onclick();                                      // tap "Not them"
  const after = { phone: $("phone").value, name: $("customer").value, location: $("location").value,
                  noteHidden: $("phone-note").hidden, focus: activeLog[activeLog.length - 1],
                  type: radios.find(r => r.checked).value };
  await $("save").onclick();
  console.log(JSON.stringify({ matched, button: !!button, after, saved }));
})();
