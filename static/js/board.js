import { api } from "./api.js";
import { h, panel, kv, money, lineChart } from "./ui.js";

export const tierBadge = (t) => h("span", { class: `tier tier-${t.toLowerCase()}` }, t.toUpperCase());

export function boardTable(entries, me) {
  if (!entries.length) return h("p", { class: "muted" }, "No players on the board yet.");
  return h("table", {}, h("thead", {}, h("tr", {}, ...["#", "Player", "Rank", "Net worth", "Cash", "Reputation", "Level"].map((c) => h("th", { scope: "col" }, c)))),
    h("tbody", {}, entries.map((e) => h("tr", { class: me && e.name === me ? "sel" : "" },
      h("td", { class: "num" }, e.rank), h("td", {}, e.name + (me && e.name === me ? " (you)" : "")), h("td", {}, tierBadge(e.tier)),
      h("td", { class: "num" }, money(e.net_worth)), h("td", { class: "num" }, money(e.cash)), h("td", { class: "num" }, e.reputation), h("td", { class: "num" }, e.level)))));
}

export async function renderLeaderboard(box, ctx, me) {
  const d = await api("/api/leaderboard?limit=50");
  box.replaceChildren(panel("Leaderboard", h("p", { class: "muted" }, "Ranked by net worth (cash + bank + stock). Ranks: " +
    d.tiers.map(([n, v]) => `${n} from ${money(v)}`).join(" | ")), boardTable(d.entries, me)));
}

export async function renderStats(box) {
  const s = await api("/api/stats");
  const t = s.totals, p = s.player, g = s.progress, gl = (n) => (n > 0 ? "pos" : n < 0 ? "neg" : "");
  box.replaceChildren(h("div", { class: "grid" },
    panel("Finances", kv([["Net worth", money(p.net_worth), "num"], ["Cash", money(p.cash), "num"], ["Bank", money(p.bank), "num"], ["Stock value", money(p.inventory_value), "num"],
      ["Total revenue", money(t.revenue), "num"], ["Total expenditure", money(t.expenditure), "num"], ["Net profit", money(t.net_profit), "num " + gl(t.net_profit)]])),
    panel("Trading", kv([["Transactions", t.transactions, "num"], ["Sales", t.sales, "num"], ["Profitable sales", t.profitable_sales, "num"],
      ["Average profit per sale", money(t.avg_profit_per_sale), "num " + gl(t.avg_profit_per_sale)], ["Largest profit", money(t.largest_profit), "num pos"],
      ["Largest loss", money(t.largest_loss), "num neg"], ["Units bought", g.units_bought, "num"], ["Units sold", g.units_sold, "num"]])),
    panel("Progress", kv([["Street level", p.level, "num"], ["Total experience", p.xp, "num"], ["Reputation", p.reputation, "num"], ["Highest reputation", p.highest_reputation, "num"],
      ["Wanted now", `${p.wanted}/100`, "num"], ["Highest wanted", `${p.highest_wanted}/100`, "num"], ["Missions", `${g.missions_done}/${g.missions_total}`, "num"],
      ["Contracts done / failed", `${g.contracts_done} / ${g.contracts_failed}`, "num"], ["Hideouts / businesses", `${g.hideouts_owned} / ${g.businesses_owned}`, "num"],
      ["Cycle", p.day, "num"]]))),
    h("div", { style: "margin-top:10px", class: "grid" },
      panel("Cash over time", lineChart(s.series.map((r, i) => ({ x: i + 1, y: r.cash_after })), { xLabel: "Ledger entry", yLabel: "Cash ($)", fmtY: (v) => "$" + v })),
      panel("Recent transactions", s.recent.length ? h("table", {}, h("thead", {}, h("tr", {}, ...["Cycle", "Type", "Item", "Qty", "Total", "Profit"].map((c) => h("th", {}, c)))),
        h("tbody", {}, s.recent.map((r) => h("tr", {}, h("td", { class: "num" }, r.cycle), h("td", {}, r.kind), h("td", {}, r.item_id), h("td", { class: "num" }, r.quantity),
          h("td", { class: "num" }, money(r.total)), h("td", { class: "num " + gl(r.profit || 0) }, r.profit == null ? "" : money(r.profit))))))
        : h("p", { class: "muted" }, "No trades yet. Buy and sell on the Market tab."))));
}
