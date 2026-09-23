// Приложение ученика: отметка дня, картина, закономерности, эксперименты, профиль.

import { $, $$, addDays, api, ApiError, auth, dayLong, dayShort, el, fmt, parseDate, plural, toast, WEEKDAYS_SHORT } from "./api.js";
import { moodCalendar, overloadChart, smallMultiples, weekdayBars } from "./charts.js";

const TAGS = ["контрольная", "экзамен", "олимпиада", "дедлайн", "тренировка", "болею", "поссорился", "праздник", "поездка", "выходной"];
const LEVEL_PILL = { calm: "good", watch: "watch", high: "bad" };
const METRIC = {
  sleep_hours: { label: "Сон", color: "var(--c-sleep)", hex: "#4c5a9e", unit: "ч", max: 11 },
  sleep_quality: { label: "Качество сна", color: "var(--c-sleep)", hex: "#4c5a9e", unit: "/5", max: 5 },
  mood: { label: "Настроение", color: "var(--c-mood)", hex: "#2f7a78", unit: "/5", max: 5 },
  stress: { label: "Стресс", color: "var(--c-stress)", hex: "#b2412f", unit: "/5", max: 5 },
  energy: { label: "Энергия", color: "var(--c-energy)", hex: "#c08a1e", unit: "/5", max: 5 },
};

const state = { me: null, today: null, checkins: [], byDate: new Map(), insights: null, experiments: [], day: null };

// ---------------------------------------------------------------------------
// Старт
// ---------------------------------------------------------------------------

async function boot() {
  if (!auth.token) { location.href = "/"; return; }
  try {
    state.me = await api("/me");
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) { auth.clear(); location.href = "/"; return; }
    throw e;
  }
  if (state.me.role === "staff") { location.href = "/school"; return; }
  $("#hello").textContent = `Привет, ${state.me.display_name || state.me.username}`;
  $("#demo-banner").hidden = !state.me.is_demo;
  $("#logout").addEventListener("click", logout);

  buildForm();
  bindTabs();
  await reload();
  selectDay(state.today);
  openView((location.hash || "#today").slice(1));
}

async function reload() {
  const [c, ins, ex] = await Promise.all([api("/checkins?days=120"), api("/insights"), api("/experiments")]);
  state.today = c.today;
  state.checkins = c.checkins;
  state.byDate = new Map(c.checkins.map((r) => [r.date, r]));
  state.insights = ins;
  state.experiments = ex.experiments;
  renderDayPicker();
  renderTodaySide();
  renderPicture();
  renderPatterns();
  renderExperiments();
  renderProfile();
}

async function logout() {
  try { await api("/auth/logout", { method: "POST" }); } catch { /* всё равно выходим */ }
  auth.clear();
  location.href = "/";
}

// ---------------------------------------------------------------------------
// Вкладки
// ---------------------------------------------------------------------------

function bindTabs() {
  $$(".appbar button").forEach((b) => b.addEventListener("click", () => openView(b.dataset.view)));
  window.addEventListener("hashchange", () => openView(location.hash.slice(1)));
}

function openView(name) {
  if (!$(`#view-${name}`)) name = "today";
  $$(".appbar button").forEach((b) => b.classList.toggle("on", b.dataset.view === name));
  $$(".view").forEach((v) => v.classList.toggle("on", v.id === `view-${name}`));
  if (location.hash.slice(1) !== name) history.replaceState(null, "", `#${name}`);
  window.scrollTo({ top: 0 });
}

// ---------------------------------------------------------------------------
// Форма отметки
// ---------------------------------------------------------------------------

const form = {};  // текущие значения полей

function buildForm() {
  // шкалы 1–5
  $$(".scale").forEach((box) => {
    const labels = box.dataset.labels.split("|");
    labels.forEach((text, i) => {
      const v = i + 1;
      const b = el("button", { type: "button", "data-v": v, "aria-pressed": "false" }, el("span", { class: "n" }, v), text);
      b.addEventListener("click", () => setScale(box.dataset.field, form[box.dataset.field] === v ? null : v));
      box.append(b);
    });
  });
  // степперы
  $$(".stepper").forEach((box) => {
    const f = box.dataset.field, step = +box.dataset.step, min = +box.dataset.min, max = +box.dataset.max;
    const out = el("output", { "aria-live": "polite" });
    const minus = el("button", { type: "button", "aria-label": "меньше" }, "−");
    const plus = el("button", { type: "button", "aria-label": "больше" }, "+");
    const change = (d) => {
      const cur = form[f] ?? +box.dataset.start;
      setStepper(f, Math.min(max, Math.max(min, Math.round((cur + d) * 10) / 10)));
    };
    minus.addEventListener("click", () => change(-step));
    plus.addEventListener("click", () => change(step));
    box.append(minus, out, plus);
  });
  // метки
  const tagBox = $("#tags");
  TAGS.forEach((t) => {
    const b = el("button", { type: "button", "data-tag": t, "aria-pressed": "false" }, t);
    b.addEventListener("click", () => { b.classList.toggle("on"); b.setAttribute("aria-pressed", b.classList.contains("on")); });
    tagBox.append(b);
  });
  $("#checkin-form").addEventListener("submit", saveDay);
  $("#delete-day").addEventListener("click", deleteDay);
}

function setScale(field, v) {
  form[field] = v;
  $$(`.scale[data-field=${field}] button`).forEach((b) => {
    const on = +b.dataset.v === v;
    b.classList.toggle("on", on);
    b.setAttribute("aria-pressed", on);
  });
}

function setStepper(field, v) {
  form[field] = v;
  const box = $(`.stepper[data-field=${field}]`);
  const out = $("output", box);
  if (v === null || v === undefined) { out.textContent = "не отмечено"; out.classList.add("empty"); return; }
  out.classList.remove("empty");
  out.textContent = `${fmt(v)} ${box.dataset.unit}`;
}

function renderDayPicker() {
  const box = $("#day-picker");
  box.replaceChildren();
  for (let i = 7; i >= 0; i--) {
    const iso = addDays(state.today, -i);
    const d = parseDate(iso);
    const b = el("button", { type: "button", class: [state.byDate.has(iso) ? "done" : "", iso === state.day ? "on" : ""].join(" "),
      title: state.byDate.has(iso) ? "Отмечено" : "Не отмечено" },
    i === 0 ? (window.innerWidth < 620 ? "сег." : "сегодня") : WEEKDAYS_SHORT[d.getDay()], el("b", {}, d.getDate()));
    b.addEventListener("click", () => selectDay(iso));
    box.append(b);
  }
}

function lastEntryBefore(iso) {
  for (let i = state.checkins.length - 1; i >= 0; i--) if (state.checkins[i].date < iso) return state.checkins[i];
  return null;
}

function selectDay(iso) {
  state.day = iso;
  renderDayPicker();
  const entry = state.byDate.get(iso);
  const isToday = iso === state.today;
  $("#today-eyebrow").textContent = isToday ? `Сегодня, ${dayLong(iso)}` : `${WEEKDAYS_SHORT[parseDate(iso).getDay()]}, ${dayLong(iso)}`;
  $("#today-title").textContent = entry ? (isToday ? "Сегодня уже отмечено" : "Этот день отмечен") : (isToday ? "Как прошёл день?" : "Заполнить пропущенный день");
  // числовые поля: из записи, иначе как в прошлый раз, иначе стартовое значение
  const prev = entry || lastEntryBefore(iso);
  for (const f of ["sleep_hours", "study_hours", "screen_hours", "activity_min"]) {
    const v = prev ? prev[f] : null;
    setStepper(f, v ?? +$(`.stepper[data-field=${f}]`).dataset.start);
  }
  for (const f of ["sleep_quality", "mood", "stress", "energy"]) setScale(f, entry ? entry[f] : null);
  const tags = new Set(entry ? entry.tags : []);
  $$("#tags button").forEach((b) => { const on = tags.has(b.dataset.tag); b.classList.toggle("on", on); b.setAttribute("aria-pressed", on); });
  $("#checkin-form textarea").value = entry ? entry.note : "";
  $("#save-btn").textContent = entry ? "Сохранить изменения" : "Сохранить день";
  $("#delete-day").hidden = !entry;
  $("#checkin-error").textContent = "";
}

async function saveDay(e) {
  e.preventDefault();
  const err = $("#checkin-error");
  if (!form.mood || !form.stress) {
    err.textContent = "Отметь хотя бы настроение и напряжение — без них день не сохранить.";
    return;
  }
  err.textContent = "";
  const body = {
    sleep_hours: form.sleep_hours, sleep_quality: form.sleep_quality, mood: form.mood, stress: form.stress,
    energy: form.energy, study_hours: form.study_hours, screen_hours: form.screen_hours, activity_min: form.activity_min,
    tags: $$("#tags button.on").map((b) => b.dataset.tag),
    note: $("#checkin-form textarea").value,
  };
  const btn = $("#save-btn");
  btn.disabled = true;
  try {
    await api(`/checkins/${state.day}`, { method: "PUT", body });
    await reload();
    selectDay(state.day);
    toast(state.day === state.today ? "Сохранено. Спасибо, что отметился." : "День сохранён.");
    if (window.innerWidth < 900) $("#today-side").scrollIntoView({ behavior: "smooth" });
  } catch (ex) {
    err.textContent = ex.message;
  } finally {
    btn.disabled = false;
  }
}

async function deleteDay() {
  const b = $("#delete-day");
  if (b.dataset.confirm !== "1") { b.dataset.confirm = "1"; b.textContent = "Точно удалить? Нажми ещё раз"; return; }
  b.dataset.confirm = ""; b.textContent = "Удалить отметку за этот день";
  await api(`/checkins/${state.day}`, { method: "DELETE" });
  await reload();
  selectDay(state.day);
  toast("Отметка удалена.");
}

// ---------------------------------------------------------------------------
// Боковая колонка «Сегодня»
// ---------------------------------------------------------------------------

function overloadMini(ov) {
  if (!ov) {
    return el("div", { class: "card" }, el("p", { class: "eyebrow" }, "Индекс перегрузки"),
      el("p", { style: "margin:0" }, "Появится, когда за последнюю неделю будет хотя бы 4 отметки."));
  }
  return el("div", { class: "card" },
    el("div", { style: "display:flex;justify-content:space-between;align-items:center;gap:10px" },
      el("p", { class: "eyebrow", style: "margin:0" }, "Индекс перегрузки"), el("span", { class: `pill ${LEVEL_PILL[ov.level]}` }, ov.label)),
    el("div", { class: "overload", style: "grid-template-columns:auto 1fr;margin-top:10px" },
      el("div", { class: "big", style: "font-size:48px" }, ov.score),
      el("div", {}, el("div", { class: "meter" }, el("i", { style: `left:${ov.score}%` })),
        el("div", { class: "meter-labels" }, el("span", {}, "ровно"), el("span", {}, "присмотреться"), el("span", {}, "перегрузка")))),
    ov.reasons.length ? el("p", { class: "small", style: "margin:12px 0 0" }, "Из чего сложилось: ", ov.reasons.join(", "), ".") : null,
    el("p", { class: "small muted", style: "margin:6px 0 0" }, el("a", { href: "#picture" }, "Подробнее в «Моей картине»")));
}

function careCard(care) {
  if (!care) return null;
  return el("div", { class: "card care" },
    el("h3", {}, "Похоже, неделя была тяжёлой"),
    el("p", {}, care.text),
    el("p", { class: "small muted" }, "Почему мы это показываем: ", care.reasons.join("; "), "."),
    el("div", { class: "phones" }, ...care.contacts.map((c) =>
      el("div", { class: "phone" }, el("b", {}, c.phone), el("span", { class: "small" }, c.name), el("div", { class: "tiny muted" }, c.note)))));
}

function renderTodaySide() {
  const ins = state.insights;
  const side = $("#today-side");
  const s = ins.summary;
  const parts = [];
  parts.push(careCard(ins.care));

  if (s.logged_today && ins.anomalies.length) {
    parts.push(el("div", { class: "card" }, el("p", { class: "eyebrow" }, "Сегодня выделяется"),
      ...ins.anomalies.map((a) => el("div", { class: `anomaly ${a.good ? "good" : ""}` }, el("i"), el("span", {}, a.text)))));
  } else if (s.logged_today) {
    parts.push(el("div", { class: "card" }, el("p", { class: "eyebrow" }, "Сегодня"),
      el("p", { style: "margin:0" }, "Обычный для тебя день: ничего не выбивается из твоей нормы.")));
  }

  parts.push(overloadMini(ins.overload));

  const streakText = s.streak > 0 ? `${s.streak} ${plural(s.streak, "день", "дня", "дней")} подряд` : "Серия начнётся с сегодняшней отметки";
  const pCount = ins.patterns.patterns.length;
  const left = Math.max(0, 14 - ins.patterns.days);
  parts.push(el("div", { class: "card" },
    el("p", { class: "eyebrow" }, "Дневник"),
    el("p", { style: "margin:0 0 6px" }, el("b", {}, streakText), ` · всего ${s.total_days} ${plural(s.total_days, "отметка", "отметки", "отметок")}`),
    left > 0
      ? el("p", { class: "small muted", style: "margin:0" }, `Закономерности начнём искать через ${left} ${plural(left, "день", "дня", "дней")} отметок.`)
      : el("p", { class: "small", style: "margin:0" }, pCount
        ? [`Найдено ${pCount} ${plural(pCount, "закономерность", "закономерности", "закономерностей")}. `, el("a", { href: "#patterns" }, "Посмотреть")]
        : "Устойчивых закономерностей пока нет. Это тоже результат.")));
  side.replaceChildren(...parts.filter(Boolean));
  side.style.display = "grid"; side.style.gap = "16px";
  $$(".card + .card", side).forEach((c) => (c.style.marginTop = "0"));
}

// ---------------------------------------------------------------------------
// Моя картина
// ---------------------------------------------------------------------------

function lastNDates(n) {
  const out = [];
  for (let i = n - 1; i >= 0; i--) out.push(addDays(state.today, -i));
  return out;
}

function renderPicture() {
  const ins = state.insights;
  const box = $("#picture");
  if (!state.checkins.length) {
    box.replaceChildren(el("div", { class: "card empty-state" }, el("span", { class: "hand" }, "Пока пусто"),
      el("p", {}, "Отметь первый день, и здесь появятся графики."), el("a", { class: "btn", href: "#today" }, "Отметить день")));
    return;
  }
  const ov = ins.overload;
  const top = el("div", { class: "grid picture-top" });
  // карточка индекса
  top.append(ov
    ? el("div", { class: "card" },
      el("div", { style: "display:flex;justify-content:space-between;gap:10px;align-items:center" },
        el("p", { class: "eyebrow", style: "margin:0" }, "Индекс перегрузки за 7 дней"), el("span", { class: `pill ${LEVEL_PILL[ov.level]}` }, ov.label)),
      el("div", { class: "overload", style: "margin-top:12px" },
        el("div", { class: "big" }, ov.score, el("small", {}, " / 100")),
        el("div", {}, el("div", { class: "meter" }, el("i", { style: `left:${ov.score}%` })),
          el("div", { class: "meter-labels" }, el("span", {}, "0"), el("span", {}, "35"), el("span", {}, "60"), el("span", {}, "100")))),
      el("p", { style: "margin:14px 0 6px" }, ov.advice),
      ov.reasons.length ? el("ul", { class: "reasons" }, ...ov.reasons.map((r) => el("li", { class: "pill" }, r))) : null,
      el("p", { class: "tiny muted", style: "margin:12px 0 0" }, "Это не диагноз, а сигнал «присмотрись». Как считается — на странице ", el("a", { href: "/method#overload" }, "«Методика»"), "."))
    : el("div", { class: "card" }, el("p", { class: "eyebrow" }, "Индекс перегрузки"), el("p", {}, "Нужно хотя бы 4 отметки за последние 7 дней.")));

  const wm = ov ? ov.week_means : {};
  const stats = el("div", { class: "grid stats2", style: "gap:12px" },
    stat(fmt(wm.sleep_hours), "ч сна в среднем за неделю"),
    stat(fmt(wm.stress), "стресс в среднем, из 5"),
    stat(ins.summary.streak, plural(ins.summary.streak, "день подряд", "дня подряд", "дней подряд")),
    stat(ins.summary.total_days, plural(ins.summary.total_days, "день в дневнике", "дня в дневнике", "дней в дневнике")));
  top.append(stats);

  const parts = [careCard(ins.care), top];

  // графики
  const dates = lastNDates(35);
  const val = (f) => dates.map((d) => (state.byDate.has(d) ? state.byDate.get(d)[f] : null));
  const markers = dates.filter((d) => state.byDate.has(d) && state.byDate.get(d).tags.some((t) => ["контрольная", "экзамен", "олимпиада"].includes(t)))
    .map((d) => ({ date: d, text: state.byDate.get(d).tags.find((t) => ["контрольная", "экзамен", "олимпиада"].includes(t)) }));
  const b = ins.baseline;
  const chartBox = el("div", { class: "chart" });
  parts.push(el("div", { class: "card" },
    el("h3", {}, "Как шли дни"),
    el("p", { class: "small muted" }, "Пунктир — твоя обычная норма (медиана за 4 недели). Наведи на график, чтобы увидеть конкретный день."),
    chartBox,
    el("div", { class: "chart-legend" }, el("span", {}, el("i", { class: "dash" }), "твоя норма"), el("span", { style: "color:#c2502e" }, el("i"), "контрольные и экзамены"))));
  smallMultiples(chartBox, {
    dates, markers,
    series: [
      { label: "Сон, ч", color: METRIC.sleep_hours.hex, min: 4, max: 11, values: val("sleep_hours"), median: b.sleep_hours?.median, ref: { value: 8, label: "8 ч" }, fmt: (v) => `${fmt(v)} ч` },
      { label: "Настроение", color: METRIC.mood.hex, min: 1, max: 5, values: val("mood"), median: b.mood?.median, fmt: (v) => `${v} из 5` },
      { label: "Стресс", color: METRIC.stress.hex, min: 1, max: 5, values: val("stress"), median: b.stress?.median, fmt: (v) => `${v} из 5` },
      { label: "Энергия", color: METRIC.energy.hex, min: 1, max: 5, values: val("energy"), median: b.energy?.median, fmt: (v) => `${v} из 5` },
    ],
  });

  const ovBox = el("div", { class: "chart" });
  parts.push(el("div", { class: "card" }, el("h3", {}, "Индекс перегрузки по дням"),
    el("p", { class: "small muted" }, "Каждая точка — индекс за 7 дней до этой даты. Зелёная зона — ровно, жёлтая — присмотрись, красная — перегрузка."), ovBox));
  overloadChart(ovBox, ins.overload_history);

  const cal = el("div", { class: "chart", style: "max-width:340px" });
  const wd = el("div", { class: "chart" });
  const wdNote = ins.weekday?.note ? el("p", { style: "margin:10px 0 0" }, ins.weekday.note) : null;
  parts.push(el("div", { class: "grid g2" },
    el("div", { class: "card" }, el("h3", {}, "Настроение по дням"), el("p", { class: "small muted" }, "Последние 12 недель. Чем зеленее, тем лучше."), cal,
      el("div", { class: "chart-legend" }, ...[[1, "#b2412f"], [2, "#d98c6a"], [3, "#e3d6b4"], [4, "#9dbf92"], [5, "#4f7a58"]].map(([n, c]) =>
        el("span", {}, el("i", { style: `background:${c};height:10px;width:10px;border-radius:3px` }), n)))),
    el("div", { class: "card" }, el("h3", {}, "Стресс по дням недели"), el("p", { class: "small muted" }, "Среднее за 10 недель."), wd, wdNote)));
  const allDates = state.checkins.map((c) => c.date);
  moodCalendar(cal, { dates: allDates, values: state.checkins.map((c) => c.mood), today: state.today });
  if (ins.weekday) {
    const rows = ins.weekday.days.map((d) => ({ day: d.day, value: d.stress }));
    const valid = rows.filter((r) => r.value !== null);
    const maxV = Math.max(...valid.map((r) => r.value));
    rows.forEach((r) => (r.highlight = r.value === maxV));
    weekdayBars(wd, rows, { color: METRIC.stress.hex });
  } else {
    wd.replaceChildren(el("p", { class: "muted" }, "Нужно хотя бы две недели отметок."));
  }
  box.replaceChildren(...parts.filter(Boolean));
}

function stat(v, label) {
  return el("div", { class: "card stat", style: "margin:0" }, el("div", { class: "v" }, v), el("div", { class: "l" }, label));
}

// ---------------------------------------------------------------------------
// Закономерности
// ---------------------------------------------------------------------------

function compareBars(p) {
  const m = METRIC[p.outcome] || METRIC.stress;
  const max = m.max === 11 ? Math.max(p.low_mean, p.high_mean) * 1.15 : 5;
  const unit = m.unit === "/5" ? "" : ` ${m.unit}`;
  const row = (label, v, n) => el("div", { class: "bar" },
    el("span", {}, `${label} · ${n} ${plural(n, "день", "дня", "дней")}`),
    el("div", { class: "track" }, el("div", { class: "fill", style: `width:${Math.max(12, (v / max) * 100)}%;background:${m.hex}` }, `${fmt(v)}${unit}`)));
  const [lowLabel, highLabel] = {
    sleep_hours: ["меньше 7 ч сна", "7 ч и больше"],
    screen_hours: ["экрана меньше", "экрана больше"],
    activity_min: ["< 30 мин движения", "30 мин и больше"],
    study_hours: ["учёбы меньше", "учёбы больше"],
  }[p.driver];
  return el("div", { class: "cmp" }, el("div", { class: "tiny muted" }, `${m.label}${p.lag ? " (на следующий день)" : ""}`),
    row(lowLabel, p.low_mean, p.n_low), row(highLabel, p.high_mean, p.n_high));
}

function patternCard(p) {
  return el("div", { class: "card pattern" },
    el("div", {},
      el("p", { class: "eyebrow" }, p.title, p.level === "hint" ? " · пока намёк" : ""),
      el("p", {}, p.text),
      el("p", { class: "fine" }, p.fine_print)),
    compareBars(p));
}

function renderPatterns() {
  const pt = state.insights.patterns;
  const box = $("#patterns");
  if (pt.days < 14) {
    const left = 14 - pt.days;
    box.replaceChildren(el("div", { class: "card empty-state" },
      el("span", { class: "hand" }, `Ещё ${left} ${plural(left, "день", "дня", "дней")}`),
      el("p", {}, "Закономерности появятся после 14 дней отметок. На меньшем числе дней любая «находка» может оказаться случайностью."),
      el("div", { class: "progress", style: "max-width:320px;margin:14px auto 0" }, el("i", { style: `width:${(pt.days / 14) * 100}%` }))));
    return;
  }
  const parts = [el("p", { class: "lead", style: "margin-bottom:20px" },
    `Мы проверили ${pt.tested} ${plural(pt.tested, "возможную связь", "возможные связи", "возможных связей")} на твоих данных за ${pt.days} ${plural(pt.days, "день", "дня", "дней")}. `,
    pt.patterns.length ? "Вот что прошло проверку:" : "Пока ни одна связь не прошла проверку. Значит, данных мало или у тебя эти вещи действительно не связаны.")];
  pt.patterns.forEach((p) => parts.push(patternCard(p)));
  if (pt.hints.length) {
    parts.push(el("h3", { style: "margin:34px 0 6px" }, "Пока только намёки"),
      el("p", { class: "muted small" }, "Эти связи слабее и могут оказаться случайностью. Если они настоящие, со временем перейдут в раздел выше."));
    pt.hints.forEach((p) => parts.push(patternCard(p)));
  }
  parts.push(el("div", { class: "card", style: "margin-top:28px;background:transparent;box-shadow:none" },
    el("p", { class: "eyebrow" }, "Как читать"),
    el("p", { style: "margin:0" }, "Здесь описаны связи, а не причины. Если после короткого сна стресс выше, возможно, дело в третьем факторе, например в контрольных, из-за которых и спишь меньше, и нервничаешь больше. Чтобы проверить, помогает ли конкретное изменение, запусти ",
      el("a", { href: "#experiments" }, "эксперимент"), ". Подробности о статистике есть на странице ", el("a", { href: "/method#patterns" }, "«Методика»"), ".")));
  box.replaceChildren(...parts);
  $$(".card + .card", box).forEach((c) => (c.style.marginTop = "14px"));
}

// ---------------------------------------------------------------------------
// Эксперименты
// ---------------------------------------------------------------------------

const PRESETS = [
  { title: "Без телефона за час до сна", metric: "sleep_quality", why: "Смотрим на качество сна" },
  { title: "Ложиться на 30 минут раньше", metric: "energy", why: "Смотрим на энергию" },
  { title: "20 минут пешком каждый день", metric: "mood", why: "Смотрим на настроение" },
  { title: "Домашка блоками по 25 минут с перерывами", metric: "stress", why: "Смотрим на стресс" },
  { title: "Без кофе и энергетиков после 16:00", metric: "sleep_quality", why: "Смотрим на качество сна" },
  { title: "Не проверять телефон первые 30 минут утра", metric: "mood", why: "Смотрим на настроение" },
];
const VERDICT_PILL = { helped: ["good", "Помогло"], worse: ["bad", "Стало хуже"], unclear: ["", "Непонятно"], not_enough: ["", "Мало данных"], collecting: ["watch", "Идёт"] };

function experimentCard(x) {
  const [pill, label] = VERDICT_PILL[x.verdict] || ["", ""];
  const pct = Math.min(100, (x.days_logged / x.days_total) * 100);
  const del = el("button", { type: "button", class: "linkbtn tiny" }, "удалить");
  del.addEventListener("click", async () => {
    if (del.dataset.c !== "1") { del.dataset.c = "1"; del.textContent = "точно удалить?"; return; }
    await api(`/experiments/${x.id}`, { method: "DELETE" });
    await reload();
  });
  return el("div", { class: "card exp" },
    el("div", {},
      el("p", { class: "eyebrow" }, `${dayShort(x.start_date)} — ${dayShort(x.end_date)} · смотрим на: ${x.metric_label}`),
      el("h3", {}, x.title),
      el("div", { class: "progress", style: "max-width:360px" }, el("i", { style: `width:${pct}%` })),
      el("p", { class: "tiny muted", style: "margin:0" }, `Отмечено ${x.days_logged} из ${x.days_total} ${plural(x.days_total, "дня", "дней", "дней")}`),
      el("p", { class: "verdict" }, x.text),
      x.p !== null ? el("p", { class: "tiny muted", style: "margin:4px 0 0" }, `До: ${fmt(x.before_mean)}, во время: ${fmt(x.during_mean)} (тест Манна–Уитни, p = ${fmt(x.p, 3)})`) : null),
    el("div", { style: "text-align:right" }, el("span", { class: `pill ${pill}` }, label), el("div", { style: "margin-top:10px" }, del)));
}

function renderExperiments() {
  const box = $("#experiments");
  const active = state.experiments.filter((x) => !x.finished);
  const done = state.experiments.filter((x) => x.finished);
  const parts = [];
  parts.push(el("p", { class: "lead", style: "margin-bottom:20px" },
    "Выбери одно маленькое изменение на неделю или две. EdiEdu сравнит нужный показатель за 14 дней до старта и во время эксперимента и скажет, есть ли разница."));

  if (active.length) { parts.push(el("h3", {}, "Сейчас идёт")); active.forEach((x) => parts.push(experimentCard(x))); }

  if (active.length < 2) {
    const grid = el("div", { class: "grid g3", style: "margin:10px 0 8px" });
    PRESETS.forEach((p) => {
      const b = el("button", { type: "button", class: "preset" }, el("b", {}, p.title), el("span", {}, p.why));
      b.addEventListener("click", () => startExperiment(p.title, p.metric, 7));
      grid.append(b);
    });
    const title = el("input", { type: "text", maxlength: 80, placeholder: "Своя идея, например: 10 минут растяжки перед сном" });
    const metric = el("select", {}, ...Object.entries({ sleep_quality: "качество сна", sleep_hours: "сон, часы", mood: "настроение", stress: "стресс", energy: "энергия" })
      .map(([v, t]) => el("option", { value: v }, t)));
    const days = el("select", {}, el("option", { value: 7 }, "7 дней"), el("option", { value: 10 }, "10 дней"), el("option", { value: 14 }, "14 дней"));
    const go = el("button", { type: "button", class: "btn" }, "Начать");
    go.addEventListener("click", () => startExperiment(title.value.trim(), metric.value, +days.value));
    parts.push(el("h3", { style: "margin-top:26px" }, "Начать новый"), grid,
      el("div", { class: "card", style: "margin-top:14px" },
        el("p", { class: "eyebrow" }, "Свой эксперимент"),
        el("div", { style: "display:grid;grid-template-columns:1fr auto auto auto;gap:10px;align-items:center" }, title, metric, days, go)));
  } else {
    parts.push(el("p", { class: "muted" }, "Одновременно можно вести не больше двух экспериментов, иначе не понять, что именно сработало."));
  }

  if (done.length) { parts.push(el("h3", { style: "margin-top:34px" }, "Завершённые")); done.forEach((x) => parts.push(experimentCard(x))); }
  parts.push(el("p", { class: "tiny muted", style: "margin-top:24px" },
    "Честно: это эксперимент на одном человеке без контрольной группы. Если в те же дни были каникулы или контрольные, они тоже повлияют на результат. Поэтому мы пишем «похоже, работает», а не «доказано»."));
  box.replaceChildren(...parts);
  $$(".card + .card", box).forEach((c) => (c.style.marginTop = "14px"));
  // на узком экране — в столбик
  if (window.innerWidth < 700) $$("#experiments [style*='grid-template-columns:1fr auto']").forEach((g) => (g.style.gridTemplateColumns = "1fr"));
}

async function startExperiment(title, metric, days) {
  if (title.length < 3) { toast("Напиши, что именно будешь пробовать."); return; }
  try {
    await api("/experiments", { method: "POST", body: { title, metric, days } });
    await reload();
    toast("Эксперимент начался. Отмечай дни как обычно.");
  } catch (ex) { toast(ex.message); }
}

// ---------------------------------------------------------------------------
// Профиль
// ---------------------------------------------------------------------------

function renderProfile() {
  const me = state.me;
  const box = $("#profile");
  const name = el("input", { type: "text", maxlength: 40, value: me.display_name || "" });
  const saveName = el("button", { type: "button", class: "btn small" }, "Сохранить");
  saveName.addEventListener("click", async () => {
    await api("/me", { method: "PATCH", body: { display_name: name.value } });
    state.me = await api("/me");
    $("#hello").textContent = `Привет, ${state.me.display_name || state.me.username}`;
    toast("Имя сохранено.");
  });

  // школа
  let schoolBlock;
  if (me.class_name) {
    const leave = el("button", { type: "button", class: "btn small ghost" }, "Выйти из класса");
    leave.addEventListener("click", async () => { await api("/me/leave-class", { method: "POST" }); state.me = await api("/me"); renderProfile(); toast("Ты больше не в классе."); });
    schoolBlock = el("div", {}, el("p", {}, "Ты в классе ", el("b", {}, me.class_name), ` · ${me.school_name}`), leave);
  } else {
    const code = el("input", { type: "text", placeholder: "Например: DEMO-10B", maxlength: 12, style: "max-width:220px" });
    const join = el("button", { type: "button", class: "btn small" }, "Присоединиться");
    join.addEventListener("click", async () => {
      try { await api("/me/join-class", { method: "POST", body: { code: code.value.trim() } }); state.me = await api("/me"); renderProfile(); toast("Готово!"); }
      catch (ex) { toast(ex.message); }
    });
    schoolBlock = el("div", {}, el("p", { class: "small muted" }, "Код класса выдаёт школьный психолог. Можно и без класса: дневник работает полностью."),
      el("div", { style: "display:flex;gap:10px;flex-wrap:wrap" }, code, join));
  }

  const share = el("input", { type: "checkbox" });
  share.checked = me.share_with_school;
  share.addEventListener("change", async () => {
    await api("/me", { method: "PATCH", body: { share_with_school: share.checked } });
    state.me.share_with_school = share.checked;
    toast(share.checked ? "Твои цифры будут учитываться в среднем по классу." : "Школа больше не получает твои данные.");
  });

  const exportBtn = el("button", { type: "button", class: "btn small ghost" }, "Скачать мои данные (JSON)");
  exportBtn.addEventListener("click", async () => {
    const res = await fetch("/api/me/export", { headers: { Authorization: `Bearer ${auth.token}` } });
    const blob = await res.blob();
    const a = el("a", { href: URL.createObjectURL(blob), download: "edieedu-export.json" });
    document.body.append(a); a.click(); a.remove();
  });
  const delBtn = el("button", { type: "button", class: "btn small danger" }, "Удалить аккаунт и все данные");
  delBtn.addEventListener("click", async () => {
    if (delBtn.dataset.c !== "1") { delBtn.dataset.c = "1"; delBtn.textContent = "Это необратимо. Нажми ещё раз, чтобы удалить"; return; }
    await api("/me", { method: "DELETE" });
    auth.clear();
    location.href = "/";
  });

  box.replaceChildren(el("div", { class: "grid g2" },
    el("div", { class: "card" }, el("h3", {}, "Как к тебе обращаться"),
      el("div", { style: "display:flex;gap:10px" }, name, saveName),
      el("p", { class: "tiny muted", style: "margin:10px 0 0" }, `Логин: ${me.username}`)),
    el("div", { class: "card" }, el("h3", {}, "Школа"), schoolBlock),
    el("div", { class: "card" }, el("h3", {}, "Делиться со школой"),
      el("label", { class: "switch" }, share, el("span", {}, "Учитывать мои отметки в анонимной статистике класса")),
      el("p", { class: "small", style: "margin:14px 0 4px" }, el("b", {}, "Психолог увидит: "), "средний сон, стресс и настроение по классу за неделю, но только если в классе хотя бы 5 таких учеников."),
      el("p", { class: "small", style: "margin:0" }, el("b", {}, "Психолог не увидит: "), "твоё имя, логин, отдельные дни, заметки и то, отмечался ли ты вообще.")),
    el("div", { class: "card" }, el("h3", {}, "Мои данные"),
      el("p", { class: "small" }, "Всё, что ты отмечал, можно скачать одним файлом. Удаление аккаунта стирает всё сразу, без «корзины» и без 30 дней ожидания."),
      el("div", { style: "display:flex;gap:10px;flex-wrap:wrap" }, exportBtn, delBtn))));
}

boot().catch((e) => {
  console.error(e);
  $("main").prepend(el("div", { class: "card", style: "margin-top:20px" }, el("b", {}, "Не получилось загрузить данные. "), e.message || ""));
});
