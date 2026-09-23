import { $, $$, api, auth, toast } from "./api.js";

const modal = $("#auth");

function openModal(tab) {
  switchTab(tab);
  modal.classList.add("open");
  setTimeout(() => $(`#form-${tab} input:not([type=hidden])`)?.focus(), 30);
}
function closeModal() { modal.classList.remove("open"); }
function switchTab(tab) {
  $$(".tabs-mini button", modal).forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
  $("#form-login").hidden = tab !== "login";
  $("#form-register").hidden = tab !== "register";
}

$$("[data-open]").forEach((b) => b.addEventListener("click", () => openModal(b.dataset.open)));
$$(".tabs-mini button", modal).forEach((b) => b.addEventListener("click", () => switchTab(b.dataset.tab)));
$("[data-close]", modal).addEventListener("click", closeModal);
modal.addEventListener("click", (e) => { if (e.target === modal) closeModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

async function afterLogin() {
  const me = await api("/me");
  location.href = me.role === "staff" ? "/school" : "/app";
}

function bindForm(id, path) {
  const form = $(id);
  const err = $(".form-error", form);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    err.textContent = "";
    const btn = $("button:not([type=button])", form);
    btn.disabled = true;
    const data = Object.fromEntries(new FormData(form));
    if (data.display_name === "") delete data.display_name;
    try {
      const { token } = await api(path, { method: "POST", body: data });
      auth.set(token);
      await afterLogin();
    } catch (ex) {
      err.textContent = ex.message;
      btn.disabled = false;
    }
  });
}
bindForm("#form-login", "/auth/login");
bindForm("#form-register", "/auth/register");

$$("[data-demo]").forEach((b) => b.addEventListener("click", async () => {
  const kind = b.dataset.demo;
  const old = b.textContent;
  b.disabled = true;
  b.textContent = "Готовим демо…";
  try {
    const { token } = await api(kind === "school" ? "/auth/demo-school" : "/auth/demo", { method: "POST" });
    auth.set(token);
    location.href = kind === "school" ? "/school" : "/app";
  } catch (ex) {
    b.textContent = old;
    b.disabled = false;
    toast(ex.message);
  }
}));
