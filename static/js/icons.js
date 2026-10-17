// Tiny inline SVG icon set (stroke icons, no external files). icon("eye") returns an <svg class="ico">.
const NS = "http://www.w3.org/2000/svg";
const I = {
  eye: [["p", "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"], ["c", 12, 12, 3]],
  chart: [["pl", "3,17 9,11 13,15 21,7"], ["pl", "15,7 21,7 21,13"]],
  box: [["p", "M3 7l9-4 9 4v10l-9 4-9-4z"], ["p", "M3 7l9 4 9-4M12 11v10"]],
  bolt: [["p", "M13 2L4 14h7l-1 8 9-12h-7z"]],
  pin: [["p", "M12 21s7-6.2 7-11a7 7 0 10-14 0c0 4.8 7 11 7 11z"], ["c", 12, 10, 2.5]],
  flask: [["p", "M9 3h6M10 3v6L4 19a2 2 0 002 3h12a2 2 0 002-3l-6-10V3"]],
  building: [["p", "M4 21V5l8-2v18M12 8h8v13M4 21h16M7 9h2M7 13h2M15 12h2M15 16h2"]],
  target: [["c", 12, 12, 9], ["c", 12, 12, 5], ["c", 12, 12, 1]],
  user: [["c", 12, 8, 4], ["p", "M4 21c0-4 4-6 8-6s8 2 8 6"]],
  bars: [["p", "M5 21V10M12 21V4M19 21v-8"]],
  trophy: [["p", "M8 4h8v5a4 4 0 01-8 0zM8 6H4v2a4 4 0 004 4M16 6h4v2a4 4 0 01-4 4M12 13v4M8 21h8M10 17h4"]],
  disk: [["p", "M5 3h11l3 3v15H5zM8 3v6h7V3M8 21v-7h8v7"]],
  gear: [["c", 12, 12, 3], ["p", "M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"]],
  calendar: [["p", "M4 6h16v14H4zM4 10h16M8 3v4M16 3v4"]],
  shield: [["p", "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"], ["pl", "9,12 11,14 15,10"]],
  dollar: [["c", 12, 12, 9], ["p", "M14.5 9.5c-.5-1-1.5-1.5-2.5-1.5-1.5 0-2.5.8-2.5 2s1 1.7 2.5 2 2.5.8 2.5 2-1 2-2.5 2c-1 0-2-.5-2.5-1.5M12 6v2M12 16v2"]],
  heart: [["p", "M12 21s-8-5.2-8-11a4.5 4.5 0 018-2.8A4.5 4.5 0 0120 10c0 5.8-8 11-8 11z"]],
  pulse: [["pl", "3,12 7,12 9,6 13,18 15,12 21,12"]],
  bell: [["p", "M6 16v-5a6 6 0 0112 0v5l2 2H4zM10 21h4"]],
  star: [["pl", "12,2 15,9 22,9.5 17,14.5 18.5,22 12,18 5.5,22 7,14.5 2,9.5 9,9"]],
  mask: [["p", "M3 8c3-2 6-2 9-1 3-1 6-1 9 1v4c0 4-4 7-9 7s-9-3-9-7z"], ["p", "M7 11l3 1M17 11l-3 1"]],
  news: [["p", "M4 5h14v14H4zM18 8h3v9a2 2 0 01-2 2M7 9h8M7 12h8M7 15h5"]],
  lock: [["p", "M6 11h12v10H6zM8 11V8a4 4 0 018 0v3"]],
  bag: [["p", "M5 8h14l-1 13H6zM9 8V6a3 3 0 016 0v2"]],
  clock: [["c", 12, 12, 9], ["pl", "12,7 12,12 16,14"]],
};

export function icon(name, size = 15) {
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("class", "ico"); svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("width", size); svg.setAttribute("height", size);
  for (const [t, ...a] of I[name] || []) {
    const e = document.createElementNS(NS, t === "p" ? "path" : t === "c" ? "circle" : "polyline");
    if (t === "p") e.setAttribute("d", a[0]);
    else if (t === "pl") e.setAttribute("points", a[0]);
    else { e.setAttribute("cx", a[0]); e.setAttribute("cy", a[1]); e.setAttribute("r", a[2]); }
    svg.append(e);
  }
  return svg;
}
