import { api } from "./api.js";
import { h, panel, kv } from "./ui.js";
import { renderMarkdown } from "./md.js";

export function applyUI(s) {
  const r = document.documentElement;
  r.dataset.density = s.density; r.dataset.font = s.font_size; r.dataset.palette = s.palette;
}

export async function renderSettings(box, ctx) {
  const d = await api("/api/settings");
  let tut = ""; try { tut = (await api("/api/tutorial")).markdown; } catch { /* optional */ }
  const s = { ...d.settings };
  const save = async (patch) => {
    try { Object.assign(s, (await api("/api/settings", { method: "POST", body: patch })).settings); Object.assign(ctx.settings, s); applyUI(s); ctx.say("Settings saved.", false); }
    catch (e) { ctx.say(e.message, true); }
  };
  const sel = (id, label, key, opts) => h("label", { for: id }, label,
    h("select", { id, onchange: (e) => save({ [key]: e.target.value }) }, opts.map(([v, t]) => h("option", { value: v, selected: s[key] === v }, t))));
  const confirmBox = h("input", { id: "cf", type: "checkbox", checked: s.confirm_expensive, style: "width:auto", onchange: (e) => save({ confirm_expensive: e.target.checked }) });
  const checkbox = (id, key) => h("input", { id, type: "checkbox", checked: s[key], style: "width:auto", onchange: (e) => save({ [key]: e.target.checked }) });
  const compactBox = checkbox("cm", "compact_market");

  const cur = h("input", { id: "pc", type: "password", autocomplete: "current-password" });
  const nw = h("input", { id: "pn", type: "password", autocomplete: "new-password", inputmode: "numeric" });
  const rep = h("input", { id: "pr", type: "password", autocomplete: "new-password", inputmode: "numeric" });
  const pinMsg = h("div", { role: "status" });
  const pinForm = h("form", { onsubmit: async (e) => {
    e.preventDefault(); pinMsg.className = "err"; pinMsg.textContent = "";
    if (nw.value !== rep.value) { pinMsg.textContent = "The new PIN and its repetition do not match."; return; }
    try { await api("/api/change-secret", { method: "POST", body: { current: cur.value, new: nw.value } });
      pinMsg.className = "ok"; pinMsg.textContent = "PIN changed. Other devices were signed out."; cur.value = nw.value = rep.value = ""; }
    catch (x) { pinMsg.textContent = x.message; } } },
    h("label", { for: "pc" }, "Current PIN", cur), h("label", { for: "pn" }, `New PIN (digits only, at least ${d.pin_min_length})`, nw),
    h("label", { for: "pr" }, "Repeat new PIN", rep), pinMsg, h("button", { class: "primary" }, "Change PIN"));

  const a = d.account;
  const fmt = (t) => (t ? t.slice(0, 16).replace("T", " ") + " UTC" : "never");
  box.replaceChildren(h("div", { class: "grid" },
    panel("How to play", tut.trim() ? renderMarkdown(tut) : h("p", { class: "muted" }, "No tutorial has been written yet.")),
    panel("Interface", h("div", { style: "display:grid;gap:10px" },
      sel("sd", "Table density", "density", [["compact", "Compact"], ["comfortable", "Comfortable"]]),
      sel("sf", "Text size", "font_size", [["small", "Small"], ["normal", "Normal"], ["large", "Large"]]),
      sel("sc", "Market chart", "chart_type", [["candles", "Candlesticks"], ["line", "Line"]]),
      sel("sp", "Colour palette", "palette", [["default", "Default (green / red)"], ["colorblind", "Colour-blind friendly (blue / orange)"]]),
      h("label", { for: "cf", style: "display:flex;gap:8px;align-items:center" }, confirmBox, "Ask for confirmation before expensive actions"),
      h("label", { for: "cm", style: "display:flex;gap:8px;align-items:center" }, compactBox, "Compact market table (item, price, status only; best on tablets)"),
      h("p", { class: "muted" }, "Preferences are stored on the server and follow you to other devices."))),
    panel("Account", kv([["Username", a.username], ["Account created", fmt(a.created_at)], ["Last sign-in", fmt(a.last_login)], ["Active sessions", a.sessions, "num"]]),
      h("div", { class: "row", style: "margin-top:8px" }, h("button", { disabled: a.sessions < 2, title: a.sessions < 2 ? "No other sessions are open" : "",
        onclick: async () => { try { const r = await api("/api/settings/sign-out-others", { method: "POST", body: {} }); ctx.say(`Signed out ${r.signed_out} other session(s).`, false); await ctx.refresh(); } catch (e) { ctx.say(e.message, true); } } }, "Sign out all other devices"))),
    panel("Change PIN", pinForm)));
}
