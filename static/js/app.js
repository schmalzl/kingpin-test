import { api, setCsrf, withAuto } from "./api.js";
import { h, panel, kv, money, meter, miniMeter, stars } from "./ui.js";
import { icon } from "./icons.js";
import { renderAdmin } from "./admin.js";
import { renderMarket } from "./market.js";
import { renderInventory } from "./inventory.js";
import { renderSettings, applyUI } from "./settings.js";
import { renderSaves } from "./saves.js";
import { renderOverview, renderMissions, renderContacts, renderActions } from "./world.js";
import { renderStats, renderLeaderboard, boardTable } from "./board.js";
import { renderShop } from "./shop.js";

const app = document.getElementById("app");
const NAV = [["Overview", 1], ["Market", 1], ["Inventory", 1], ["Shop", 1], ["Actions", 1], ["Locations", 2], ["Laboratory", 8],
  ["Businesses", 4], ["Missions", 1], ["Contacts", 1], ["Statistics", 1], ["Leaderboard", 1], ["Save / Load", 1], ["Settings", 1]];
const NAV_ICON = { Overview: "eye", Market: "chart", Inventory: "box", Shop: "bag", Actions: "bolt", Locations: "pin", Laboratory: "flask", Businesses: "building",
  Missions: "target", Contacts: "user", Statistics: "bars", Leaderboard: "trophy", "Save / Load": "disk", Settings: "gear" };
let stopPlayer = null; // stops the background refresh of the player view when leaving it
let idleStop = null;   // stops the inactivity watcher

/** Signs the user out after `idleMinutes` without input, and sends a heartbeat while they are active. */
function startIdleWatch(idleMinutes) {
  if (idleStop) idleStop();
  const limit = idleMinutes * 60000, evs = ["mousemove", "keydown", "click", "touchstart", "scroll", "wheel"];
  let last = Date.now(), lastPing = 0;
  const mark = () => { last = Date.now(); };
  evs.forEach((e) => window.addEventListener(e, mark, { passive: true }));
  const timer = setInterval(async () => {
    const now = Date.now();
    if (now - last > limit) {
      if (idleStop) idleStop();
      try { await api("/api/logout", { method: "POST" }); } catch { /* already gone */ }
      return loginView("You were signed out because of inactivity.");
    }
    if (now - last < 60000 && now - lastPing > 60000) {
      lastPing = now;
      try { await api("/api/ping", { method: "POST", body: {} }); } catch (e) { if (e.status === 401) { if (idleStop) idleStop(); loginView(e.message); } }
    }
  }, 10000);
  idleStop = () => { evs.forEach((e) => window.removeEventListener(e, mark)); clearInterval(timer); idleStop = null; };
}

async function loadMeta() {
  try {
    const m = await api("/api/meta"), f = document.getElementById("footer");
    f.replaceChildren(h("div", {}, m.version), h("div", {}, m.copyright));
  } catch { /* footer is optional */ }
}

async function loadAnnouncement(box) {
  try {
    const a = await api("/api/announcement");
    box.replaceChildren(panel("Announcement", a.message
      ? [h("p", { class: "announce" }, a.message), h("div", { class: "muted" }, "Posted by administration on " + new Date(a.posted_at).toLocaleString())]
      : h("p", { class: "muted" }, "No announcements at the moment.")));
  } catch { box.replaceChildren(); }
}
async function loadBoard(box) {
  try { const d = await api("/api/leaderboard?limit=10"); box.replaceChildren(panel("Leaderboard (top 10)", boardTable(d.entries))); } catch { box.replaceChildren(); }
}

function loginView(note = "") {
  if (stopPlayer) { stopPlayer(); stopPlayer = null; }
  if (idleStop) idleStop();
  document.title = "KINGPIN";
  let role = "player";
  const err = h("div", { class: "err", role: "alert" }, note);
  const user = h("input", { id: "u", autocomplete: "username", required: true });
  const sec = h("input", { id: "s", type: "password", autocomplete: "current-password", required: true });
  const secLabel = h("label", { for: "s" }, "PIN");
  const tabs = ["player", "admin"].map((r) => h("button", { type: "button", role: "tab", "aria-selected": String(r === role),
    onclick: () => { role = r; tabs.forEach((b, i) => b.setAttribute("aria-selected", String(["player", "admin"][i] === r)));
      secLabel.textContent = r === "admin" ? "Password" : "PIN"; } }, r === "admin" ? "Administrator" : "Player"));
  const form = h("form", { onsubmit: async (e) => {
    e.preventDefault(); err.textContent = "";
    try { const s = await api("/api/login", { method: "POST", body: { username: user.value, secret: sec.value, role } });
      setCsrf(s.csrf); sec.value = ""; await boot(); }
    catch (x) { err.textContent = x.message; sec.value = ""; }
  } }, h("label", { for: "u" }, "Username", user), secLabel, sec, err, h("button", { class: "primary" }, "Sign in"));
  const annBox = h("div"), boardBox = h("div", { style: "margin-top:10px" });
  app.replaceChildren(h("main", { class: "loginwrap" },
    h("div", { class: "login" },
      h("div", { class: "wordmark", style: "font-size:26px" }, "KINGPIN"),
      h("div", { class: "tabs", role: "tablist" }, tabs), form,
      h("aside", { class: "access" },
        h("p", {}, "Kingpin is invite-only. To request access, contact ", h("a", { href: "mailto:kingpin.game@proton.me" }, "kingpin.game@proton.me"), "."),
        h("p", {}, h("strong", {}, "Note:"), " When contacting administration, please state the following information in your email:"),
        h("ol", {}, h("li", {}, "Your Name (Will be used as a username/character name - shown on leaderboard)"),
          h("li", {}, "Desired account PIN (must be at least 6 digits)")),
        h("p", { class: "warn", style: "margin-top:8px" }, icon("lock"), " Gameplay only optimised for Tablet/PC"))),
    h("div", {}, annBox, boardBox)));
  loadAnnouncement(annBox); loadBoard(boardBox);
}

function changeView(session) {
  const isAdmin = session.role === "admin";
  const cur = h("input", { id: "cp", type: "password", autocomplete: "current-password", required: true });
  const nw = h("input", { id: "np", type: "password", autocomplete: "new-password", required: true });
  const rep = h("input", { id: "rp", type: "password", autocomplete: "new-password", required: true });
  const err = h("div", { class: "err", role: "alert" });
  app.replaceChildren(h("main", { class: "login" }, h("div", { class: "wordmark", style: "font-size:22px;margin-bottom:10px" }, "KINGPIN"),
    h("form", { onsubmit: async (e) => { e.preventDefault(); err.textContent = "";
      if (nw.value !== rep.value) { err.textContent = "The new credential and its repetition do not match."; return; }
      try { await api("/api/change-secret", { method: "POST", body: { current: cur.value, new: nw.value } }); await boot(); }
      catch (x) { err.textContent = x.message; } } },
      h("p", {}, isAdmin ? "First login: choose your own password (at least 12 characters)." : "First login: choose your own PIN."),
      h("label", { for: "cp" }, isAdmin ? "Current password (the one you just signed in with)" : "Current PIN (the one you just signed in with)", cur),
      h("label", { for: "np" }, isAdmin ? "NEW password" : "NEW PIN", nw),
      h("label", { for: "rp" }, "Repeat the NEW " + (isAdmin ? "password" : "PIN"), rep),
      err, h("button", { class: "primary" }, "Save and continue"))));
}

function topbar(session, extra = []) {
  return h("header", { class: "topbar" }, h("span", { class: "wordmark" }, "KINGPIN"), ...extra, h("span", { class: "spacer" }),
    h("span", { class: "chip" }, session.username), h("button", { onclick: async () => { await api("/api/logout", { method: "POST" }); loginView(); } }, "Sign out"));
}

async function playerView(session) {
  const ctx = { selected: null, tab: "Overview", say: () => {}, settings: { confirm_expensive: true }, marketTimer: null };
  const toast = h("div", { class: "toast", role: "status" });
  ctx.say = (t, bad) => { toast.className = "toast " + (bad ? "neg" : "pos"); toast.textContent = t; };
  const top = h("header", { class: "topbar" });
  const nav = h("nav", { class: "main", "aria-label": "Primary" });
  const side = h("aside", { class: "side", "aria-label": "Player status" });
  const main = h("div", { class: "content" });
  let s;
  const IMPL = { Overview: 1, Market: 1, Inventory: 1, Shop: 1, Actions: 1, Missions: 1, Contacts: 1, Statistics: 1, Leaderboard: 1, "Save / Load": 1, Settings: 1 };

  // ---- real-time clock: 1 cycle = 2 real minutes; the server is the only authority ----
  const dayChip = h("span", { class: "chip num", title: "A new cycle starts every 2 real minutes. The market moves with it, even while you are away." });
  let nextAt = 0, busy = false, clockTimer = null, pollTimer = null, requested = false;
  function setClock() { nextAt = Date.now() + s.next_day_in_ms; requested = false; paintClock(); }
  function paintClock() {
    const rem = Math.max(0, nextAt - Date.now()), m = Math.floor(rem / 60000), sec = Math.floor((rem % 60000) / 1000);
    dayChip.textContent = `NEXT CYCLE IN ${m}:${String(sec).padStart(2, "0")}`;
    if (rem === 0 && !requested) { requested = true; setTimeout(() => auto(), 1500); }
  }

  function drawTop() {
    const unread = s.unread_events, pend = s.pending_events;
    const bell = h("button", { class: "bell" + (unread || pend ? " on" : ""), title: "Open the news on the Overview tab",
      "aria-label": `News: ${unread} unread, ${pend} waiting for a decision`, onclick: () => { ctx.tab = "Overview"; draw(); } },
      icon("bell"), ` NEWS ${unread}` + (pend ? ` · ${pend} DECISION${pend > 1 ? "S" : ""}` : ""));
    top.replaceChildren(h("span", { class: "wordmark" }, "KINGPIN"), h("span", { class: "chip" }, icon("pin"), " " + s.location.replace(/_/g, " ").toUpperCase()), dayChip,
      h("span", { class: "spacer" }), bell, h("span", { class: "chip" }, icon("mask"), " " + session.username),
      h("button", { onclick: async () => { await api("/api/logout", { method: "POST" }); loginView(); } }, "Sign out"),
      h("span", { class: "chip season", title: "Season, current cycle and days (real-life days since the season began)" },
        icon("calendar"), ` ${s.season.name.toUpperCase()} · CYCLE ${s.day} · DAY ${s.season.real_day}`));
    document.title = unread ? `(${unread}) KINGPIN` : "KINGPIN";
  }

  function needsLine() {
    const n = s.needs, note = h("p", { class: "muted", hidden: true }, n.explain);
    const hint = h("button", { class: "hint", title: n.explain, "aria-label": "Why am I losing this? " + n.explain, onclick: () => { note.hidden = !note.hidden; } }, "?");
    const dmg = [n.health_loss ? `health -${n.health_loss}` : "", n.sanity_loss ? `sanity -${n.sanity_loss}` : ""].filter(Boolean).join(", ");
    return h("div", {}, h("div", { class: "muted needs" }, `Losing ${n.hydration} hydration and ${n.nutrition} nutrition per cycle`, " ", hint),
      dmg ? h("div", { class: "neg needs" }, `Starving or dehydrated: ${dmg} per cycle`) : null, note);
  }
  function drawSide() {
    const xpSpan = Math.max(1, s.xp_next - s.xp_floor);
    side.replaceChildren(panel("Operator",
      h("div", { class: "row2" }, h("strong", {}, session.username), h("span", { class: "chip num" }, "LEVEL " + s.level)),
      h("div", { class: "sect" }, icon("dollar"), " Money"),
      h("div", { class: "big num pos", title: "Cash on hand" }, money(s.cash)),
      kv([["Bank", money(s.bank), "num"], ["Net worth", money(s.net_worth), "num"]]),
      h("div", { class: "sect" }, icon("heart"), " Condition"),
      meter("Health", s.condition, 100, "health"),
      meter("Sanity", s.sanity, 100, "health"),
      h("div", { class: "duo" }, miniMeter("Hydration", s.hydration), miniMeter("Nutrition", s.nutrition)),
      needsLine(),
      h("div", { class: "sect" }, icon("shield"), " Wanted"),
      h("div", { class: "row2" }, stars(s.wanted), h("span", { class: "num " + (s.wanted >= 40 ? "warn" : "") }, `${s.wanted}/100`)),
      h("div", { class: "sect" }, icon("bars"), " Progress"),
      meter("Experience", s.xp - s.xp_floor, xpSpan, "info", ` (total ${s.xp})`),
      meter("Storage", s.storage_used, s.capacity, "info"),
      kv([["Reputation", s.reputation, "num"], ["Cycle", s.day, "num"]])));
  }
  function drawNav() {
    nav.replaceChildren(...NAV.map(([n, lvl]) => {
      const locked = s.level < lvl, todo = !IMPL[n];
      const badge = n === "Overview" && s.pending_events ? ` (${s.pending_events}!)` : "";
      const ready = n === "Missions" ? s.claimable_missions : 0;
      return h("button", { class: locked || todo ? "locked" : "", "aria-current": n === ctx.tab ? "page" : null, disabled: locked || todo,
        "aria-label": ready ? `Missions, ${ready} reward${ready > 1 ? "s" : ""} ready to claim` : null,
        title: locked ? `Unlocks at street level ${lvl}` : todo ? "Not implemented yet" : ready ? `${ready} reward(s) ready to claim` : "", onclick: () => { ctx.tab = n; draw(); } },
        icon(NAV_ICON[n]), " " + n + (locked ? ` (L${lvl})` : todo ? " (soon)" : badge), ready ? h("span", { class: "dot", "aria-hidden": "true" }, ready) : null);
    }));
  }
  async function renderTab() {
    if (ctx.marketTimer && ctx.tab !== "Market") { clearInterval(ctx.marketTimer); ctx.marketTimer = null; }
    if (ctx.tab === "Market") await renderMarket(main, ctx);
    else if (ctx.tab === "Inventory") await renderInventory(main);
    else if (ctx.tab === "Shop") await renderShop(main, ctx);
    else if (ctx.tab === "Statistics") await renderStats(main);
    else if (ctx.tab === "Leaderboard") await renderLeaderboard(main, ctx, session.username);
    else if (ctx.tab === "Save / Load") await renderSaves(main, ctx);
    else if (ctx.tab === "Settings") await renderSettings(main, ctx);
    else if (ctx.tab === "Actions") await renderActions(main, ctx);
    else if (ctx.tab === "Missions") await renderMissions(main, ctx);
    else if (ctx.tab === "Contacts") await renderContacts(main, ctx);
    else await renderOverview(main, s, ctx);
  }
  async function draw() {
    try {
      const { state } = await api("/api/state"); s = state;
      drawSide(); drawNav(); drawTop(); setClock();
      await renderTab();
    } catch (e) { if (e.status === 401) return loginView(e.message); ctx.say(e.message, true); }
  }
  // Automatic refresh (every 15 s and when a new cycle starts). It does not count as activity, so idle sessions still expire.
  async function auto() {
    if (busy || !s) return;
    busy = true;
    try {
      await withAuto(async () => {
        const prev = s.day;
        const { state } = await api("/api/state"); s = state;
        drawSide(); drawNav(); drawTop(); setClock();
        if (s.day !== prev && ["Overview", "Inventory", "Statistics", "Leaderboard"].includes(ctx.tab)) await renderTab();
      });
    } catch (e) { if (e.status === 401) loginView(e.message); }
    finally { busy = false; }
  }
  ctx.refresh = draw;
  ctx.repaint = () => { if (s) { drawTop(); drawNav(); } };
  app.replaceChildren(h("div", {}, top, nav, h("div", { class: "shell" }, h("div", { class: "sidecol" }, side), h("div", {}, toast, main))));
  try { ctx.settings = (await api("/api/settings")).settings; applyUI(ctx.settings); } catch { /* defaults */ }
  await draw();
  clockTimer = setInterval(() => { if (s) paintClock(); }, 1000);
  pollTimer = setInterval(auto, 15000);
  stopPlayer = () => { clearInterval(clockTimer); clearInterval(pollTimer); if (ctx.marketTimer) clearInterval(ctx.marketTimer); };
}

async function boot() {
  let session;
  try { session = await api("/api/me"); } catch (e) { return loginView(e.code ? e.message : ""); }
  setCsrf(session.csrf);
  if (session.must_change) return changeView(session);
  startIdleWatch(session.idle_minutes || 15);
  if (session.role === "admin") {
    app.replaceChildren(topbar(session, [h("span", { class: "chip" }, "ADMINISTRATION")]));
    return renderAdmin(app, session);
  }
  try { await playerView(session); } catch (e) { loginView(e.message); }
}
loadMeta();
boot();
