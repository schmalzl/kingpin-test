import { api } from "./api.js";
import { h, panel, kv, bar, money, meter, stars } from "./ui.js";

const evCls = { good: "pos", info: "", warning: "warn", severe: "neg" };
const evTag = { good: "GOOD", info: "INFO", warning: "WARN", severe: "SEVERE" }; // text label, not colour alone

async function run(ctx, fn) {
  try { const r = await fn(); await ctx.refresh(); return r; } catch (e) { ctx.say(e.message, true); }
}

function eventList(events, ctx, limit = 30) {
  if (!events.length) return h("p", { class: "muted" }, "Nothing has happened yet. The street never sleeps, so give it a few minutes.");
  return h("div", {}, events.slice(0, limit).map((e) => h("div", { class: "evrow" },
    h("div", {}, h("span", { class: "badge " + evCls[e.severity] }, evTag[e.severity]), " ", h("strong", {}, e.title), " ", e.unread ? h("span", { class: "badge warn" }, "NEW") : null,
      " ", h("span", { class: "muted num" }, `cycle ${e.cycle}`)),
    h("div", { class: "muted" }, e.description), e.effects ? h("div", { class: "num" }, e.effects) : null,
    e.status === "pending" ? h("div", { class: "row", style: "margin-top:4px" }, e.choices.map((c, i) =>
      h("button", { class: i === 0 ? "primary" : "", onclick: () => run(ctx, async () => {
        const r = await api(`/api/events/${e.id}/respond`, { method: "POST", body: { choice: i } }); ctx.say(r.result, false); }) }, c.label)),
      h("span", { class: "warn" }, `Decide by cycle ${e.expires_cycle}, or the default applies.`)) : null)));
}

function bankForm(s, ctx) {
  const amt = h("input", { id: "bk", type: "number", min: 1, step: 1, value: 100, "aria-label": "Amount" });
  const go = (action) => run(ctx, async () => {
    const r = await api("/api/bank", { method: "POST", body: { action, amount: Math.floor(Number(amt.value)), key: crypto.randomUUID() } });
    ctx.say(`${action === "deposit" ? "Deposited" : "Withdrew"} ${money(r.amount)}. Cash ${money(r.cash)}, bank ${money(r.bank)}.`, false); });
  const all = (action, max) => h("button", { title: `All (${money(max)})`, disabled: max < 1, onclick: () => { amt.value = max; } }, "max");
  return h("div", { style: "margin-top:10px" }, h("div", { class: "sect" }, "Bank"),
    h("div", { class: "row" }, h("label", { for: "bk" }, "Amount", amt), h("button", { class: "primary", onclick: () => go("deposit") }, "Deposit"), h("button", { onclick: () => go("withdraw") }, "Withdraw")),
    h("div", { class: "row", style: "margin-top:4px" }, h("span", { class: "muted" }, "Quick amount:"), all("deposit", s.cash), h("span", { class: "muted" }, `(sets the amount to your cash, ${money(s.cash)})`)),
    h("p", { class: "muted" }, "Money in the bank cannot be lost to fines or expenses that hit your cash."));
}

export async function renderOverview(box, s, ctx) {
  const { events } = await api("/api/events");
  const m = s.active_mission;
  const pending = events.filter((e) => e.status === "pending");
  const resolved = events.filter((e) => e.status === "resolved").length;
  const unreadIds = events.filter((e) => e.unread).map((e) => e.id);
  const clearBtn = h("button", { disabled: resolved === 0, title: resolved === 0 ? "Nothing to clear" : "", onclick: () => run(ctx, async () => {
    const r = await api("/api/events/clear", { method: "POST", body: {} }); ctx.say(`Cleared ${r.cleared} event(s).`, false); }) }, "Clear news");
  box.replaceChildren(
    panel(`News${pending.length ? ` (${pending.length} awaiting your decision)` : unreadIds.length ? ` (${unreadIds.length} new)` : ""}`,
      h("div", { class: "feedtools" }, clearBtn, h("span", { class: "muted" }, "Events waiting for your decision are never cleared.")), eventList(events, ctx)),
    h("div", { class: "grid", style: "margin-top:10px" },
      panel("Financial overview", kv([["Cash on hand", money(s.cash), "num"], ["Bank balance", money(s.bank), "num"],
        ["Inventory value (sell quote)", money(s.inventory_value), "num"], ["Net worth", money(s.net_worth), "num"]]), bankForm(s, ctx)),
      panel("Active mission", m ? h("div", {}, h("strong", {}, m.title), h("p", { class: "muted" }, m.context),
        ...m.objectives.map((o) => h("div", {}, h("span", { class: o.met ? "pos" : "" }, (o.met ? "[x] " : "[ ] ") + o.label), h("span", { class: "num muted" }, ` ${o.value}/${o.target}`))),
        (m.claimable ? h("p", { class: "pos" }, "[!] Reward ready: open the Missions tab to claim it.") : h("p", { class: "muted" }, "Track all objectives in the Missions tab.")))
        : h("p", { class: "muted" }, "No active main mission. More arrive as the story progresses.")),
      panel("Threats", h("div", { class: "row2" }, h("span", {}, "Wanted"), stars(s.wanted)), meter("Wanted heat", s.wanted, 100, "strain"),
        meter("Sanity", s.sanity, 100, "health"), meter("Health", s.condition, 100, "health"),
        h("p", { class: "muted" }, s.wanted >= 30 ? "Searches and crackdowns are now possible. Lay low or retain legal help." : "Heat is manageable.")),
      panel("Progression", kv([["Street level", s.level, "num"], ["Experience", `${s.xp}/${s.xp_next}`, "num"], ["Reputation", s.reputation, "num"]]),
        bar(s.xp - s.xp_floor, Math.max(1, s.xp_next - s.xp_floor), "Progress to next level"),
        h("p", { class: "muted" }, "Higher levels raise storage and unlock new market tiers and contacts."))));
  // opening the Overview counts as reading the news
  if (unreadIds.length) {
    try { await api("/api/events/ack", { method: "POST", body: { upto: Math.max(...unreadIds) } }); s.unread_events = 0; if (ctx.repaint) ctx.repaint(); } catch { /* next time */ }
  }
}

const CH_TITLE = { 1: "Chapter 1: First Steps", 2: "Chapter 2: Local Reputation", 0: "Side activities" };
const rewardText = (r) => Object.entries(r).map(([k, v]) => (k === "cash" ? "$" + v : `${v} ${k}`)).join(", ");

export async function renderMissions(box, ctx) {
  const { missions } = await api("/api/missions");
  const open = missions.filter((m) => m.status === "available"); // locked missions stay hidden until they unlock
  const done = missions.filter((m) => m.status === "completed");
  const card = (m) => h("div", { class: "card" },
    h("div", {}, h("strong", {}, m.title), " ", m.claimable ? h("span", { class: "badge pos" }, "READY") : null),
    h("div", { class: "muted" }, m.context),
    ...m.objectives.map((o) => h("div", {}, h("span", { class: o.met ? "pos" : "" }, (o.met ? "[x] " : "[ ] ") + o.label), h("span", { class: "num muted" }, ` ${o.value}/${o.target}`))),
    h("div", { class: "num" }, "Reward: " + rewardText(m.rewards)),
    m.claimable ? h("button", { class: "primary", onclick: () => run(ctx, async () => {
      const r = await api(`/api/missions/${m.id}/claim`, { method: "POST", body: {} }); ctx.say("Mission complete: " + r.effects_text, false); }) }, "Claim reward") : null);
  const group = (title, list) => (list.length ? h("div", {}, h("h3", { class: "grp" }, title), h("div", { class: "cards" }, list.map(card))) : null);
  const parts = [group("Ready to claim", open.filter((m) => m.claimable)),
    ...[1, 2, 0].map((c) => group(CH_TITLE[c], open.filter((m) => !m.claimable && m.chapter === c)))];
  box.replaceChildren(panel("Missions",
    open.length ? null : h("p", { class: "muted" }, "No missions available right now. New ones appear as you progress."), ...parts,
    done.length ? h("details", { class: "done" }, h("summary", {}, `Completed (${done.length})`), h("ul", {}, done.map((m) => h("li", {}, m.title)))) : null));
}

export async function renderContacts(box, ctx) {
  const d = await api("/api/contacts");
  const contactCard = (c) => h("div", { class: "card" },
    h("div", {}, h("strong", {}, c.name), " ", h("span", { class: "muted" }, c.faction)), h("div", { class: "muted" }, c.profile),
    h("div", { class: "num" }, `Prefers ${c.prefers} | orders ${c.order} | negotiation ${c.difficulty}/5 | reliability ${Math.round(c.reliability * 100)}% | relationship ${c.score}`));
  const lockedCard = (x) => h("div", { class: "card" }, h("strong", {}, x.name || x.title), h("div", { class: "warn" }, x.locked_reason || "Locked"));
  const contractCard = (c) => h("div", { class: "card" },
    h("div", {}, h("strong", {}, c.title), " ", h("span", { class: "muted" }, "for " + c.contact), " ", h("span", { class: "badge" }, c.status.toUpperCase())),
    h("div", { class: "muted" }, c.text),
    h("div", { class: "num" }, `Deliver ${c.qty} x ${c.item} | reward ${money(c.reward)} | +${c.rep_reward} rep (miss: -${c.rep_penalty}) | ${c.days} cycles` + (c.deadline != null ? ` | due cycle ${c.deadline}` : "")),
    c.status === "offered" ? h("button", { onclick: () => run(ctx, async () => { await api(`/api/contracts/${c.id}/accept`, { method: "POST", body: {} }); ctx.say("Contract accepted.", false); }) }, "Accept") : null,
    c.status === "active" ? h("div", { class: "row" }, h("span", { class: c.held >= c.qty ? "pos" : "warn" }, `You hold ${c.held}/${c.qty} at this stash`),
      h("button", { class: "primary", disabled: c.held < c.qty, onclick: () => run(ctx, async () => { const r = await api(`/api/contracts/${c.id}/fulfill`, { method: "POST", body: {} }); ctx.say("Delivered: " + r.effects_text, false); }) }, "Deliver")) : null);
  const drop = (title, list, card) => (list.length ? h("details", { class: "done" }, h("summary", {}, `${title} (${list.length})`), h("div", { class: "cards", style: "margin-top:8px" }, list.map(card))) : null);
  const avail = d.contacts.filter((c) => c.available), live = d.contracts.filter((c) => c.status === "active" || c.status === "offered");
  box.replaceChildren(h("div", { class: "grid" },
    panel("Contacts", avail.length ? h("div", { class: "cards" }, avail.map(contactCard)) : h("p", { class: "muted" }, "Nobody is talking to you yet."),
      drop("Locked contacts", d.contacts.filter((c) => !c.available), lockedCard)),
    panel("Contracts", live.length ? h("div", { class: "cards" }, live.map(contractCard)) : h("p", { class: "muted" }, "No open contracts right now."),
      drop("Locked contracts", d.contracts.filter((c) => c.status === "locked"), lockedCard),
      drop("Finished contracts", d.contracts.filter((c) => c.status === "completed" || c.status === "failed"), contractCard))));
}

export async function renderActions(box, ctx) {
  const { actions } = await api("/api/actions");
  const vis = actions.filter((a) => !a.hidden); // hide level-locked and situational actions
  const card = (a) => {
    const btn = h("button", { class: "primary", disabled: !a.available, title: a.reason || "", onclick: () => {
      if (a.confirm && ctx.settings.confirm_expensive && btn.dataset.armed !== "1") { btn.dataset.armed = "1"; btn.textContent = `Confirm (${money(a.cost)})`; setTimeout(() => { btn.dataset.armed = ""; btn.textContent = "Do it"; }, 4000); return; }
      run(ctx, async () => { const r = await api(`/api/actions/${a.id}`, { method: "POST", body: { key: crypto.randomUUID() } }); ctx.say(`${a.label}: ${r.effects_text}`, false); });
    } }, "Do it");
    return h("div", { class: "card" },
      h("div", {}, h("strong", {}, a.label), " ", h("span", { class: "num" }, `cost ${money(a.cost)}`)), h("div", { class: "muted" }, a.desc),
      h("div", { class: "num" }, "Effect: " + a.effects + (a.cooldown ? ` | cooldown ${a.cooldown} cycle(s)` : "")),
      a.reason ? h("div", { class: "warn" }, a.reason) : null, btn);
  };
  const groups = [...new Set(vis.map((a) => a.group))];
  box.replaceChildren(panel("Actions", vis.length
    ? groups.map((g) => h("div", {}, h("h3", { class: "grp" }, g), h("div", { class: "cards" }, vis.filter((a) => a.group === g).map(card))))
    : h("p", { class: "muted" }, "No actions available right now.")));
}
