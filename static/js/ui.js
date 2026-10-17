/** Tiny DOM helper. Text is always set via textContent/attributes: no innerHTML with data. */
export function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "style") el.style.cssText = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null) el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  return el;
}
export const money = (n) => "$" + Number(n).toLocaleString("en-US");
export const panel = (title, ...body) => h("section", { class: "panel" }, h("h2", {}, title), h("div", { class: "body" }, ...body));
export const kv = (rows) => h("dl", { class: "kv" }, rows.flatMap(([k, v, cls]) => [h("dt", {}, k), h("dd", { class: cls || "" }, v)]));
export const bar = (v, max, label, cls = "info") => h("div", { class: "bar", role: "progressbar", "aria-valuenow": v, "aria-valuemin": 0, "aria-valuemax": max, "aria-label": label },
  h("i", { class: cls, style: `width:${Math.max(0, Math.min(100, (v / max) * 100))}%` }));

/** Labelled meter. kind: "health" (high is good), "strain" (high is bad) or "info". The state word means colour is never the only signal. */
export function meter(label, v, max, kind = "info", extra = "") {
  const r = max ? v / max : 0;
  let cls = "info", word = "";
  if (kind === "health") { [cls, word] = r >= 0.6 ? ["good", "Good"] : r >= 0.3 ? ["warn", "Hurt"] : ["bad", "Critical"]; }
  if (kind === "strain") { [cls, word] = r <= 0.4 ? ["good", "Calm"] : r <= 0.7 ? ["warn", "Tense"] : ["bad", "Overloaded"]; }
  return h("div", { class: "meter" }, h("div", { class: "top" }, h("span", {}, label),
    h("span", { class: "num " + (cls === "info" ? "" : cls) }, `${v}/${max}` + (word ? ` · ${word}` : "") + extra)), bar(v, max, label, cls));
}

/** Five stars like a classic wanted level; wanted 1-20 = 1 star ... 81-100 = 5 stars. */
export function stars(w) {
  const n = w <= 0 ? 0 : Math.min(5, Math.ceil(w / 20));
  return h("span", { class: "stars" + (n >= 4 ? " hot" : ""), role: "img", "aria-label": `Wanted level: ${n} of 5 stars (${w} of 100)` },
    [0, 1, 2, 3, 4].map((i) => h("span", { class: i < n ? "on" : "off", "aria-hidden": "true" }, i < n ? "★" : "☆")));
}
export const starCount = (w) => (w <= 0 ? 0 : Math.min(5, Math.ceil(w / 20)));

export function spark(values, w = 280, hgt = 70) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${w} ${hgt}`); svg.setAttribute("class", "spark");
  svg.setAttribute("role", "img");
  if (values.length < 2) { svg.setAttribute("aria-label", "Not enough history yet"); return svg; }
  const min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * (w - 4) + 2},${hgt - 4 - ((v - min) / span) * (hgt - 8)}`).join(" ");
  const line = document.createElementNS(ns, "polyline");
  line.setAttribute("points", pts); line.setAttribute("fill", "none"); line.setAttribute("stroke-width", "1.5");
  line.setAttribute("class", values[values.length - 1] >= values[0] ? "up" : "down");
  svg.setAttribute("aria-label", `Price from ${values[0]} to ${values[values.length - 1]}, low ${min}, high ${max}`);
  svg.append(line);
  return svg;
}
export const pct = (a, b) => (b ? ((a - b) / b) * 100 : 0);
export const sign = (n) => (n > 0 ? "▲ " : n < 0 ? "▼ " : "– ");

export const ageText = (s) => `${s.age.years} years, ${s.age.days} days`;

function niceTicks(min, max, n = 5) {
  if (min === max) { min -= 1; max += 1; }
  const step0 = (max - min) / (n - 1), mag = Math.pow(10, Math.floor(Math.log10(step0))), norm = step0 / mag;
  const step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
  const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step, ticks = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Math.round(v * 1e6) / 1e6);
  return { ticks, lo, hi };
}

/** Line chart with x and y axes. Scales and tick counts adapt to the data shown. points: [{x, y}] */
export function lineChart(points, { xLabel = "Time", yLabel = "Value", fmtX = (v) => v, fmtY = (v) => v, w = 520, hgt = 240 } = {}) {
  const ns = "http://www.w3.org/2000/svg";
  const el = (tag, attrs = {}, text) => { const e = document.createElementNS(ns, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); if (text != null) e.textContent = text; return e; };
  const svg = el("svg", { viewBox: `0 0 ${w} ${hgt}`, class: "chart", role: "img" });
  if (points.length < 2) { svg.setAttribute("aria-label", "Not enough data yet"); svg.append(el("text", { x: w / 2, y: hgt / 2, "text-anchor": "middle" }, "Not enough data yet")); return svg; }
  const m = { l: 58, r: 14, t: 12, b: 44 }, iw = w - m.l - m.r, ih = hgt - m.t - m.b;
  const xs = points.map((p) => p.x), ys = points.map((p) => p.y);
  const { ticks, lo, hi } = niceTicks(Math.min(...ys), Math.max(...ys), ih > 150 ? 6 : 4);
  const x0 = xs[0], span = (xs[xs.length - 1] - x0) || 1;
  const X = (v) => m.l + ((v - x0) / span) * iw, Y = (v) => m.t + ih - ((v - lo) / (hi - lo)) * ih;
  ticks.forEach((t) => { svg.append(el("line", { class: "grid", x1: m.l, x2: w - m.r, y1: Y(t), y2: Y(t) }), el("text", { x: m.l - 6, y: Y(t) + 3, "text-anchor": "end" }, fmtY(t))); });
  const nx = Math.min(points.length, iw > 380 ? 7 : 4);
  for (let i = 0; i < nx; i++) {
    const p = points[Math.round((i / (nx - 1)) * (points.length - 1))];
    svg.append(el("line", { class: "axis", x1: X(p.x), x2: X(p.x), y1: m.t + ih, y2: m.t + ih + 4 }), el("text", { x: X(p.x), y: m.t + ih + 16, "text-anchor": "middle" }, fmtX(p.x)));
  }
  svg.append(el("line", { class: "axis", x1: m.l, x2: m.l, y1: m.t, y2: m.t + ih }), el("line", { class: "axis", x1: m.l, x2: w - m.r, y1: m.t + ih, y2: m.t + ih }),
    el("polyline", { class: "line " + (ys[ys.length - 1] >= ys[0] ? "up" : "down"), fill: "none", points: points.map((p) => `${X(p.x)},${Y(p.y)}`).join(" ") }),
    el("circle", { class: "dotp", cx: X(xs[xs.length - 1]), cy: Y(ys[ys.length - 1]), r: 3 }),
    el("text", { class: "title", x: m.l + iw / 2, y: hgt - 6, "text-anchor": "middle" }, xLabel),
    el("text", { class: "title", x: 12, y: m.t + ih / 2, "text-anchor": "middle", transform: `rotate(-90 12 ${m.t + ih / 2})` }, yLabel));
  svg.setAttribute("aria-label", `${yLabel} over ${xLabel}: from ${fmtY(ys[0])} to ${fmtY(ys[ys.length - 1])}, low ${fmtY(Math.min(...ys))}, high ${fmtY(Math.max(...ys))}`);
  return svg;
}

/** Candlestick chart with axes. candles: [{day, open, high, low, close, live}]. Width is in real pixels so text stays readable. */
export function candleChart(c, { w = 480, hgt = 290, xLabel = "Cycle", yLabel = "Price", fmtX = (v) => v, fmtY = (v) => v } = {}) {
  const ns = "http://www.w3.org/2000/svg";
  const el = (tag, attrs = {}, text) => { const e = document.createElementNS(ns, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); if (text != null) e.textContent = text; return e; };
  const svg = el("svg", { viewBox: `0 0 ${w} ${hgt}`, width: w, height: hgt, class: "chart", role: "img" });
  if (c.length < 2) { svg.append(el("text", { x: w / 2, y: hgt / 2, "text-anchor": "middle" }, "Not enough data yet")); return svg; }
  const m = { l: 66, r: 66, t: 14, b: 52 }, iw = w - m.l - m.r, ih = hgt - m.t - m.b, n = c.length;
  const { ticks, lo, hi } = niceTicks(Math.min(...c.map((k) => k.low)), Math.max(...c.map((k) => k.high)), 6);
  const X = (i) => m.l + ((i + 0.5) / n) * iw, Y = (v) => m.t + ih - ((v - lo) / (hi - lo)) * ih;
  ticks.forEach((t) => svg.append(el("line", { class: "grid", x1: m.l, x2: w - m.r, y1: Y(t), y2: Y(t) }), el("text", { x: m.l - 8, y: Y(t) + 4, "text-anchor": "end" }, fmtY(t))));
  const cw = Math.max(2, Math.min(14, (iw / n) * 0.7));
  c.forEach((k, i) => {
    const cls = (k.close >= k.open ? "candle up" : "candle down") + (k.live ? " live" : "");
    svg.append(el("line", { class: cls, x1: X(i), x2: X(i), y1: Y(k.high), y2: Y(k.low) }),
      el("rect", { class: cls, x: X(i) - cw / 2, y: Math.min(Y(k.open), Y(k.close)), width: cw, height: Math.max(1.5, Math.abs(Y(k.open) - Y(k.close))) }));
  });
  const nx = Math.min(n, iw > 380 ? 7 : 4);
  for (let i = 0; i < nx; i++) {
    const idx = Math.round((i / (nx - 1)) * (n - 1));
    svg.append(el("line", { class: "axis", x1: X(idx), x2: X(idx), y1: m.t + ih, y2: m.t + ih + 5 }), el("text", { x: X(idx), y: m.t + ih + 20, "text-anchor": "middle" }, fmtX(c[idx].day)));
  }
  const last = c[n - 1].close;
  svg.append(el("line", { class: "axis", x1: m.l, x2: m.l, y1: m.t, y2: m.t + ih }), el("line", { class: "axis", x1: m.l, x2: w - m.r, y1: m.t + ih, y2: m.t + ih }),
    el("line", { class: "lastline", x1: m.l, x2: w - m.r, y1: Y(last), y2: Y(last) }), el("text", { class: "lasttxt", x: w - m.r + 6, y: Y(last) + 4 }, fmtY(last)),
    el("text", { class: "title", x: m.l + iw / 2, y: hgt - 10, "text-anchor": "middle" }, xLabel),
    el("text", { class: "title", x: 14, y: m.t + ih / 2, "text-anchor": "middle", transform: `rotate(-90 14 ${m.t + ih / 2})` }, yLabel));
  svg.setAttribute("aria-label", `Candlestick chart of ${yLabel} per ${xLabel}: latest ${fmtY(last)}, low ${fmtY(Math.min(...c.map((k) => k.low)))}, high ${fmtY(Math.max(...c.map((k) => k.high)))}`);
  return svg;
}

/** Small meter (label + percent) for narrow, side-by-side use. Higher is better. */
export function miniMeter(label, v) {
  const cls = v >= 60 ? "good" : v >= 30 ? "warn" : "bad";
  return h("div", { class: "meter mini" }, h("div", { class: "top" }, h("span", {}, label), h("span", { class: "num " + (cls === "good" ? "" : cls) }, `${v}%`)), bar(v, 100, label, cls));
}
