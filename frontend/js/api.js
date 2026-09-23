// Общение с сервером + мелкие помощники, которые нужны на всех страницах.

const TOKEN_KEY = "edieedu_token";

export const auth = {
  get token() { try { return localStorage.getItem(TOKEN_KEY); } catch { return null; } },
  set(token) { try { localStorage.setItem(TOKEN_KEY, token); } catch { /* приватный режим */ } },
  clear() { try { localStorage.removeItem(TOKEN_KEY); } catch { /* ничего */ } },
};

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export async function api(path, { method = "GET", body } = {}) {
  const headers = { "Accept": "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (auth.token) headers["Authorization"] = `Bearer ${auth.token}`;
  let res;
  try {
    res = await fetch(`/api${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "Нет связи с сервером. Проверь интернет.");
  }
  let data = null;
  try { data = await res.json(); } catch { /* пустой ответ */ }
  if (!res.ok) {
    throw new ApiError(res.status, humanError(data, res.status));
  }
  return data;
}

function humanError(data, status) {
  const d = data && data.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d) && d.length) {
    const field = (d[0].loc || []).slice(-1)[0];
    const names = { username: "логин", password: "пароль", note: "заметка", tags: "метки", title: "название" };
    if (field === "password") return "Пароль должен быть не короче 8 символов.";
    if (field === "username") return "Логин: 3–32 символа, латиница, цифры, точка, дефис или подчёркивание.";
    return `Проверь поле «${names[field] || field}».`;
  }
  if (status === 429) return "Слишком много попыток. Подожди немного.";
  return "Что-то пошло не так. Попробуй ещё раз.";
}

// ---------- форматирование ----------
export const fmt = (x, digits = 1) =>
  x === null || x === undefined || Number.isNaN(x) ? "—" :
  Number(x).toFixed(digits).replace(/\.0+$/, "").replace(".", ",");

const MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];
const MONTHS_SHORT = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
export const WEEKDAYS_SHORT = ["Вс", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"];

export const parseDate = (iso) => { const [y, m, d] = iso.split("-").map(Number); return new Date(y, m - 1, d); };
export const isoDate = (dt) => `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;
export const addDays = (iso, n) => { const d = parseDate(iso); d.setDate(d.getDate() + n); return isoDate(d); };
export const dayLong = (iso) => { const d = parseDate(iso); return `${d.getDate()} ${MONTHS[d.getMonth()]}`; };
export const dayShort = (iso) => { const d = parseDate(iso); return `${d.getDate()} ${MONTHS_SHORT[d.getMonth()]}`; };

export function plural(n, one, few, many) {
  const a = Math.abs(n) % 100, b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b > 1 && b < 5) return few;
  if (b === 1) return one;
  return many;
}

// ---------- DOM ----------
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

// Создание элементов без innerHTML с пользовательскими данными — защита от XSS.
export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "style") node.setAttribute("style", v);
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else if (k === "dataset") Object.assign(node.dataset, v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

let toastTimer;
export function toast(text) {
  let t = $(".toast");
  if (!t) { t = el("div", { class: "toast", role: "status" }); document.body.append(t); }
  t.textContent = text;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 2600);
}
