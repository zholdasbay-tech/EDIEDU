// Графики на чистом SVG — без библиотек. Каждый график — функция,
// которая получает данные и рисует <svg> внутри контейнера.

import { dayShort, fmt, parseDate, WEEKDAYS_SHORT } from "./api.js";

const NS = "http://www.w3.org/2000/svg";
const s = (tag, attrs = {}, text) => {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) n.setAttribute(k, v);
  if (text !== undefined) n.textContent = text;
  return n;
};

// ---------- всплывающая подсказка ----------
let tipEl;
function tip(html, x, y) {
  if (!tipEl) { tipEl = document.createElement("div"); tipEl.className = "tip"; document.body.append(tipEl); }
  if (html === null) { tipEl.classList.remove("show"); return; }
  tipEl.replaceChildren(...html);
  const pad = 14;
  const w = tipEl.offsetWidth || 160;
  let left = x + pad;
  if (left + w > window.innerWidth - 8) left = x - w - pad;
  tipEl.style.left = `${Math.max(8, left)}px`;
  tipEl.style.top = `${y + pad}px`;
  tipEl.classList.add("show");
}
const line = (text, bold = false) => { const d = document.createElement("div"); if (bold) d.style.fontWeight = "600"; d.textContent = text; return d; };

// На телефоне рисуем в более узкой системе координат, чтобы подписи не становились крошечными.
const chartWidth = () => (window.innerWidth < 640 ? 380 : 720);

// ---------- путь с разрывами на пропущенных днях ----------
function pathWithGaps(points) {
  let d = "", pen = false;
  for (const p of points) {
    if (p === null) { pen = false; continue; }
    d += `${pen ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`;
    pen = true;
  }
  return d;
}

/**
 * Несколько маленьких графиков друг под другом с общей осью дат.
 * series: [{ key, label, unit, color, min, max, values[], median?, ref?: {value, label}, fmt? }]
 * markers: [{ date, text }] — например, дни контрольных.
 */
export function smallMultiples(container, { dates, series, markers = [] }) {
  const W = chartWidth(), rowH = W < 720 ? 70 : 86, gap = 40, left = 34, right = 10, top = 24, axis = 22;
  const H = top + series.length * (rowH + gap) - gap + axis;
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": series.map(x => x.label).join(", ") });
  const n = dates.length;
  const x = (i) => left + (n <= 1 ? 0 : (i / (n - 1)) * (W - left - right));

  // маркеры (контрольные и т.п.) — через все ряды
  for (const m of markers) {
    const i = dates.indexOf(m.date);
    if (i < 0) continue;
    svg.append(s("line", { x1: x(i), x2: x(i), y1: top - 4, y2: H - axis, stroke: "#c2502e", "stroke-width": 1, "stroke-dasharray": "2 3", opacity: .7 }));
    svg.append(s("text", { x: x(i) + 4, y: top + 12, class: "ann", "font-size": 15 }, m.text));
  }

  series.forEach((ser, k) => {
    const y0 = top + k * (rowH + gap);
    const y = (v) => y0 + rowH - ((v - ser.min) / (ser.max - ser.min)) * rowH;
    const g = s("g");
    // подпись ряда и шкала
    g.append(s("text", { x: left, y: y0 - 10, class: "lbl", fill: ser.color }, ser.label));
    for (const t of [ser.min, ser.max]) {
      g.append(s("line", { x1: left, x2: W - right, y1: y(t), y2: y(t), stroke: "#e6dfd1", "stroke-width": 1 }));
      g.append(s("text", { x: left - 8, y: y(t) + 4, "text-anchor": "end" }, fmt(t)));
    }
    if (ser.ref) {
      g.append(s("line", { x1: left, x2: W - right, y1: y(ser.ref.value), y2: y(ser.ref.value), stroke: ser.color, "stroke-width": 1, opacity: .35 }));
      g.append(s("text", { x: W - right, y: y(ser.ref.value) - 5, "text-anchor": "end", class: "ann", "font-size": 15 }, ser.ref.label));
    }
    if (ser.median !== undefined && ser.median !== null) {
      g.append(s("line", { x1: left, x2: W - right, y1: y(ser.median), y2: y(ser.median), stroke: "#7a7368", "stroke-width": 1.2, "stroke-dasharray": "4 4" }));
    }
    const pts = ser.values.map((v, i) => (v === null || v === undefined ? null : [x(i), y(v)]));
    g.append(s("path", { d: pathWithGaps(pts), fill: "none", stroke: ser.color, "stroke-width": 2.2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
    pts.forEach((p) => { if (p) g.append(s("circle", { cx: p[0], cy: p[1], r: 2.6, fill: ser.color })); });
    svg.append(g);
  });

  // ось дат: 5–6 подписей
  const step = Math.max(1, Math.round(n / (W < 720 ? 4 : 6)));
  for (let i = 0; i < n; i += step) {
    svg.append(s("text", { x: x(i), y: H - 5, "text-anchor": "middle" }, dayShort(dates[i])));
  }

  // интерактив: вертикальная линия + подсказка
  const cursor = s("line", { y1: top, y2: H - axis, stroke: "#1f1d1a", "stroke-width": 1, opacity: 0 });
  svg.append(cursor);
  const hit = s("rect", { x: left, y: 0, width: W - left - right, height: H, fill: "transparent" });
  svg.append(hit);
  const move = (ev) => {
    const r = svg.getBoundingClientRect();
    const px = ((ev.clientX - r.left) / r.width) * W;
    const i = Math.max(0, Math.min(n - 1, Math.round(((px - left) / (W - left - right)) * (n - 1))));
    cursor.setAttribute("x1", x(i)); cursor.setAttribute("x2", x(i)); cursor.setAttribute("opacity", .25);
    const d = parseDate(dates[i]);
    const rows = [line(`${WEEKDAYS_SHORT[d.getDay()]}, ${dayShort(dates[i])}`, true)];
    let any = false;
    for (const ser of series) {
      const v = ser.values[i];
      if (v === null || v === undefined) continue;
      any = true;
      rows.push(line(`${ser.label}: ${ser.fmt ? ser.fmt(v) : fmt(v)}`));
    }
    if (!any) rows.push(line("нет отметки"));
    const m = markers.find((mm) => mm.date === dates[i]);
    if (m) rows.push(line(`• ${m.text}`));
    tip(rows, ev.clientX, ev.clientY);
  };
  hit.addEventListener("pointermove", move);
  hit.addEventListener("pointerleave", () => { cursor.setAttribute("opacity", 0); tip(null); });

  container.replaceChildren(svg);
}

/** Индекс перегрузки по дням: линия на фоне трёх зон. */
export function overloadChart(container, history) {
  const W = chartWidth(), H = W < 720 ? 150 : 170, left = 34, right = 10, top = 10, bottom = 22;
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Индекс перегрузки по дням" });
  const n = history.length;
  if (!n) { container.replaceChildren(); return; }
  const x = (i) => left + (n <= 1 ? 0 : (i / (n - 1)) * (W - left - right));
  const y = (v) => top + (1 - v / 100) * (H - top - bottom);
  const zones = [[0, 35, "#e3ecdf"], [35, 60, "#f5e9cb"], [60, 100, "#f4dcd3"]];
  for (const [a, b, c] of zones) svg.append(s("rect", { x: left, width: W - left - right, y: y(b), height: y(a) - y(b), fill: c, opacity: .8 }));
  for (const t of [0, 35, 60, 100]) svg.append(s("text", { x: left - 6, y: y(t) + 4, "text-anchor": "end" }, t));
  const pts = history.map((h, i) => (h.score === null ? null : [x(i), y(h.score)]));
  svg.append(s("path", { d: pathWithGaps(pts), fill: "none", stroke: "#1f1d1a", "stroke-width": 2.2, "stroke-linejoin": "round" }));
  const last = [...pts].reverse().find(Boolean);
  if (last) svg.append(s("circle", { cx: last[0], cy: last[1], r: 4.5, fill: "#1f1d1a" }));
  const step = Math.max(1, Math.round(n / (W < 720 ? 4 : 6)));
  for (let i = 0; i < n; i += step) svg.append(s("text", { x: x(i), y: H - 5, "text-anchor": "middle" }, dayShort(history[i].date)));

  const hit = s("rect", { x: left, y: 0, width: W - left - right, height: H, fill: "transparent" });
  svg.append(hit);
  hit.addEventListener("pointermove", (ev) => {
    const r = svg.getBoundingClientRect();
    const px = ((ev.clientX - r.left) / r.width) * W;
    const i = Math.max(0, Math.min(n - 1, Math.round(((px - left) / (W - left - right)) * (n - 1))));
    const h = history[i];
    tip([line(dayShort(h.date), true), line(h.score === null ? "мало данных" : `индекс ${h.score}`)], ev.clientX, ev.clientY);
  });
  hit.addEventListener("pointerleave", () => tip(null));
  container.replaceChildren(svg);
}

/** Календарь настроения: недели — столбцы, дни недели — строки. */
export function moodCalendar(container, { dates, values, today }) {
  const byDate = new Map(dates.map((d, i) => [d, values[i]]));
  const end = parseDate(today);
  const weeks = 12, cell = 17, gapc = 4, left = 22, top = 18;
  // начинаем с понедельника
  const start = new Date(end);
  start.setDate(start.getDate() - ((end.getDay() + 6) % 7) - (weeks - 1) * 7);
  const W = left + weeks * (cell + gapc), H = top + 7 * (cell + gapc);
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Настроение по дням" });
  const colors = { 1: "#b2412f", 2: "#d98c6a", 3: "#e3d6b4", 4: "#9dbf92", 5: "#4f7a58" };
  ["Пн", "", "Ср", "", "Пт", "", "Вс"].forEach((t, r) => t && svg.append(s("text", { x: 0, y: top + r * (cell + gapc) + 12, "font-size": 10 }, t)));
  const d = new Date(start);
  for (let w = 0; w < weeks; w++) {
    for (let r = 0; r < 7; r++) {
      const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
      if (d <= end) {
        const v = byDate.get(iso);
        const rect = s("rect", {
          x: left + w * (cell + gapc), y: top + r * (cell + gapc), width: cell, height: cell, rx: 4,
          fill: v ? colors[v] : "transparent", stroke: v ? "none" : "#d8cfbd", "stroke-dasharray": v ? null : "2 2",
        });
        const label = v ? `настроение ${v} из 5` : "нет отметки";
        rect.addEventListener("pointermove", (ev) => tip([line(dayShort(iso), true), line(label)], ev.clientX, ev.clientY));
        rect.addEventListener("pointerleave", () => tip(null));
        svg.append(rect);
        if (r === 0 && d.getDate() <= 7) svg.append(s("text", { x: left + w * (cell + gapc), y: 11, "font-size": 10 }, dayShort(iso).split(" ")[1]));
      }
      d.setDate(d.getDate() + 1);
    }
  }
  container.replaceChildren(svg);
}

/** Столбики по дням недели. rows: [{day, value}] */
export function weekdayBars(container, rows, { color = "#b2412f", max = 5, label = "стресс" } = {}) {
  const W = 360, H = 150, bottom = 22, top = 16;
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `${label} по дням недели` });
  const bw = W / rows.length;
  rows.forEach((r, i) => {
    const x = i * bw + bw * 0.18, w = bw * 0.64;
    svg.append(s("text", { x: i * bw + bw / 2, y: H - 5, "text-anchor": "middle" }, r.day));
    if (r.value === null || r.value === undefined) {
      svg.append(s("text", { x: i * bw + bw / 2, y: H - bottom - 6, "text-anchor": "middle" }, "—"));
      return;
    }
    const h = ((r.value - 1) / (max - 1)) * (H - top - bottom) + 4;
    svg.append(s("rect", { x, y: H - bottom - h, width: w, height: h, rx: 5, fill: color, opacity: r.highlight ? 1 : .55 }));
    svg.append(s("text", { x: i * bw + bw / 2, y: H - bottom - h - 5, "text-anchor": "middle", "font-weight": 600, fill: "#4a453e" }, fmt(r.value)));
  });
  container.replaceChildren(svg);
}

/** Простые линии по неделям для школьной панели. series: [{label, color, values[], min, max, fmt}] */
export function weeklyLines(container, { labels, series }) {
  smallMultiples(container, { dates: labels, series });
}
