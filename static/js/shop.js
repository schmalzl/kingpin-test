import { api } from "./api.js";
import { h, panel, money } from "./ui.js";

export async function renderShop(box, ctx) {
  const { shops } = await api("/api/shops");
  let sel = ctx.shop && shops.find((s) => s.id === ctx.shop) ? ctx.shop : null;
  const body = h("div");
  const itemCard = (it) => h("div", { class: "card" },
    h("div", {}, h("strong", {}, it.name), " ", h("span", { class: "num" }, money(it.price))), h("div", { class: "muted" }, it.description), h("div", { class: "num" }, it.text),
    it.max ? h("div", { class: "muted" }, `Owned ${it.owned}/${it.max}`) : (it.owned ? h("div", { class: "muted" }, `Owned ${it.owned}`) : null),
    it.reason ? h("div", { class: "warn" }, it.reason) : null,
    h("button", { class: "primary", disabled: !it.available, onclick: async () => {
      try { const r = await api("/api/shops/buy", { method: "POST", body: { item_id: it.id, key: crypto.randomUUID() } });
        ctx.say(`Bought ${r.item} for ${money(r.price)}: ${r.effects_text}`, false); await ctx.refresh(); } catch (e) { ctx.say(e.message, true); } } }, "Buy"));
  function draw() {
    const shop = shops.find((s) => s.id === sel);
    if (!shop) {
      body.replaceChildren(h("div", { class: "cards" }, shops.map((s) => h("div", { class: "card" }, h("strong", {}, s.name), h("div", { class: "muted" }, s.description),
        h("div", { class: "muted" }, `${s.items.filter((i) => !i.hidden).length} items on sale`),
        h("button", { class: "primary", onclick: () => { sel = s.id; ctx.shop = sel; draw(); } }, "Enter shop")))));
      return;
    }
    const open = shop.items.filter((i) => !i.hidden), locked = shop.items.filter((i) => i.hidden);
    body.replaceChildren(h("div", { class: "row" }, h("button", { onclick: () => { sel = null; ctx.shop = null; draw(); } }, "Leave shop"), h("strong", {}, shop.name)),
      h("p", { class: "muted" }, shop.description), h("div", { class: "cards" }, open.map(itemCard)),
      locked.length ? h("details", { class: "done" }, h("summary", {}, `Locked (${locked.length})`), h("div", { class: "cards", style: "margin-top:8px" },
        locked.map((i) => h("div", { class: "card" }, h("strong", {}, i.name), h("div", { class: "warn" }, i.reason))))) : null);
  }
  box.replaceChildren(panel("Shops", body)); draw();
}
