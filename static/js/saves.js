import { api } from "./api.js";
import { h, panel, kv, money } from "./ui.js";

const MAX_BYTES = 5 * 1024 * 1024;
const when = (t) => (t ? t.slice(0, 16).replace("T", " ") + " UTC" : "");

function download(name, text) {
  const url = URL.createObjectURL(new Blob([text], { type: "application/octet-stream" }));
  const a = h("a", { href: url, download: name });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export async function renderSaves(box, ctx) {
  const { exports: list } = await api("/api/saves/exports");
  const result = h("div", { role: "status", "aria-live": "polite" });
  const file = h("input", { id: "kf", type: "file", accept: ".kgf", "aria-label": "Select .kgf save file" });

  const exportBtn = h("button", { class: "primary", onclick: async () => {
    exportBtn.disabled = true;
    try { const r = await api("/api/saves/export", { method: "POST", body: {} }); download(r.filename, r.data);
      ctx.say(`Exported ${r.filename} (cycle ${r.meta.cycle}, level ${r.meta.level}).`, false); await ctx.refresh(); }
    catch (e) { ctx.say(e.message, true); exportBtn.disabled = false; } } }, "Create and download save (.kgf)");

  file.addEventListener("change", async () => {
    result.replaceChildren();
    const f = file.files[0];
    if (!f) return;
    if (!f.name.toLowerCase().endsWith(".kgf")) { result.replaceChildren(h("p", { class: "err" }, "Please choose a .kgf file.")); return; }
    if (f.size > MAX_BYTES) { result.replaceChildren(h("p", { class: "err" }, "File is too large (maximum 5 MB).")); return; }
    let text;
    try { text = await f.text(); } catch { result.replaceChildren(h("p", { class: "err" }, "The file could not be read.")); return; }
    let r;
    try { r = await api("/api/saves/inspect", { method: "POST", body: { data: text } }); } catch (e) { result.replaceChildren(h("p", { class: "err" }, e.message)); return; }
    if (!r.compatible) { result.replaceChildren(h("p", { class: "err" }, "Rejected: " + r.error)); return; }
    const m = r.meta, c = r.current;
    let armed = false, timer;
    const go = h("button", { class: "danger", onclick: async () => {
      if (!armed) { armed = true; go.textContent = "Click again to replace my campaign"; timer = setTimeout(() => { armed = false; go.textContent = "Replace current campaign with this save"; }, 5000); return; }
      clearTimeout(timer); go.disabled = true;
      try { await api("/api/saves/import", { method: "POST", body: { data: text, confirm: true } }); ctx.say("Save restored.", false); await ctx.refresh(); }
      catch (e) { ctx.say(e.message, true); go.disabled = false; } } }, "Replace current campaign with this save");
    result.replaceChildren(h("p", { class: "pos" }, "[OK] Signature valid, belongs to your campaign, compatible with this server."),
      h("div", { class: "grid" },
        panel("Save file", kv([["Saved at", when(m.saved_at)], ["Game version", m.game_version], ["Cycle", m.cycle, "num"], ["Level", m.level, "num"], ["Cash", money(m.cash), "num"],
          ["Bank", money(m.bank), "num"], ["Reputation", m.reputation, "num"], ["Inventory units", m.inventory_units, "num"], ["Missions done", m.missions_done, "num"]])),
        panel("Your campaign now", kv([["Cycle", c.cycle, "num"], ["Level", c.level, "num"], ["Cash", money(c.cash), "num"], ["Bank", money(c.bank), "num"]]))),
      ...r.warnings.map((w) => h("p", { class: "warn" }, "[!] " + w)), go);
  });

  box.replaceChildren(h("div", { class: "grid" },
    panel("Export", h("p", {}, "Download a signed backup of your whole campaign. Your progress is also saved on the server automatically; this file is an extra backup."),
      exportBtn, h("p", { class: "muted" }, "Saves contain no passwords, PINs or other players' data. They are signed by this server and cannot be edited or used on another account.")),
    panel("Import", h("p", {}, "Choose a .kgf file made from your own campaign. You will see what it contains before anything changes."),
      h("label", { for: "kf" }, "Save file", file), result,
      h("p", { class: "muted" }, "Importing is a rollback: your campaign returns to the moment of the save. Nothing is merged. Saves made before an administrator changed your account cannot be restored.")),
    panel("Recent exports on the server", list.length ? h("table", {}, h("thead", {}, h("tr", {}, ...["Created", "Cycle", "Level", "Cash"].map((x) => h("th", {}, x)))),
      h("tbody", {}, list.slice(0, 10).map((e) => h("tr", {}, h("td", { class: "num" }, when(e.created_at)), h("td", { class: "num" }, e.cycle), h("td", { class: "num" }, e.level), h("td", { class: "num" }, money(e.cash))))))
      : h("p", { class: "muted" }, "No exports yet. The server remembers the last 50 so only genuine exports can be restored."))));
}
