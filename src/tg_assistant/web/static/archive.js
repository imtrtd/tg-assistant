"use strict";

/* Вкладка «Архив»: чаты из Telegram Business, переписка с правками и удалениями.
   Подключается до app.js и пользуется его помощниками ($, el, api, toast, fail,
   formatter, dayKey, dayLabel, emptyState, skeletons) — они вызываются уже после загрузки. */

/* Параметры запуска запоминаем сразу: вход по ссылке потом переписывает адрес. */
const LAUNCH_PARAMS = new URLSearchParams(location.search);

const archive = {
  loaded: false,
  overview: null,
  view: "chats",
  chats: [],
  deleted: [],
  query: "",
  chat: null, // { id, title }
  messages: [],
  hasMore: false,
  filter: "all",
  mediaUrls: [],
};

const ARCHIVE_ICONS = {
  back: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6"/></svg>',
  chats: '<svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M10 14h32a6 6 0 0 1 6 6v14a6 6 0 0 1-6 6H24l-10 8v-8h-4a6 6 0 0 1-6-6V20a6 6 0 0 1 6-6Z"/><path d="M48 24h6a6 6 0 0 1 6 6v12a6 6 0 0 1-6 6h-2v8l-9-8H34"/></svg>',
  trash: '<svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M12 18h40"/><path d="M24 18v-6h16v6"/><path d="M48 18l-3 36H19l-3-36"/><path d="M27 28v16M37 28v16"/></svg>',
};

const MEDIA_EMOJI = {
  photo: "🖼",
  video: "🎬",
  animation: "🎞",
  video_note: "⏺",
  voice: "🎤",
  audio: "🎵",
  sticker: "🏷",
  document: "📎",
};

function initials(name) {
  return (name || "?").trim().charAt(0).toUpperCase() || "?";
}

function shortTime(iso) {
  const date = new Date(iso);
  if (dayKey(date) === dayKey(new Date())) {
    return formatter({ hour: "2-digit", minute: "2-digit" }).format(date);
  }
  return formatter({ day: "numeric", month: "short" }).format(date);
}

function fullTime(iso) {
  return formatter({ day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }).format(
    new Date(iso),
  );
}

function authHeaders() {
  return inTelegram ? { Authorization: `tma ${tg.initData}` } : {};
}

/* --- обзор ------------------------------------------------------------------ */

function renderOverview() {
  const o = archive.overview;
  if (!o) return;
  $("archive-dot").classList.toggle("on", o.connected);
  $("archive-state").textContent = o.connected ? "Архив подключён" : "Архив не подключён";
  $("archive-setup").hidden = o.connected;
  const counts = [
    [o.chats, "чатов"],
    [o.messages, "сообщений"],
    [o.edited, "изменено"],
    [o.deleted, "удалено"],
  ];
  $("archive-counts").replaceChildren(
    ...counts.map(([n, label]) => el("div", {}, el("b", {}, String(n)), el("span", {}, label))),
  );
  $("notify-edits").checked = o.notify_edits;
  $("notify-deletes").checked = o.notify_deletes;
  $("count-deleted").textContent = o.deleted ? String(o.deleted) : "";
}

function renderTabBadge() {
  const dayAgo = Date.now() - 86400000;
  const recent = archive.deleted.filter((m) => new Date(m.deleted_at).getTime() > dayAgo).length;
  $("count-archive").textContent = recent ? String(recent) : "";
}

async function saveNotify(field, value) {
  try {
    archive.overview = await api("PUT", "/api/archive/settings", { [field]: value });
    renderOverview();
    toast(value ? "Уведомления включены" : "Уведомления выключены");
  } catch (error) {
    fail(error);
    renderOverview();
  }
}

/* --- список чатов и удалённых ---------------------------------------------- */

function chatRow(chat) {
  const deleted = chat.deleted ? el("span", { class: "count alert" }, `🗑 ${chat.deleted}`) : null;
  return el(
    "button",
    { class: "card chat-row", type: "button", onclick: () => openChat(chat.chat_id, chat.title) },
    el("div", { class: "avatar small", "aria-hidden": "true" }, initials(chat.title)),
    el(
      "div",
      { class: "chat-row-body" },
      el("b", {}, chat.title),
      el("span", {}, `${chat.messages} ${plural(chat.messages, "сообщение", "сообщения", "сообщений")}`),
    ),
    el("div", { class: "chat-row-side" }, shortTime(chat.last_at), deleted ? el("br") : null, deleted),
  );
}

function deletedCard(m) {
  const body = [];
  if (m.media_type) body.push(mediaBlock(m));
  if (m.text) body.push(el("p", { class: "card-text" }, m.text));
  const who = m.chat_title === m.sender_name ? m.sender_name : `${m.sender_name} · ${m.chat_title}`;
  return el(
    "article",
    { class: "card deleted-card" },
    el(
      "div",
      { class: "meta" },
      el("b", {}, who + (m.outgoing ? " (вы)" : "")),
      el("span", {}, `удалено ${fullTime(m.deleted_at)}`),
    ),
    ...body,
    el(
      "div",
      { class: "card-foot" },
      el("span", {}, `отправлено ${fullTime(m.sent_at)}`),
      el("span", { class: "spacer" }),
      el(
        "button",
        { class: "act", type: "button", onclick: () => openChat(m.chat_id, m.chat_title, m.id) },
        "В переписке",
      ),
    ),
  );
}

function renderArchiveList() {
  const list = $("archive-list");
  $("archive-search").parentElement.hidden = archive.view !== "chats";
  if (archive.view === "chats") {
    const q = archive.query.toLowerCase();
    const items = q ? archive.chats.filter((c) => c.title.toLowerCase().includes(q)) : archive.chats;
    if (!items.length) {
      list.replaceChildren(
        q
          ? emptyState(ARCHIVE_ICONS.chats, "Чат не найден", "Попробуйте другое имя")
          : emptyState(
              ARCHIVE_ICONS.chats,
              "Чатов пока нет",
              archive.overview && archive.overview.connected
                ? "Сообщения появятся, как только вам напишут"
                : "Подключите бота в Telegram Business — шаги выше",
            ),
      );
      return;
    }
    list.replaceChildren(...items.map(chatRow));
    return;
  }
  if (!archive.deleted.length) {
    list.replaceChildren(emptyState(ARCHIVE_ICONS.trash, "Удалённых нет", "Здесь появятся сообщения, которые стёрли собеседники"));
    return;
  }
  list.replaceChildren(...archive.deleted.map(deletedCard));
}

function selectArchiveView(view) {
  archive.view = view;
  for (const button of document.querySelectorAll(".segmented button")) {
    button.setAttribute("aria-selected", String(button.dataset.view === view));
  }
  renderArchiveList();
}

async function loadArchive() {
  archive.loaded = true;
  skeletons($("archive-list"));
  try {
    const [overview, chats, deleted] = await Promise.all([
      api("GET", "/api/archive"),
      api("GET", "/api/archive/chats"),
      api("GET", "/api/archive/deleted"),
    ]);
    archive.overview = overview;
    archive.chats = chats.items;
    archive.deleted = deleted.items;
    renderOverview();
    renderTabBadge();
    renderArchiveList();
  } catch (error) {
    archive.loaded = false;
    fail(error);
  }
}

/* --- переписка --------------------------------------------------------------- */

function releaseMedia() {
  for (const url of archive.mediaUrls) URL.revokeObjectURL(url);
  archive.mediaUrls = [];
}

async function sendToTelegram(m, button) {
  button.disabled = true;
  try {
    await api("POST", `/api/archive/messages/${m.id}/send`, {});
    toast("Отправил вам в чат с ботом");
  } catch (error) {
    fail(error);
  } finally {
    button.disabled = false;
  }
}

function mediaBlock(m) {
  const label = `${MEDIA_EMOJI[m.media_type] || "📎"} ${m.media_label || "вложение"}`;
  const send = el("button", { class: "act", type: "button" }, "Прислать в Telegram");
  send.addEventListener("click", () => sendToTelegram(m, send));
  const chip = el("div", { class: "media-chip" }, el("span", {}, label), send);
  if (!m.media_inline) return chip;

  /* Картинку грузим через fetch: внутри Telegram вход — заголовком, а <img> его не отправит. */
  const img = el("img", { class: "media-img", alt: m.media_label || "изображение", loading: "lazy" });
  fetch(`/api/archive/messages/${m.id}/media`, { headers: authHeaders(), credentials: "same-origin" })
    .then((response) => (response.ok ? response.blob() : Promise.reject(response)))
    .then((blob) => {
      const url = URL.createObjectURL(blob);
      archive.mediaUrls.push(url);
      img.src = url;
    })
    .catch(() => img.replaceWith(chip));
  return el("div", {}, img, m.media_type === "sticker" ? null : chip);
}

function bubble(m) {
  const classes = ["bubble"];
  if (m.outgoing) classes.push("out");
  if (m.deleted_at) classes.push("deleted");
  const node = el("article", { class: classes.join(" "), id: `msg-${m.id}` });
  if (!m.outgoing) node.append(el("span", { class: "bubble-who" }, m.sender_name));
  if (m.media_type) node.append(mediaBlock(m));
  if (m.text) node.append(el("p", { class: "bubble-text" }, m.text));

  const meta = el("div", { class: "bubble-meta" });
  if (m.edited_at) meta.append(el("span", { class: "mark edited" }, "✏️ изменено"));
  if (m.deleted_at) meta.append(el("span", { class: "mark deleted" }, `🗑 удалено ${shortTime(m.deleted_at)}`));
  meta.append(el("time", { datetime: m.sent_at }, formatter({ hour: "2-digit", minute: "2-digit" }).format(new Date(m.sent_at))));
  node.append(meta);

  if (m.edits && m.edits.length) {
    const versions = m.edits.map((e) =>
      el(
        "div",
        { class: "version" },
        el("time", { datetime: e.replaced_at }, `до ${fullTime(e.replaced_at)}`),
        e.text || "(без текста)",
      ),
    );
    const n = m.edits.length;
    node.append(
      el(
        "details",
        {},
        el("summary", {}, `Прежние версии (${n})`),
        ...versions,
      ),
    );
  }
  return node;
}

function renderThread() {
  const filter = archive.filter;
  const items = archive.messages.filter(
    (m) => filter === "all" || (filter === "edited" ? m.edited_at : m.deleted_at),
  );
  const nodes = [];
  let lastDay = "";
  for (const m of items) {
    const label = dayLabel(new Date(m.sent_at));
    if (label !== lastDay) {
      nodes.push(el("div", { class: "day-sep" }, label));
      lastDay = label;
    }
    nodes.push(bubble(m));
  }
  if (!nodes.length) {
    nodes.push(
      emptyState(
        filter === "deleted" ? ARCHIVE_ICONS.trash : ARCHIVE_ICONS.chats,
        filter === "all" ? "Сообщений нет" : "Таких сообщений нет",
        archive.hasMore ? "Попробуйте загрузить более ранние" : "",
      ),
    );
  }
  releaseMedia();
  $("chat-messages").replaceChildren(...nodes);
  $("chat-more").hidden = !archive.hasMore;
  const total = archive.messages.length;
  const deleted = archive.messages.filter((m) => m.deleted_at).length;
  const edited = archive.messages.filter((m) => m.edited_at).length;
  const parts = [`${total}${archive.hasMore ? "+" : ""} ${plural(total, "сообщение", "сообщения", "сообщений")}`];
  if (edited) parts.push(`изменено ${edited}`);
  if (deleted) parts.push(`удалено ${deleted}`);
  $("chat-sub").textContent = parts.join(" · ");
}

function setFilter(filter) {
  archive.filter = filter;
  for (const chip of document.querySelectorAll("#chat-filters .chip")) {
    chip.setAttribute("aria-pressed", String(chip.dataset.filter === filter));
  }
  renderThread();
}

function showBackButton(show) {
  if (!inTelegram || !tg.BackButton) return;
  if (show) tg.BackButton.show();
  else tg.BackButton.hide();
}

async function openChat(chatId, title, focusId) {
  archive.chat = { id: chatId, title: title || "" };
  archive.messages = [];
  archive.hasMore = false;
  $("archive-home").hidden = true;
  $("archive-chat").hidden = false;
  $("chat-title").textContent = title || "Переписка";
  $("chat-avatar").textContent = initials(title);
  $("chat-sub").textContent = "";
  skeletons($("chat-messages"));
  setFilter("all");
  showBackButton(true);
  window.scrollTo({ top: 0 });
  try {
    const data = await api("GET", `/api/archive/chats/${chatId}`);
    if (!archive.chat || archive.chat.id !== chatId) return; // пока грузили, ушли назад
    archive.messages = data.items;
    archive.hasMore = data.has_more;
    archive.chat.title = data.title || title;
    $("chat-title").textContent = archive.chat.title;
    $("chat-avatar").textContent = initials(archive.chat.title);
    renderThread();
    const target = focusId ? $(`msg-${focusId}`) : $("chat-messages").lastElementChild;
    if (target) target.scrollIntoView({ block: focusId ? "center" : "end" });
  } catch (error) {
    fail(error);
    closeChat();
  }
}

async function loadOlder() {
  if (!archive.chat || !archive.messages.length) return;
  const button = $("chat-more");
  button.disabled = true;
  const anchor = archive.messages[0].id;
  try {
    const data = await api("GET", `/api/archive/chats/${archive.chat.id}?before=${anchor}`);
    archive.messages = data.items.concat(archive.messages);
    archive.hasMore = data.has_more;
    renderThread();
    const keep = $(`msg-${anchor}`);
    if (keep) keep.scrollIntoView({ block: "start" });
  } catch (error) {
    fail(error);
  } finally {
    button.disabled = false;
  }
}

function closeChat() {
  archive.chat = null;
  releaseMedia();
  $("archive-chat").hidden = true;
  $("archive-home").hidden = false;
  showBackButton(false);
}

function isChatOpen() {
  return Boolean(archive.chat);
}

/* --- запуск ------------------------------------------------------------------ */

function bindArchive() {
  $("chat-back").innerHTML = ARCHIVE_ICONS.back;
  document.querySelector("#archive-home .search-icon").innerHTML = ICONS.search;
  $("chat-back").addEventListener("click", closeChat);
  $("chat-more").addEventListener("click", loadOlder);
  $("notify-edits").addEventListener("change", (e) => saveNotify("notify_edits", e.target.checked));
  $("notify-deletes").addEventListener("change", (e) => saveNotify("notify_deletes", e.target.checked));
  for (const button of document.querySelectorAll(".segmented button")) {
    button.addEventListener("click", () => selectArchiveView(button.dataset.view));
  }
  for (const chip of document.querySelectorAll("#chat-filters .chip")) {
    chip.addEventListener("click", () => setFilter(chip.dataset.filter));
  }
  $("archive-search").addEventListener("input", (e) => {
    archive.query = e.target.value.trim();
    renderArchiveList();
  });
  if (inTelegram && tg.BackButton) tg.BackButton.onClick(closeChat);
}

/* Что открыть при запуске: ?open=archive&chat=123 (кнопка из уведомления) или
   start_param из ссылки t.me/<бот>?startapp=archive / archive_123. */
function launchTarget() {
  let tab = LAUNCH_PARAMS.get("open");
  let chat = LAUNCH_PARAMS.get("chat");
  const start = inTelegram && tg.initDataUnsafe ? tg.initDataUnsafe.start_param : null;
  if (start) {
    const match = /^(notes|reminders|archive)(?:_(\d+))?$/.exec(start);
    if (match) {
      tab = match[1];
      chat = match[2] || chat;
    }
  }
  if (!["notes", "reminders", "archive"].includes(tab)) return null;
  const chatId = chat && /^-?\d+$/.test(chat) ? Number(chat) : null;
  return { tab, chatId: tab === "archive" ? chatId : null };
}
