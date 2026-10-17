import { h } from "./ui.js";

function inline(text) {
  const out = [], re = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*\s][^*]*\*)|(\[[^\]]+\]\((https?:\/\/[^\s)]+)\))/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    if (m[1]) out.push(h("code", {}, m[1].slice(1, -1)));
    else if (m[2]) out.push(h("strong", {}, m[2].slice(2, -2)));
    else if (m[3]) out.push(h("em", {}, m[3].slice(1, -1)));
    else out.push(h("a", { href: m[5], target: "_blank", rel: "noopener noreferrer" }, m[4].slice(1, m[4].indexOf("]"))));
    last = re.lastIndex;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/** Renders a safe subset of Markdown: headings, paragraphs, lists, quotes, code, rules, bold, italic, links (http/https only). */
export function renderMarkdown(src) {
  const root = h("div", { class: "md" });
  const lines = String(src).replace(/\r\n?/g, "\n").split("\n");
  const UL = /^\s*[-*+]\s+/, OL = /^\s*\d+\.\s+/, BQ = /^>\s?/;
  let i = 0, m;
  while (i < lines.length) {
    const line = lines[i];
    if (/^```/.test(line)) { const buf = []; i++; while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]); i++; root.append(h("pre", {}, h("code", {}, buf.join("\n")))); continue; }
    if ((m = /^(#{1,6})\s+(.*)$/.exec(line))) { root.append(h("h" + m[1].length, {}, ...inline(m[2]))); i++; continue; }
    if (/^\s*([-*_])\1{2,}\s*$/.test(line)) { root.append(h("hr")); i++; continue; }
    if (UL.test(line)) { const li = []; while (i < lines.length && UL.test(lines[i])) li.push(h("li", {}, ...inline(lines[i++].replace(UL, "")))); root.append(h("ul", {}, li)); continue; }
    if (OL.test(line)) { const li = []; while (i < lines.length && OL.test(lines[i])) li.push(h("li", {}, ...inline(lines[i++].replace(OL, "")))); root.append(h("ol", {}, li)); continue; }
    if (BQ.test(line)) { const buf = []; while (i < lines.length && BQ.test(lines[i])) buf.push(lines[i++].replace(BQ, "")); root.append(h("blockquote", {}, ...inline(buf.join(" ")))); continue; }
    if (!line.trim()) { i++; continue; }
    const buf = [line]; i++;
    while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|```)/.test(lines[i]) && !UL.test(lines[i]) && !OL.test(lines[i]) && !BQ.test(lines[i])) buf.push(lines[i++]);
    root.append(h("p", {}, ...inline(buf.join(" "))));
  }
  return root;
}
