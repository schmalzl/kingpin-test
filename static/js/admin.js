import { api } from "./api.js";
import { h, panel, money } from "./ui.js";

const TABS = ["Players", "Items", "Market", "Announcements", "Season", "Log"];
const LABEL = { kick: "Kick", suspend: "Suspend", ban: "Ban", reset: "Reset campaign", delete: "Delete account" };
const PERKS = [["capacity", "Storage +N"], ["sell_bonus_pct", "Sell prices +N%"], ["heat_shield_pct", "Police attention from sales -N%"],
  ["search_loss_reduction_pct", "Seizures in searches -N%"], ["xp_bonus_pct", "Experience +N%"]];
const EFFECTS = [["sanity", "Sanity"], ["condition", "Health"], ["hydration", "Hydration"], ["nutrition", "Nutrition"], ["xp", "XP"], ["rep", "Reputation"], ["wanted", "Wanted"]];
const PREVIEW = {
  ban: (r) => `Your account has been banned.${r ? ` Reason: ${r.replace(/\.$/, "")}.` : ""} To appeal ban/suspension, please contact admin.`,
  suspend: (r, hrs) => `Your account is suspended for ${hrs || "?"} hours.${r ? ` Reason: ${r.replace(/\.$/, "")}.` : ""} To appeal ban/suspension, please contact admin.`,
};
const fmt = (t) => (t ? new Date(t).toLocaleString() : "never");

export async function renderAdmin(root, session) {
  const msg = h("div", { role: "status" });
  const say = (t, bad) => { msg.className = bad ? "err" : "ok"; msg.textContent = t; };
  const fail = (e) => say(e.message, true);
  const nav = h("nav", { class: "main", "aria-label": "Admin sections" });
  const body = h("div", { class: "content" });
  let tab = "Players";

  /** Two-step button: first click arms it, second click runs fn. */
  const armed = (label, cls, fn) => {
    let on = false, timer;
    const b = h("button", { class: cls, onclick: async () => {
      if (!on) { on = true; b.textContent = "Click again to confirm"; timer = setTimeout(() => { on = false; b.textContent = label; }, 4000); return; }
      clearTimeout(timer); on = false; b.textContent = label;
      try { await fn(); } catch (e) { fail(e); }
    } }, label);
    return b;
  };
  const select = (opts, id) => h("select", { id }, opts.map(([v, t]) => h("option", { value: v }, t)));

  // ------------------------------------------------------------ Players
  async function playersTab() {
    const usersBox = h("div"), editBox = h("div");
    const search = h("input", { type: "search", placeholder: "Search username", "aria-label": "Search players", oninput: () => refresh() });
    async function refresh() {
      const { users } = await api("/api/admin/users?q=" + encodeURIComponent(search.value));
      usersBox.replaceChildren(users.length ? h("table", {},
        h("thead", {}, h("tr", {}, ...["User", "Status", "Lvl", "Cash", "Bank", "Last login", "Actions"].map((c) => h("th", {}, c)))),
        h("tbody", {}, users.map((u) => h("tr", {}, h("td", {}, u.username),
          h("td", { title: u.status_reason || "" }, h("span", { class: "badge " + (u.status === "active" ? "pos" : "neg") }, u.status.toUpperCase()),
            u.status !== "active" && u.status_reason ? h("div", { class: "muted" }, u.status_reason) : null),
          h("td", { class: "num" }, u.level ?? "-"), h("td", { class: "num" }, money(u.cash ?? 0)), h("td", { class: "num" }, money(u.bank ?? 0)), h("td", { class: "num" }, fmt(u.last_login)),
          h("td", { class: "btns" }, h("button", { class: "primary", onclick: () => edit(u) }, "Edit state"),
            ...["kick", "suspend", "ban"].map((a) => h("button", { onclick: () => actionForm(u, a) }, LABEL[a])),
            h("button", { onclick: () => unban(u) }, "Unban"), h("button", { onclick: () => actionForm(u, "reset") }, "Reset"),
            h("button", { class: "danger", onclick: () => actionForm(u, "delete") }, "Delete"))))))
        : h("p", { class: "muted" }, "No players match. Create one above."));
    }
    async function unban(u) { try { await api(`/api/admin/users/${u.id}/action`, { method: "POST", body: { action: "unban" } }); say(`${u.username} is active again.`); await refresh(); } catch (e) { fail(e); } }
    function actionForm(u, action) {
      const reason = h("textarea", { id: "ar", rows: 2, maxlength: 300, placeholder: "Reason shown to the player (optional)" });
      const hours = h("input", { id: "ah", type: "number", min: 1, max: 8760, value: 24 });
      const typed = h("input", { id: "at", placeholder: `Type ${u.username} to confirm`, autocomplete: "off" });
      const preview = h("p", { class: "muted" });
      const showReason = action === "ban" || action === "suspend";
      const upd = () => { if (showReason) preview.textContent = "The player will see: " + PREVIEW[action](reason.value.trim(), hours.value); };
      reason.addEventListener("input", upd); hours.addEventListener("input", upd); upd();
      const warn = { kick: "Ends the session. The player sees \"Kicked by administrator.\" (no custom reason).", reset: "Resets this player's campaign to the starting state. Cannot be undone.",
        delete: "Permanently removes the account and all of its data from the player list. Cannot be undone." }[action];
      const go = armed(LABEL[action], "danger", async () => {
        const b = { action, confirm: true };
        if (showReason) b.reason = reason.value;
        if (action === "suspend") b.hours = Number(hours.value);
        if (action === "delete") b.confirm_name = typed.value;
        await api(`/api/admin/users/${u.id}/action`, { method: "POST", body: b }); say(`${LABEL[action]}: ${u.username}`); editBox.replaceChildren(); await refresh();
      });
      editBox.replaceChildren(panel(`${LABEL[action]}: ${u.username}`, warn ? h("p", { class: "warn" }, warn) : null,
        action === "suspend" ? h("label", { for: "ah" }, "Duration in hours", hours) : null, showReason ? h("label", { for: "ar" }, "Reason", reason) : null, showReason ? preview : null,
        action === "delete" ? h("label", { for: "at" }, "Confirmation", typed) : null,
        h("div", { class: "row", style: "margin-top:8px" }, go, h("button", { onclick: () => editBox.replaceChildren() }, "Cancel"))));
    }
    async function edit(u) {
      const { state: st } = await api(`/api/admin/users/${u.id}/state`);
      const field = select([["cash", "Cash"], ["bank", "Bank"], ["level", "Level (resets XP to level start)"], ["reputation", "Reputation"]], "af");
      const mode = select([["add", "Add"], ["remove", "Remove"], ["set", "Set to exact value"]], "am");
      const amount = h("input", { id: "aa", type: "number", min: 0, step: 1, value: 100 });
      const note = h("input", { id: "an", placeholder: "Reason (optional, goes to audit log)", maxlength: 200 });
      const confirmBtn = h("button", { class: "danger", hidden: true, onclick: () => { confirmBtn.hidden = true; apply(); } }, "Confirm remove / set");
      const apply = async () => {
        try { const r = await api(`/api/admin/users/${u.id}/adjust`, { method: "POST", body: { field: field.value, mode: mode.value, amount: Number(amount.value), note: note.value, confirm: true } });
          say(`${u.username}: ${r.field} ${r.before} -> ${r.after}`); await refresh(); await edit(u); } catch (e) { fail(e); }
      };
      editBox.replaceChildren(panel(`Edit ${u.username}`,
        h("p", { class: "num" }, `Level ${st.level} | XP ${st.xp} | Cash ${money(st.cash)} | Bank ${money(st.bank)} | Reputation ${st.reputation} | Wanted ${st.wanted}`),
        h("div", { class: "row" }, h("label", { for: "af" }, "Field", field), h("label", { for: "am" }, "Action", mode), h("label", { for: "aa" }, "Amount", amount), h("label", { for: "an" }, "Note", note),
          h("button", { class: "primary", onclick: () => { if (mode.value === "add") return apply(); if (!confirmBtn.hidden) return; confirmBtn.hidden = false; } }, "Apply"), confirmBtn),
        h("p", { class: "muted" }, "Changes run on the server, are audited and (for cash) written to the player's ledger.")));
    }
    const un = h("input", { id: "nu", autocomplete: "off" }), pin = h("input", { id: "np", type: "password", autocomplete: "new-password", inputmode: "numeric" });
    const create = h("form", { class: "row", onsubmit: async (e) => {
      e.preventDefault();
      try { await api("/api/admin/users", { method: "POST", body: { username: un.value, pin: pin.value } }); say("Player created."); un.value = pin.value = ""; await refresh(); } catch (err) { fail(err); }
    } }, h("label", {}, "Username", un), h("label", {}, "PIN (at least 6 digits)", pin), h("button", { class: "primary" }, "Create player"));
    await refresh();
    return h("div", {}, panel("New player", create), h("div", { style: "margin-top:10px" }, panel("Players", search, usersBox)), h("div", { style: "margin-top:10px" }, editBox));
  }

  // ------------------------------------------------------------ Items (season specials)
  async function itemsTab() {
    const listBox = h("div");
    const name = h("input", { id: "in", maxlength: 40 }), desc = h("input", { id: "id", maxlength: 200 });
    const price = h("input", { id: "ip", type: "number", min: 0, value: 250 }), lvl = h("input", { id: "il", type: "number", min: 1, max: 15, value: 1 }), max = h("input", { id: "im", type: "number", min: 0, max: 99, value: 1 });
    const perk = select([["", "(no perk)"], ...PERKS], "ipk"), perkV = h("input", { id: "ipv", type: "number", min: 1, value: 5 });
    const eff = select([["", "(no instant effect)"], ...EFFECTS], "ie"), effV = h("input", { id: "iev", type: "number", value: 10 });
    async function refresh() {
      const { specials } = await api("/api/admin/specials");
      listBox.replaceChildren(specials.length ? h("table", {}, h("thead", {}, h("tr", {}, ...["Name", "Price", "Level", "Limit", "Effects", ""].map((c) => h("th", {}, c)))),
        h("tbody", {}, specials.map((s) => h("tr", {}, h("td", {}, s.name), h("td", { class: "num" }, money(s.price)), h("td", { class: "num" }, s.min_level),
          h("td", { class: "num" }, s.max_per_player || "unlimited"), h("td", {}, s.text),
          h("td", {}, armed("Remove", "danger", async () => { await api(`/api/admin/specials/${s.id}/delete`, { method: "POST", body: {} }); say("Item removed."); await refresh(); })))))) : h("p", { class: "muted" }, "No season specials yet."));
    }
    const add = h("button", { class: "primary", onclick: async () => {
      try { await api("/api/admin/specials", { method: "POST", body: { name: name.value, description: desc.value, price: Number(price.value), min_level: Number(lvl.value), max_per_player: Number(max.value),
        perk: perk.value || null, perk_value: perk.value ? Number(perkV.value) : null, effect: eff.value || null, effect_value: eff.value ? Number(effV.value) : null } });
        say("Season special added. Players find it in the Shop tab."); name.value = desc.value = ""; await refresh(); } catch (e) { fail(e); } } }, "Add item");
    await refresh();
    return h("div", { class: "grid" }, panel("New season special", h("p", { class: "muted" }, "Appears in the Shop tab under \"Season Specials\" and disappears when a new season starts."),
      h("label", { for: "in" }, "Name", name), h("label", { for: "id" }, "Description", desc),
      h("div", { class: "row" }, h("label", { for: "ip" }, "Price ($)", price), h("label", { for: "il" }, "Minimum level", lvl), h("label", { for: "im" }, "Max per player (0 = unlimited)", max)),
      h("div", { class: "row" }, h("label", { for: "ipk" }, "Permanent perk", perk), h("label", { for: "ipv" }, "Perk value N", perkV)),
      h("div", { class: "row" }, h("label", { for: "ie" }, "Instant effect", eff), h("label", { for: "iev" }, "Effect value (negative = harm)", effV)),
      h("div", { style: "margin-top:8px" }, add)), panel("Current season specials", listBox));
  }

  // ------------------------------------------------------------ Market
  async function marketTab() {
    const st = await api("/api/admin/market");
    const form = (title, action, factor, cycles, needItem, hint, label) => {
      const item = needItem ? select(st.items.map((i) => [i.id, i.name])) : null;
      const f = h("input", { type: "number", step: "0.05", value: factor }), c = h("input", { type: "number", min: 1, max: 500, value: cycles });
      return panel(title, h("p", { class: "muted" }, hint), item ? h("label", {}, "Item", item) : null,
        h("div", { class: "row" }, h("label", {}, "Price multiplier", f), h("label", {}, "Cycles", c)),
        h("div", { style: "margin-top:8px" }, armed(label, "danger", async () => {
          await api("/api/admin/market", { method: "POST", body: { action, item_id: item ? item.value : null, factor: Number(f.value), cycles: Number(c.value), confirm: true } });
          say(`${label}: done.`); await show(); })));
    };
    const mods = st.mods.length ? h("table", {}, h("thead", {}, h("tr", {}, ...["Target", "Multiplier", "Until cycle", ""].map((x) => h("th", {}, x)))),
      h("tbody", {}, st.mods.map((m) => h("tr", {}, h("td", {}, m.target), h("td", { class: "num" }, "x" + m.factor), h("td", { class: "num" }, m.expires_day),
        h("td", {}, h("button", { onclick: async () => { try { await api(`/api/admin/market/${m.id}/end`, { method: "POST", body: {} }); say("Ended."); await show(); } catch (e) { fail(e); } } }, "End")))))) : h("p", { class: "muted" }, "Nothing active.");
    return h("div", {}, h("div", { class: "grid" },
      form("Price pump", "surge", 1.6, 10, true, "Sudden price increase on one item (multiplier 1.05 to 5).", "Pump price"),
      form("Rug pull", "rug_pull", 0.15, 30, true, "The price collapses far below its normal floor and stays there (multiplier 0.05 to 0.6).", "Rug pull"),
      form("Market crash", "crash", 0.4, 10, false, "Every price plummets for the chosen number of cycles (multiplier 0.1 to 0.9).", "Crash the market")),
      h("div", { style: "margin-top:10px" }, panel("Active price events (including random ones)", mods,
        h("div", { style: "margin-top:8px" }, armed("End all", "danger", async () => { await api("/api/admin/market", { method: "POST", body: { action: "clear", confirm: true } }); say("All price events ended."); await show(); })))),
      h("p", { class: "muted" }, "Players are told about pumps, rug pulls and crashes in their news feed. Prices change immediately."));
  }

  // ------------------------------------------------------------ Announcements + login screen
  async function announcementsTab() {
    const annText = h("textarea", { id: "ann", rows: 4, maxlength: 1000, "aria-label": "Announcement text", placeholder: "Message shown to every visitor on the login screen (max 1000 characters)" });
    const annInfo = h("p", { class: "muted" });
    const a = await api("/api/announcement");
    annInfo.textContent = a.message ? `Currently shown (posted ${new Date(a.posted_at).toLocaleString()}): ${a.message}` : "No announcement is shown right now.";
    const meta = await api("/api/meta");
    const maskBox = h("input", { id: "mk", type: "checkbox", style: "width:auto", checked: !!meta.mask_leaderboard, onchange: async (e) => {
      try { await api("/api/admin/settings", { method: "POST", body: { mask_leaderboard: e.target.checked } }); say("Leaderboard name masking " + (e.target.checked ? "on." : "off.")); }
      catch (x) { e.target.checked = !e.target.checked; fail(x); } } });
    return h("div", { class: "grid" },
      panel("Login announcement", annInfo, h("label", { for: "ann" }, "New message (replaces the current one)", annText),
        h("div", { class: "row", style: "margin-top:8px" },
          h("button", { class: "primary", onclick: async () => { try { await api("/api/admin/announcement", { method: "POST", body: { message: annText.value } }); say("Announcement published."); await show(); } catch (e) { fail(e); } } }, "Publish"),
          armed("Remove announcement", "danger", async () => { await api("/api/admin/announcement/clear", { method: "POST", body: {} }); say("Announcement removed."); await show(); }))),
      panel("Login screen", h("label", { for: "mk", style: "display:flex;gap:8px;align-items:center" }, maskBox,
        "Mask player names on the public login leaderboard (visitors only see the first 2 characters)")));
  }

  // ------------------------------------------------------------ Season
  async function seasonTab() {
    const m = await api("/api/meta");
    const sName = h("input", { id: "sn", maxlength: 40, placeholder: "e.g. Season 2" });
    const sReset = h("input", { id: "sr", type: "checkbox", style: "width:auto" });
    return panel("Season", h("p", { class: "muted" }, `Current: ${m.season.name}, cycle ${m.season.day}, day ${m.season.real_day}`),
      h("label", { for: "sn" }, "New season name", sName),
      h("label", { for: "sr", style: "display:flex;gap:8px;align-items:center;margin-top:6px" }, sReset, "Also reset every player to the start (cash, level, stock, missions)"),
      h("p", { class: "muted" }, "A new season resets the cycle counter to 1, creates a fresh market, removes season specials and invalidates old save files."),
      armed("Start new season", "danger", async () => {
        const r = await api("/api/admin/season", { method: "POST", body: { name: sName.value, reset_players: sReset.checked, confirm: true } });
        say(`New season "${r.season.name}" started` + (r.players_reset ? `; ${r.players_reset} player(s) reset.` : ".")); await show(); }));
  }

  // ------------------------------------------------------------ Log
  async function logTab() {
    const { entries } = await api("/api/admin/audit");
    return panel("Audit log", entries.length ? h("table", {}, h("thead", {}, h("tr", {}, ...["Time", "Action", "Target", "Before", "After", "Note"].map((c) => h("th", {}, c)))),
      h("tbody", {}, entries.map((e) => h("tr", {}, h("td", { class: "num" }, e.at.slice(0, 19).replace("T", " ")), h("td", {}, e.action), h("td", { class: "num" }, (e.target_user_id || "").slice(0, 8)),
        h("td", { class: "num" }, e.before_value || ""), h("td", { class: "num" }, e.after_value || ""), h("td", {}, e.note)))))
      : h("p", { class: "muted" }, "No administrative actions recorded yet."));
  }

  const BUILD = { Players: playersTab, Items: itemsTab, Market: marketTab, Announcements: announcementsTab, Season: seasonTab, Log: logTab };
  function drawNav() { nav.replaceChildren(...TABS.map((t) => h("button", { "aria-current": t === tab ? "page" : null, onclick: () => { tab = t; msg.textContent = ""; show(); } }, t))); }
  async function show() {
    drawNav(); const keep = msg.textContent, cls = msg.className;
    body.replaceChildren(msg);
    try { body.append(await BUILD[tab]()); } catch (e) { fail(e); }
    if (keep && !msg.textContent) { msg.textContent = keep; msg.className = cls; }
  }
  root.append(nav, body);
  await show();
}
