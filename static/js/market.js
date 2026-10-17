import { api, withAuto } from "./api.js";
import { h, panel, kv, money, candleChart, lineChart, pct, sign } from "./ui.js";

export async function renderMarket(box, ctx) {
  if (ctx.marketTimer) { clearInterval(ctx.marketTimer); ctx.marketTimer = null; }
  let { items } = await api("/api/market");
  const compact = !!(ctx.settings && ctx.settings.compact_market);
  let sel = ctx.selected && items.find((i) => i.id === ctx.selected) ? ctx.selected : null;
  let sort = "min_level", chartBox = h("div"), upd = () => {};
  const cur = () => items.find((x) => x.id === sel);
  const search = h("input", { type: "search", placeholder: "Search symbol or item", "aria-label": "Search market" });
  const cat = h("select", { "aria-label": "Category filter" }, h("option", { value: "" }, "All categories"),
    [...new Set(items.map((i) => i.category))].map((c) => h("option", { value: c }, c)));
  const tbl = h("div"), detail = h("div");

  function drawTable() {
    const q = search.value.toLowerCase();
    const rows = items.filter((i) => (!cat.value || i.category === cat.value) && (!q || i.symbol.toLowerCase().includes(q) || i.name.toLowerCase().includes(q)))
      .sort((a, b) => (typeof a[sort] === "string" ? a[sort].localeCompare(b[sort]) : a[sort] - b[sort]));
    const th = (label, key) => h("th", { scope: "col" }, h("button", { onclick: () => { sort = key; drawTable(); }, title: "Sort by " + label }, label));
    tbl.replaceChildren(rows.length ? h("table", {},
      h("thead", {}, h("tr", {}, ...(compact ? [th("Item", "name"), th("Price", "price"), h("th", {}, "Status")]
        : [th("Symbol", "symbol"), th("Item", "name"), th("Tier", "tier"), th("Price", "price"), h("th", {}, "Chg"), th("Supply", "supply"), th("Demand", "demand"), th("Held", "owned"), h("th", {}, "Status")]))),
      h("tbody", {}, rows.map((i) => {
        const chg = pct(i.price, i.prev_price);
        return h("tr", { class: (i.id === sel ? "sel " : "") + (i.unlocked ? "pick" : "lockedrow pick"), tabindex: 0, "aria-selected": String(i.id === sel),
          onclick: () => { sel = i.id; ctx.selected = sel; drawTable(); drawDetail(); }, onkeydown: (e) => { if (e.key === "Enter") e.currentTarget.click(); } },
          ...(compact ? [h("td", {}, i.name), h("td", { class: "num right" }, money(i.price)), h("td", { title: i.locked_reason || "" }, i.unlocked ? "Available" : "Locked")]
          : [h("td", { class: "num" }, i.symbol), h("td", {}, i.name), h("td", {}, i.tier), h("td", { class: "num right" }, money(i.price)),
            h("td", { class: "num " + (chg > 0 ? "pos" : chg < 0 ? "neg" : "muted") }, sign(chg) + Math.abs(chg).toFixed(1) + "%"),
            h("td", { class: "num" }, i.supply.toFixed(2)), h("td", { class: "num" }, i.demand.toFixed(2)), h("td", { class: "num" }, i.owned),
            h("td", {}, i.unlocked ? "Available" : `Locked: ${i.locked_reason}`)]));
      }))) : h("p", { class: "muted" }, "No items match the filters."));
  }

  async function loadChart() {
    const i = cur(); if (!i) return;
    const { candles } = await api(`/api/market/${i.id}/candles?limit=${ctx.range || 60}`);
    const w = Math.max(300, Math.floor(detail.clientWidth || 480));
    const line = ctx.settings && ctx.settings.chart_type === "line";
    chartBox.replaceChildren(line ? lineChart(candles.map((k) => ({ x: k.day, y: k.close })), { w, hgt: 290, xLabel: "Cycle", yLabel: "Price ($)", fmtY: (v) => "$" + v })
      : candleChart(candles, { w, xLabel: "Cycle (one candle per cycle)", yLabel: "Price ($)", fmtY: (v) => "$" + v }));
  }

  function drawDetail() {
    const i = cur();
    if (!i) { detail.replaceChildren(h("p", { class: "muted" }, "Select an item to see details, the live candle chart and to trade.")); return; }
    const range = ctx.range || 60;
    const ranges = h("div", { class: "row" }, [[20, "20 cycles"], [60, "60 cycles"], [200, "200 cycles"]].map(([n, l]) =>
      h("button", { class: range === n ? "primary" : "", "aria-pressed": String(range === n), onclick: () => { ctx.range = n; drawDetail(); } }, l)));
    const qty = h("input", { type: "number", min: 1, max: 1000, value: 1, "aria-label": "Quantity", style: "width:90px" });
    const est = h("span", { class: "num" });
    upd = () => { const x = cur(); if (!x) return; const q = Math.floor(Number(qty.value)) || 0; est.textContent = `Buy ${money(x.price * q)} / Sell ${money(x.sell_price * q)}`; };
    qty.addEventListener("input", upd); upd();
    const trade = async (kind) => {
      const x = cur(); const q = Number(qty.value);
      try { const r = await api(`/api/trade/${kind}`, { method: "POST", body: { item_id: x.id, quantity: q, key: crypto.randomUUID() } });
        ctx.say(`${kind === "buy" ? "Bought" : "Sold"} ${r.quantity} x ${x.name} at ${money(r.unit_price)} = ${money(r.total)}` + (kind === "sell" ? ` (profit ${money(r.profit)})` : ""), false);
        await ctx.refresh(); }
      catch (e) { ctx.say(e.message, true); }
    };
    chartBox = h("div");
    detail.replaceChildren(h("h3", {}, `${i.symbol} · ${i.name}`), h("p", { class: "muted" }, i.description), ranges, chartBox,
      h("p", { class: "muted" }, "The latest value is live and moves during the cycle. When the next cycle starts it is fixed. Switch between candles and a line in Settings."),
      h("h3", { class: "grp" }, "Details"),
      kv([["Category", i.category], ["Quality", i.tier], ["Popularity", i.popularity], ["Made from", i.made_from.join(", ")],
        ["Typical buyers", i.buyers.length ? i.buyers.join(", ") : "None known"], ["Police attention", i.heat],
        ["Normal price range", `${money(i.min_price)} to ${money(i.max_price)}`], ["Base price", money(i.base_price), "num"],
        ["Supply / demand", `${i.supply} / ${i.demand}`, "num"], ["Unlocks at level", i.min_level, "num"], ["You hold here", i.owned, "num"]]),
      h("p", { class: "muted" }, i.tier_note + " Sell quote is 90% of the market price."),
      i.unlocked ? h("div", { class: "row" }, h("label", {}, "Quantity", qty), est,
        h("button", { class: "primary", onclick: () => trade("buy") }, "Buy"),
        h("button", { disabled: i.owned < 1, title: i.owned < 1 ? "You hold none at this stash" : "", onclick: () => trade("sell") }, "Sell"))
        : h("p", { class: "warn" }, `Locked: ${i.locked_reason}.`));
    loadChart();
  }

  search.addEventListener("input", drawTable); cat.addEventListener("change", drawTable);
  box.replaceChildren(h("div", { class: "marketgrid" + (compact ? " compact" : "") },
    panel("Market quotes", h("div", { class: "row" }, h("label", {}, "Search", search), h("label", {}, "Category", cat)), tbl), panel("Item detail", detail)));
  drawTable(); drawDetail();
  // live refresh: prices and the live candle move every few seconds (background refreshes do not count as activity)
  ctx.marketTimer = setInterval(async () => {
    if (ctx.tab !== "Market") { clearInterval(ctx.marketTimer); ctx.marketTimer = null; return; }
    try { await withAuto(async () => { items = (await api("/api/market")).items; drawTable(); upd(); await loadChart(); }); } catch { /* next tick */ }
  }, 6000);
}
