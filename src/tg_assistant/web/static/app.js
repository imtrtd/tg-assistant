"use strict";

let tg = null;
let inTelegram = false;

/* Скрипт Telegram подключаем, только если страницу открыл Telegram: обычному браузеру он не нужен. */
function openedByTelegram() {
  if (/tgWebApp/.test(location.hash) || window.TelegramWebviewProxy) return true;
  try {
    return Boolean(sessionStorage.getItem("__telegram__initParams"));
  } catch {
    return false;
  }
}

function loadTelegram() {
  if (!openedByTelegram()) return Promise.resolve();
  return new Promise((resolve) => {
    const script = document.createElement("script");
    const done = () => {
      tg = (window.Telegram && window.Telegram.WebApp) || null;
      inTelegram = Boolean(tg && tg.initData);
      resolve();
    };
    script.src = "https://telegram.org/js/telegram-web-app.js";
    script.onload = done;
    script.onerror = done;
    setTimeout(done, 5000);
    document.head.append(script);
  });
}

const ICONS = {
  edit: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>',
  trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/></svg>',
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
  repeat: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/></svg>',
  logout: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/></svg>',
  note: '<svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><rect x="12" y="8" width="40" height="48" rx="8"/><path d="M22 22h20M22 32h20M22 42h11"/></svg>',
  bell: '<svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M16 44V29a16 16 0 0 1 32 0v15l4 6H12Z"/><path d="M27 54a5 5 0 0 0 10 0"/><path d="M32 8v5"/></svg>',
  logo: '<svg viewBox="0 0 64 64"><defs><linearGradient id="lg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#6d7dff"/><stop offset="1" stop-color="#3f5bf0"/></linearGradient></defs><rect width="64" height="64" fill="url(#lg)"/><path d="M19 33.5l9 9 17-20" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
};

const CHIPS = ["через час", "сегодня в 18:00", "завтра в 9", "каждый день 8:00", "по будням 9:30"];

const state = { me: null, notes: [], notesTotal: 0, query: "", reminders: [], chip: "" };
const seen = { notes: new Set(), reminders: new Set() };
const $ = (id) => document.getElementById(id);

/* --- вспомогательное ------------------------------------------------------ */

function el(tag, props, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (key === "class") node.className = value;
    else if (key === "html") node.innerHTML = value; // только константы из ICONS
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value !== false && value != null) node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child != null) node.append(child);
  }
  return node;
}

async function api(method, path, body) {
  const headers = {};
  if (inTelegram) headers.Authorization = `tma ${tg.initData}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let response;
  try {
    response = await fetch(path, {
      method,
      headers,
      credentials: "same-origin",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new Error("Нет связи с сервером");
  }
  let data = null;
  try {
    data = await response.json();
  } catch {
    /* пустой ответ */
  }
  if (!response.ok) {
    const error = new Error((data && data.error) || `Ошибка ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return data;
}

let toastTimer;
function toast(message, isError) {
  const node = $("toast");
  node.textContent = message;
  node.className = `toast show${isError ? " error" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (node.className = "toast"), isError ? 4500 : 2600);
  const haptic = tg && tg.HapticFeedback;
  if (inTelegram && haptic) haptic.notificationOccurred(isError ? "error" : "success");
}

const fail = (error) => {
  if (error.status === 401 || error.status === 403) showGate(error);
  else toast(error.message, true);
};

function autoGrow(textarea) {
  textarea.style.height = "auto";
  textarea.style.height = `${textarea.scrollHeight}px`;
}

function formatter(options) {
  try {
    return new Intl.DateTimeFormat("ru", { ...options, timeZone: state.me.timezone });
  } catch {
    return new Intl.DateTimeFormat("ru", options);
  }
}

const dayKey = (date) => formatter({ year: "numeric", month: "2-digit", day: "2-digit" }).format(date);

/* Текст заметки: #теги — кнопки поиска, ссылки — ссылки. Только textContent, без innerHTML. */
function richText(text) {
  const parts = text.split(/(https?:\/\/[^\s<>"']+|#[\p{L}\p{N}_]+)/gu);
  return parts.map((part, index) => {
    if (index % 2 === 0) return part;
    if (part.startsWith("#")) {
      return el("button", { class: "tag", type: "button", onclick: () => setQuery(part) }, part);
    }
    return el("a", { href: part, target: "_blank", rel: "noopener noreferrer" }, part);
  });
}

/* Удаление в два нажатия: первое превращает кнопку в «Удалить?», второе удаляет. */
function deleteButton(label, onConfirm) {
  let timer;
  const button = el("button", { class: "act", type: "button", "aria-label": label, title: label, html: ICONS.trash });
  button.addEventListener("click", () => {
    if (button.classList.contains("confirm")) {
      clearTimeout(timer);
      onConfirm();
      return;
    }
    button.classList.add("confirm");
    button.textContent = "Удалить?";
    timer = setTimeout(() => {
      button.classList.remove("confirm");
      button.innerHTML = ICONS.trash;
    }, 3000);
  });
  return button;
}

/* Карточка, которую ещё не показывали, получает анимацию появления. */
function makeCard(kind, id, extraClass) {
  const node = el("article", { class: `card${extraClass ? ` ${extraClass}` : ""}` });
  if (!seen[kind].has(id)) node.classList.add("enter");
  seen[kind].add(id);
  return node;
}

function removeCard(card, after) {
  card.classList.add("leaving");
  setTimeout(after, 180);
}

function emptyState(icon, title, hint) {
  return el("div", { class: "empty" }, el("div", { html: icon }), el("b", {}, title), el("span", {}, hint));
}

function skeletons(target) {
  target.replaceChildren(el("div", { class: "skeleton" }), el("div", { class: "skeleton" }));
}

/* --- заметки -------------------------------------------------------------- */

function noteCard(note) {
  const card = makeCard("notes", note.id);
  const dateFormat = formatter({ day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

  const view = () => {
    card.classList.remove("editing");
    const edited = note.updated_at ? " · изменена" : "";
    card.replaceChildren(
      el("p", { class: "card-text" }, richText(note.text)),
      el(
        "div",
        { class: "card-foot" },
        el("span", {}, dateFormat.format(new Date(note.created_at)) + edited),
        el("span", { class: "spacer" }),
        el("button", { class: "act", type: "button", "aria-label": "Изменить", title: "Изменить", html: ICONS.edit, onclick: edit }),
        deleteButton("Удалить заметку", remove),
      ),
    );
  };

  const edit = () => {
    card.classList.add("editing");
    const area = el("textarea", { rows: "1", maxlength: "4000", "aria-label": "Текст заметки" });
    area.value = note.text;
    area.addEventListener("input", () => autoGrow(area));
    area.addEventListener("keydown", (event) => {
      if (event.key === "Escape") view();
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) save();
    });
    const save = async () => {
      const text = area.value.trim();
      if (!text || text === note.text) return view();
      try {
        Object.assign(note, await api("PUT", `/api/notes/${note.id}`, { text }));
        view();
        toast("Заметка обновлена");
      } catch (error) {
        fail(error);
      }
    };
    card.replaceChildren(
      area,
      el(
        "div",
        { class: "card-foot" },
        el("span", { class: "spacer" }),
        el("button", { class: "btn plain", type: "button", onclick: view }, "Отмена"),
        el("button", { class: "btn ghost", type: "button", onclick: save }, "Сохранить"),
      ),
    );
    autoGrow(area);
    area.focus();
    area.setSelectionRange(area.value.length, area.value.length);
  };

  const remove = async () => {
    try {
      await api("DELETE", `/api/notes/${note.id}`);
      removeCard(card, () => {
        state.notes = state.notes.filter((item) => item.id !== note.id);
        state.notesTotal -= 1;
        renderNotes();
      });
    } catch (error) {
      fail(error);
    }
  };

  view();
  return card;
}

function renderNotes() {
  const list = $("notes");
  if (!state.notes.length) {
    list.replaceChildren(
      state.query
        ? emptyState(ICONS.note, "Ничего не найдено", "Попробуйте другое слово или тег")
        : emptyState(ICONS.note, "Заметок пока нет", "Напишите первую в поле выше"),
    );
  } else {
    list.replaceChildren(...state.notes.map(noteCard));
  }
  $("count-notes").textContent = state.query ? "" : state.notesTotal || "";
  $("more").hidden = Boolean(state.query) || state.notes.length >= state.notesTotal;
}

async function loadNotes(append) {
  const query = state.query;
  const params = new URLSearchParams(query ? { q: query } : { offset: append ? state.notes.length : 0 });
  try {
    const data = await api("GET", `/api/notes?${params}`);
    if (query !== state.query) return; // пока ждали ответ, запрос изменился
    state.notes = append ? state.notes.concat(data.items) : data.items;
    state.notesTotal = data.total;
    renderNotes();
  } catch (error) {
    fail(error);
  }
}

let searchTimer;
function setQuery(value) {
  $("search").value = value;
  state.query = value.trim();
  clearTimeout(searchTimer);
  loadNotes(false);
  if (value) selectTab("notes");
}

/* --- напоминания ---------------------------------------------------------- */

function dayLabel(date) {
  const now = new Date();
  const key = dayKey(date);
  if (key === dayKey(now)) return "Сегодня";
  if (key === dayKey(new Date(now.getTime() + 86400000))) return "Завтра";
  return formatter({ weekday: "short", day: "numeric", month: "long" }).format(date);
}

function reminderCard(reminder) {
  const date = new Date(reminder.remind_at);
  const time = formatter({ hour: "2-digit", minute: "2-digit" }).format(date);
  const card = makeCard("reminders", reminder.id, "reminder");
  const remove = async () => {
    try {
      await api("DELETE", `/api/reminders/${reminder.id}`);
      removeCard(card, () => {
        state.reminders = state.reminders.filter((item) => item.id !== reminder.id);
        renderReminders();
      });
    } catch (error) {
      fail(error);
    }
  };
  card.append(
    el("div", { class: "time" }, time),
    el(
      "div",
      { class: "reminder-body" },
      el("p", {}, reminder.text),
      reminder.repeat ? el("span", { class: "repeat" }, el("span", { html: ICONS.repeat }), reminder.repeat) : null,
    ),
    deleteButton("Удалить напоминание", remove),
  );
  return card;
}

function renderReminders() {
  const list = $("reminders");
  $("count-reminders").textContent = state.reminders.length || "";
  if (!state.reminders.length) {
    list.replaceChildren(
      emptyState(ICONS.bell, "Напоминаний нет", "Начните со времени: «завтра в 9 позвонить маме»"),
    );
    return;
  }
  const nodes = [];
  let lastDay = "";
  for (const reminder of state.reminders) {
    const label = dayLabel(new Date(reminder.remind_at));
    if (label !== lastDay) {
      nodes.push(el("h3", { class: "day" }, label));
      lastDay = label;
    }
    nodes.push(reminderCard(reminder));
  }
  list.replaceChildren(...nodes);
}

async function loadReminders() {
  try {
    state.reminders = (await api("GET", "/api/reminders")).items;
    renderReminders();
  } catch (error) {
    fail(error);
  }
}

function renderChips() {
  const input = $("reminder-input");
  $("chips").replaceChildren(
    ...CHIPS.map((chip) =>
      el(
        "button",
        {
          class: "chip",
          type: "button",
          "aria-pressed": String(state.chip === chip),
          onclick: () => {
            let rest = input.value;
            if (state.chip && rest.startsWith(state.chip)) rest = rest.slice(state.chip.length);
            state.chip = state.chip === chip ? "" : chip;
            input.value = state.chip ? `${state.chip} ${rest.trimStart()}` : rest.trimStart();
            input.dispatchEvent(new Event("input"));
            input.focus();
            renderChips();
          },
        },
        chip,
      ),
    ),
  );
}

/* --- экран ---------------------------------------------------------------- */

function selectTab(name) {
  document.querySelector(".tabs").dataset.active = name;
  document.querySelector(".panels").dataset.active = name;
  for (const tab of document.querySelectorAll(".tab")) {
    tab.setAttribute("aria-selected", String(tab.dataset.tab === name));
  }
  try {
    sessionStorage.setItem("tab", name);
  } catch {
    /* хранилище недоступно */
  }
}

function showGate(error) {
  $("splash").hidden = true;
  $("app").hidden = true;
  $("gate").hidden = false;
  const denied = error && error.status === 403;
  let title = "Вход через Telegram";
  let text = "Бот пришлёт одноразовую ссылку для этого браузера.";
  if (denied) {
    title = "Доступ закрыт";
    text = error.message;
  } else if (inTelegram) {
    text = "Не удалось проверить вход. Закройте и откройте приложение заново.";
  } else if (error && error.loginLink) {
    title = "Ссылка не сработала";
    text = `${error.message}. Запросите новую:`;
  } else if (error && error.status !== 401) {
    text = error.message;
  }
  $("gate-title").textContent = title;
  $("gate-text").textContent = text;
  $("gate-steps").hidden = denied || inTelegram;
}

function renderHeader() {
  const { first_name: name, timezone } = state.me;
  $("avatar").textContent = (name || "?").trim().charAt(0).toUpperCase();
  $("greeting").textContent = `Привет, ${name}`;
  const today = formatter({ weekday: "long", day: "numeric", month: "long" }).format(new Date());
  $("today").textContent = today.charAt(0).toUpperCase() + today.slice(1);
  $("footer").textContent = `Часовой пояс: ${timezone} · изменить можно в боте командой /timezone`;
}

function bindEvents() {
  for (const tab of document.querySelectorAll(".tab")) {
    tab.addEventListener("click", () => selectTab(tab.dataset.tab));
  }

  const noteInput = $("note-input");
  noteInput.addEventListener("input", () => {
    autoGrow(noteInput);
    $("note-submit").disabled = !noteInput.value.trim();
  });
  noteInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) $("note-form").requestSubmit();
  });
  $("note-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = noteInput.value.trim();
    if (!text) return;
    $("note-submit").disabled = true;
    try {
      await api("POST", "/api/notes", { text });
      noteInput.value = "";
      autoGrow(noteInput);
      toast("Заметка сохранена");
      if (state.query) setQuery("");
      else await loadNotes(false);
    } catch (error) {
      $("note-submit").disabled = false;
      fail(error);
    }
  });

  $("search").addEventListener("input", (event) => {
    clearTimeout(searchTimer);
    const value = event.target.value;
    searchTimer = setTimeout(() => {
      state.query = value.trim();
      loadNotes(false);
    }, 250);
  });
  $("more").addEventListener("click", () => loadNotes(true));

  const reminderInput = $("reminder-input");
  reminderInput.addEventListener("input", () => {
    $("reminder-submit").disabled = !reminderInput.value.trim();
    if (state.chip && !reminderInput.value.startsWith(state.chip)) {
      state.chip = "";
      renderChips();
    }
  });
  $("reminder-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = reminderInput.value.trim();
    if (!text) return;
    $("reminder-submit").disabled = true;
    try {
      const created = await api("POST", "/api/reminders", { text });
      reminderInput.value = "";
      state.chip = "";
      renderChips();
      toast(`Напомню: ${created.when}`);
      await loadReminders();
    } catch (error) {
      $("reminder-submit").disabled = false;
      fail(error);
    }
  });

  $("logout").addEventListener("click", async () => {
    try {
      await api("POST", "/api/logout", {});
    } finally {
      location.reload();
    }
  });

  // Вернулись на вкладку — обновим списки: сработавшие напоминания должны исчезнуть.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && state.me) {
      loadReminders();
      if (!document.querySelector(".card.editing")) loadNotes(false);
    }
  });
}

async function redeemLoginLink() {
  const match = location.hash.match(/^#login=([\w-]+)$/);
  if (!match) return;
  history.replaceState(null, "", location.pathname);
  try {
    await api("POST", "/api/login", { token: match[1] });
  } catch (error) {
    error.loginLink = true;
    throw error;
  }
}

async function start() {
  document.querySelector(".search-icon").innerHTML = ICONS.search;
  document.querySelector(".gate-logo").innerHTML = ICONS.logo;
  $("logout").innerHTML = ICONS.logout;

  await loadTelegram();
  if (inTelegram) {
    tg.ready();
    tg.expand();
    try {
      tg.setHeaderColor("secondary_bg_color");
      tg.setBackgroundColor("secondary_bg_color");
    } catch {
      /* старый клиент Telegram */
    }
  }

  try {
    await redeemLoginLink();
    state.me = await api("GET", "/api/me");
  } catch (error) {
    showGate(error);
    return;
  }

  bindEvents();
  renderHeader();
  renderChips();
  $("logout").hidden = inTelegram;
  let savedTab = null;
  try {
    savedTab = sessionStorage.getItem("tab");
  } catch {
    /* хранилище недоступно */
  }
  selectTab(savedTab === "reminders" ? "reminders" : "notes");
  skeletons($("notes"));
  skeletons($("reminders"));
  $("splash").hidden = true;
  $("app").hidden = false;
  await Promise.all([loadNotes(false), loadReminders()]);
}

start();
