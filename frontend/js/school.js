// Панель школьного психолога: только агрегаты по классам, без отдельных учеников.

import { $, $$, api, ApiError, auth, dayLong, dayShort, el, fmt, plural } from "./api.js";
import { weeklyLines } from "./charts.js";

const METRICS = {
  stress: { label: "Стресс", lo: 1.8, hi: 3.6, invert: false, show: (v) => fmt(v), tip: "средний стресс из 5" },
  sleep: { label: "Сон", lo: 6.2, hi: 8.2, invert: true, show: (v) => fmt(v), tip: "средний сон, ч" },
  mood: { label: "Настроение", lo: 2.8, hi: 4.2, invert: true, show: (v) => fmt(v), tip: "среднее настроение из 5" },
  strain_share: { label: "Перегружены", lo: 0.05, hi: 0.5, invert: false, show: (v) => `${Math.round(v * 100)}%`, tip: "доля учеников со стрессом ≥ 3,8 или сном < 6,5 ч" },
};
let metric = "stress";
let data = null;

// от светлого песочного к терракоте
function heatColor(v, { lo, hi, invert }) {
  let t = Math.max(0, Math.min(1, (v - lo) / (hi - lo)));
  if (invert) t = 1 - t;
  const a = [241, 233, 218], b = [178, 65, 47];
  const c = a.map((x, i) => Math.round(x + (b[i] - x) * t));
  return { bg: `rgb(${c.join(",")})`, fg: t > 0.55 ? "#fff" : "#1f1d1a" };
}

async function boot() {
  if (!auth.token) { location.href = "/"; return; }
  let me;
  try { me = await api("/me"); } catch (e) {
    if (e instanceof ApiError && e.status === 401) { auth.clear(); location.href = "/"; return; }
    throw e;
  }
  if (me.role !== "staff") { location.href = "/app"; return; }
  $("#demo-banner").hidden = !me.is_demo;
  $("#logout").addEventListener("click", async () => {
    try { await api("/auth/logout", { method: "POST" }); } catch { /* ок */ }
    auth.clear(); location.href = "/";
  });
  data = await api("/school/overview?weeks=8");
  render();
}

function tile(v, l) {
  return el("div", { class: "card stat", style: "margin:0" }, el("div", { class: "v" }, v), el("div", { class: "l" }, l));
}

function render() {
  const root = $("#school");
  const L = data.latest;
  const total = data.classes.reduce((s, c) => s + c.students_total, 0);
  const sharing = data.classes.reduce((s, c) => s + c.sharing, 0);
  const parts = [];

  parts.push(el("div", { class: "view-head" }, el("div", {},
    el("p", { class: "eyebrow" }, L ? `Неделя с ${dayLong(L.week)}` : "Пока нет данных"),
    el("h2", {}, data.school.name))));

  parts.push(el("div", { class: "grid g4" },
    tile(`${sharing} из ${total}`, "учеников делятся данными"),
    tile(L ? `${fmt(L.sleep)} ч` : "—", "средний сон за неделю"),
    tile(L ? `${Math.round(L.short_sleep_share * 100)}%` : "—", "спят в среднем меньше 7 ч"),
    tile(L ? `${Math.round(L.strain_share * 100)}%` : "—", "перегружены (стресс ≥ 3,8 или сон < 6,5 ч)")));

  // сигналы
  const alerts = el("div", { class: "card", style: "margin-top:16px" }, el("h3", {}, "На что обратить внимание"));
  if (data.alerts.length) {
    data.alerts.forEach((a) => alerts.append(el("div", { class: `alert ${a.severity}` }, el("span", { class: "dot" }), el("div", {}, a.text))));
  } else {
    alerts.append(el("p", { class: "muted", style: "margin:0" }, "Сейчас ни в одном классе нет резкого роста напряжения по сравнению с прошлым месяцем."));
  }
  alerts.append(el("p", { class: "tiny muted", style: "margin:12px 0 0" },
    "Сигнал появляется, если за последнюю неделю средний стресс класса вырос на 0,4 и больше или доля перегруженных выросла на 15 п.п. по сравнению с 4 предыдущими неделями."));
  parts.push(alerts);

  // тепловая карта
  const switcher = el("div", { class: "tabs-mini", style: "max-width:520px" });
  for (const [k, m] of Object.entries(METRICS)) {
    const b = el("button", { type: "button", class: k === metric ? "on" : "" }, m.label);
    b.addEventListener("click", () => { metric = k; render(); });
    switcher.append(b);
  }
  const table = el("table", { class: "heat" });
  const head = el("tr", {}, el("th", {}), ...data.weeks.map((w) => el("th", {}, dayShort(w))));
  table.append(el("thead", {}, head));
  const tbody = el("tbody");
  const M = METRICS[metric];
  for (const c of data.classes) {
    const tr = el("tr", {}, el("th", { class: "cls" }, c.name));
    c.weeks.forEach((w, i) => {
      if (!w) { tr.append(el("td", { class: "none", title: "нет отметок" })); return; }
      if (w.hidden) { tr.append(el("td", { class: "hidden", title: `Меньше ${data.k} учеников: цифры скрыты, чтобы никого нельзя было узнать` }, `<${data.k}`)); return; }
      const v = w[metric];
      const col = heatColor(v, M);
      tr.append(el("td", {
        style: `background:${col.bg};color:${col.fg}`,
        title: `${c.name}, неделя с ${dayShort(data.weeks[i])}: ${M.tip} — ${M.show(v)}; учеников: ${w.n}; сон ${fmt(w.sleep)} ч, стресс ${fmt(w.stress)}, настроение ${fmt(w.mood)}`,
      }, M.show(v)));
    });
    tbody.append(tr);
  }
  table.append(tbody);
  parts.push(el("div", { class: "card", style: "margin-top:16px" },
    el("div", { class: "view-head", style: "margin-bottom:10px" }, el("h3", { style: "margin:0" }, "Классы по неделям"), switcher),
    el("div", { class: "scroll-x" }, table),
    el("p", { class: "tiny muted", style: "margin:10px 0 0" },
      `Чем темнее, тем хуже. Штриховка значит, что в группе меньше ${data.k} учеников и цифры скрыты. Наведите на клетку, чтобы увидеть подробности.`)));

  // динамика школы
  const chart = el("div", { class: "chart" });
  const sw = data.school_weeks.map((w) => (w && !w.hidden ? w : null));
  const tagsCard = el("div", { class: "card" }, el("h3", {}, "Метки этой недели"),
    el("p", { class: "small muted" }, `Что ученики отмечали чаще всего. Учитываются метки, которые поставили хотя бы ${data.k} человек.`));
  if (data.tags.length) {
    tagsCard.append(el("div", { style: "display:grid;gap:8px" }, ...data.tags.map(([t, n]) =>
      el("div", { style: "display:flex;justify-content:space-between;border-bottom:1px dashed var(--line-2);padding:6px 0" },
        el("span", {}, t), el("b", { class: "num" }, `${n} ${plural(n, "ученик", "ученика", "учеников")}`)))));
  } else tagsCard.append(el("p", { class: "muted" }, "Пока ничего заметного."));

  parts.push(el("div", { class: "two-col", style: "margin-top:16px" },
    el("div", { class: "card" }, el("h3", {}, "Вся школа за 8 недель"), chart),
    tagsCard));
  weeklyLines(chart, {
    labels: data.weeks,
    series: [
      { label: "Стресс", color: "#b2412f", min: 1.5, max: 4.5, values: sw.map((w) => w && w.stress), fmt: (v) => `${fmt(v, 2)} из 5` },
      { label: "Сон, ч", color: "#4c5a9e", min: 6, max: 9, values: sw.map((w) => w && w.sleep), ref: { value: 8, label: "8 ч" }, fmt: (v) => `${fmt(v, 2)} ч` },
      { label: "Настроение", color: "#2f7a78", min: 2.5, max: 4.5, values: sw.map((w) => w && w.mood), fmt: (v) => `${fmt(v, 2)} из 5` },
    ],
  });

  // классы и коды
  parts.push(el("div", { class: "grid g2", style: "margin-top:16px" },
    el("div", { class: "card" }, el("h3", {}, "Коды классов"),
      el("p", { class: "small muted" }, "Ученик вводит код в профиле и попадает в свой класс. Делиться данными или нет, решает сам ученик."),
      el("table", { class: "plain" }, el("thead", {}, el("tr", {}, el("th", {}, "Класс"), el("th", {}, "Код"), el("th", {}, "Учеников"), el("th", {}, "Делятся"))),
        el("tbody", {}, ...data.classes.map((c) => el("tr", {}, el("td", {}, c.name), el("td", {}, el("code", {}, c.code)), el("td", { class: "num" }, c.students_total), el("td", { class: "num" }, c.sharing)))))),
    el("div", { class: "card" }, el("h3", {}, "Что вы здесь не увидите"),
      el("ul", { class: "feature-list" },
        el("li", {}, "Имена, логины и заметки учеников. Они даже не попадают в запрос к базе."),
        el("li", {}, "Отдельные дни и отдельных людей. Сначала считается средняя неделя каждого ученика, потом среднее по классу."),
        el("li", {}, `Группы меньше ${data.k} человек. Иначе по цифрам можно было бы догадаться, о ком речь.`),
        el("li", {}, "Учеников, которые выключили «делиться со школой».")))));

  root.replaceChildren(...parts);
}

boot().catch((e) => { console.error(e); $("#school").replaceChildren(el("div", { class: "card" }, "Не получилось загрузить панель. ", e.message || "")); });
