// Lays the printed bill out as A6 sheets. Every sheet carries the full header and footer; the item
// rows are spread over as many sheets as needed (a row is never split), "Continued on next page"
// closes every sheet but the last, and the totals sit on the last sheet with ruled blank rows
// filling the space between. Plain browser printing: the Print button still calls window.print().
(function () {
  const src = document.getElementById("paper-src");
  const sheets = document.getElementById("sheets");
  if (!src || !sheets) return;

  const draft = document.querySelector(".paper").dataset.draft === "1";
  const rows = [...src.querySelectorAll(".rows-src tr")];
  const totals = src.querySelector(".sh-totals");

  function newSheet() {
    const sheet = document.createElement("div");
    sheet.className = "sheet" + (draft ? " is-draft" : "");
    sheet.append(src.querySelector(".sh-head").cloneNode(true));
    const body = document.createElement("div");
    body.className = "sh-body";
    const table = document.createElement("table");
    table.className = "paper-items";
    table.innerHTML = '<thead><tr><th class="sr">Sr.</th><th class="left">Description of Goods</th>' +
      '<th class="qty">Qty</th><th class="rate">Rate</th><th class="amt">Amount</th></tr></thead><tbody></tbody>';
    body.append(table);
    sheet.append(body);
    sheet.append(src.querySelector(".sh-foot").cloneNode(true));
    return { sheet, body, tbody: table.tBodies[0] };
  }

  function blankRow() {
    const tr = document.createElement("tr");
    tr.className = "blank";
    tr.innerHTML = "<td></td><td></td><td></td><td></td><td></td>";
    return tr;
  }

  function continued() {
    const p = document.createElement("p");
    p.className = "continued";
    p.textContent = "Continued on next page";
    return p;
  }

  const fits = page => page.body.scrollHeight <= page.body.clientHeight + 0.5;

  // Do these rows (and the closing block) fit on one sheet?
  function tryFit(page, list, closing) {
    page.tbody.replaceChildren(...list.map(r => r.cloneNode(true)));
    const extra = closing === "totals" ? totals.cloneNode(true) : continued();
    page.body.append(extra);
    const ok = fits(page);
    extra.remove();
    return ok;
  }

  function build() {
    sheets.replaceChildren();
    const probe = newSheet();
    sheets.append(probe.sheet);
    const pages = [];
    let rest = rows.slice();
    while (true) {
      if (tryFit(probe, rest, "totals")) { pages.push({ list: rest, last: true }); break; }
      let k = rest.length - 1;                       // keep at least one row for the last sheet
      while (k > 1 && !tryFit(probe, rest.slice(0, k), "continued")) k--;
      pages.push({ list: rest.slice(0, k), last: false });
      rest = rest.slice(k);
    }
    sheets.replaceChildren();
    pages.forEach((pg, i) => {
      const page = newSheet();
      page.tbody.replaceChildren(...pg.list.map(r => r.cloneNode(true)));
      page.sheet.querySelector(".px").textContent = i + 1;
      page.sheet.querySelector(".py").textContent = pages.length;
      sheets.append(page.sheet);
      if (pg.last) {
        page.body.append(totals.cloneNode(true));
        // Empty ruled rows fill what is left, like the paper book.
        let added = 0;
        while (added < 60) {
          const blank = blankRow();
          page.tbody.append(blank);
          if (!fits(page)) { blank.remove(); break; }
          added++;
        }
      } else {
        page.body.append(continued());
      }
    });
  }

  function run() { try { build(); } catch (e) { console.error(e); } }
  run();
  window.addEventListener("load", run);          // logo and QR images are in by now
  window.addEventListener("beforeprint", run);
})();
