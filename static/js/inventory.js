import { api } from "./api.js";
import { h, panel, money, bar } from "./ui.js";

export async function renderInventory(box) {
  const inv = await api("/api/inventory");
  const [{ transactions: tx }, { ledger }] = await Promise.all([api("/api/transactions"), api("/api/ledger")]);
  const gl = (n) => (n > 0 ? "pos" : n < 0 ? "neg" : "");
  box.replaceChildren(h("div", { class: "grid" },
    panel(`Stash: ${inv.location}`, h("p", { class: "num" }, `${inv.used}/${inv.capacity} units used`), bar(inv.used, inv.capacity, "Storage used"),
      inv.items.length ? h("table", {}, h("thead", {}, h("tr", {}, ...["Item", "Qty", "Bought for", "Avg cost", "Est. value", "Unrealized"].map((c) => h("th", {}, c)))),
        h("tbody", {}, inv.items.map((r) => h("tr", {}, h("td", {}, r.name), h("td", { class: "num" }, r.quantity), h("td", { class: "num" }, money(r.cost_total)), h("td", { class: "num" }, money(r.avg_cost)),
          h("td", { class: "num" }, money(r.est_value)), h("td", { class: "num " + gl(r.unrealized) }, (r.unrealized > 0 ? "+" : "") + money(r.unrealized))))))
        : h("p", { class: "muted" }, "This stash is empty. Buy something on the Market tab.")),
    panel("Transactions", tx.length ? h("table", {}, h("thead", {}, h("tr", {}, ...["Cycle", "Type", "Item", "Qty", "Unit", "Total", "Profit"].map((c) => h("th", {}, c)))),
      h("tbody", {}, tx.map((t) => h("tr", {}, h("td", { class: "num" }, t.cycle), h("td", {}, t.kind), h("td", {}, t.item_id), h("td", { class: "num" }, t.quantity),
        h("td", { class: "num" }, money(t.unit_price)), h("td", { class: "num" }, money(t.total)), h("td", { class: "num " + gl(t.profit || 0) }, t.profit == null ? "" : money(t.profit))))))
      : h("p", { class: "muted" }, "No trades yet.")),
    panel("Financial ledger", h("table", {}, h("thead", {}, h("tr", {}, ...["#", "Cycle", "Kind", "Amount", "Cash after"].map((c) => h("th", {}, c)))),
      h("tbody", {}, ledger.map((l) => h("tr", {}, h("td", { class: "num" }, l.id), h("td", { class: "num" }, l.cycle), h("td", {}, l.kind),
        h("td", { class: "num " + gl(l.amount) }, (l.amount > 0 ? "+" : "") + money(l.amount)), h("td", { class: "num" }, money(l.cash_after)))))))));
}
