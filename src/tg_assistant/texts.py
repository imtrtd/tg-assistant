"""Тексты бота. Хендлеры только подставляют данные и ставят parse_mode HTML.

Пользовательский текст экранируется здесь или в хендлере до подстановки.
"""

import html

from aiogram.types import BotCommand

# Команды, которые имеют смысл только в личке: архив и одноразовая ссылка в браузер.
PRIVATE_ONLY = frozenset(
    {
        "archive",
        "chats",
        "deleted",
        "web",
        "topics",
        "search",
        "sources",
        "channel",
        "watch",
        "unwatch",
        "watches",
    }
)

COMMAND_SPECS: tuple[tuple[str, str], ...] = (
    ("start", "Главное меню"),
    ("note", "Новая заметка"),
    ("notes", "Список заметок"),
    ("find", "Поиск по заметкам"),
    ("edit", "Изменить заметку"),
    ("del", "Удалить заметку"),
    ("remind", "Новое напоминание"),
    ("reminders", "Список напоминаний"),
    ("timezone", "Часовой пояс"),
    ("digest", "Утренняя сводка"),
    ("export", "Экспорт заметок"),
    ("archive", "Архив чатов"),
    ("chats", "Чаты в архиве"),
    ("deleted", "Удалённые сообщения"),
    ("app", "Мини-приложение"),
    ("web", "Вход в браузере"),
    ("topics", "Пересоздать темы"),
    ("search", "Публичные посты"),
    ("sources", "Публичные каналы"),
    ("channel", "Сводка канала"),
    ("watch", "Наблюдение"),
    ("unwatch", "Снять наблюдение"),
    ("watches", "Список наблюдений"),
    ("help", "Справка и команды"),
)

BOT_COMMANDS = [BotCommand(command=name, description=desc) for name, desc in COMMAND_SPECS]
GROUP_COMMANDS = [cmd for cmd in BOT_COMMANDS if cmd.command not in PRIVATE_ONLY]

DESCRIPTION_RU = (
    "Личный ассистент в Telegram.\n\n"
    "• Заметки с поиском и тегами\n"
    "• Напоминания, в том числе с повтором\n"
    "• Утренняя сводка дел на день\n"
    "• Экспорт заметок в файл\n"
    "• Архив личных чатов: правки и удаления\n"
    "• Мини-приложение для заметок и настроек\n\n"
    "Напишите текст или перешлите сообщение — бот предложит сохранить его или напомнить."
)
DESCRIPTION_EN = (
    "A personal assistant in Telegram.\n\n"
    "• Notes with search and tags\n"
    "• Reminders, including repeating ones\n"
    "• A morning digest of the day\n"
    "• Export notes to a file\n"
    "• Private chat archive: edits and deletions\n"
    "• A mini app for notes and settings\n\n"
    "Send or forward a message — the bot can save it or set a reminder."
)
SHORT_RU = "Заметки, напоминания, сводка на день и архив чатов."
SHORT_EN = "Notes, reminders, a morning digest, and a chat archive."

REPLY_NOTES = "📝 Заметки"
REPLY_REMINDERS = "⏰ Напоминания"
REPLY_DIGEST = "☀️ Сводка"
REPLY_MENU = "☰ Меню"
REPLY_HINT = "Кнопки внизу: <b>заметки</b>, <b>напоминания</b>, <b>сводка</b> и меню."

ERROR_TEXT = "Что-то пошло не так. Попробуйте ещё раз чуть позже."
ACCESS_ALERT = "Доступ закрыт"

REMIND_UNKNOWN = "Не понял, когда напомнить.\n\n"
CAPTION_LIMIT = 1024


def command_help(commands: list[BotCommand] | None = None) -> str:
    items = commands if commands is not None else BOT_COMMANDS
    lines = ["<b>Команды</b>"]
    for cmd in items:
        desc = cmd.description[:1].lower() + cmd.description[1:]
        lines.append(f"/{cmd.command} — {html.escape(desc)}")
    lines += [
        "",
        "Теги заметок: /find #тег. Каналы: /sources, посты: /search, канал: /channel.",
    ]
    return "\n".join(lines)


def welcome(name: str) -> str:
    return (
        f"<b>Привет, {html.escape(name)}!</b>\n\n"
        "Я помогаю держать дела в одном чате: заметки, напоминания, "
        "утренняя сводка и архив переписок.\n\n"
        "Напишите или перешлите сообщение — предложу сохранить его "
        "или поставить напоминание.\n\n"
        "<b>Выберите раздел</b>"
    )


def with_extra(text: str, extra: str) -> str:
    combined = f"{text}\n\n{extra}"
    if len(combined) <= CAPTION_LIMIT:
        return combined
    return text


def screen_notes() -> str:
    return (
        "📝 <b>Заметки</b>\n\n"
        "Сохранить: <code>/note купить хлеб</code> или ответом на сообщение.\n"
        "Список — /notes, поиск — /find молоко или /find #тег.\n"
        "Изменить — /edit 12 новый текст, удалить — /del 12.\n\n"
        "Можно просто написать или переслать сообщение."
    )


def screen_reminders() -> str:
    return (
        "⏰ <b>Напоминания</b>\n\n"
        "<code>/remind через 15 минут выключить духовку</code>\n"
        "<code>/remind завтра в 9 позвонить</code>\n"
        "<code>/remind каждый день 8:00 витамины</code>\n\n"
        "Список — /reminders. Если не указать время дня, напомню в 9:00.\n"
        "Часовой пояс — /timezone."
    )


def screen_archive() -> str:
    return (
        "🗄 <b>Архив чатов</b>\n\n"
        "Если собеседник изменит или удалит сообщение, пришлю сюда, что было и что стало. "
        "В сами чаты я ничего не пишу.\n\n"
        "/archive — состояние, /chats — выгрузка, /deleted — последние удалённые.\n"
        "Нужны Telegram Premium и Business Mode."
    )


def screen_digest() -> str:
    return (
        "☀️ <b>Сводка</b>\n\n"
        "Каждое утро пришлю напоминания на сегодня.\n"
        "Включить: /digest 8:00 · выключить: /digest off"
    )


def screen_settings(timezone: str, digest_time: str | None, hm: str) -> str:
    state = f"включена, в {digest_time}" if digest_time else "выключена"
    return (
        "⚙️ <b>Настройки</b>\n\n"
        f"Часовой пояс: <b>{html.escape(timezone)}</b>, сейчас {hm}.\n"
        f"Утренняя сводка {state}.\n\n"
        "Пояс: /timezone Europe/Moscow, /timezone +3 или /timezone мск\n"
        "Сводка: /digest 8:00 или /digest off\n"
        "Все заметки файлом: /export"
    )


def screen_app(*, web_enabled: bool, mini_app: bool) -> str:
    if not web_enabled:
        return (
            "📱 <b>Мини-приложение</b>\n\nВеб-интерфейс не настроен: в .env не задан WEB_APP_URL."
        )
    if not mini_app:
        return (
            "📱 <b>Мини-приложение</b>\n\n"
            "В Telegram оно открывается только по HTTPS.\n"
            "Сейчас доступен вход в браузере: /web"
        )
    return "📱 <b>Мини-приложение</b>\n\nЗаметки, напоминания, сводка и настройки — в одном окне."


def note_saved(note_id: int) -> str:
    return f"<b>Сохранено как #{note_id}</b>"


def note_usage() -> str:
    return (
        "<b>Нужен текст заметки</b>\n"
        "Напишите: <code>/note купить хлеб</code>\n"
        "Или ответьте командой /note на сообщение, которое нужно сохранить."
    )


def notes_empty() -> str:
    return "<b>Заметок пока нет.</b> Добавьте: /note текст"


def notes_header(total: int, page: int, pages: int) -> str:
    return f"📝 <b>Заметки ({total}), стр. {page}/{pages}</b>"


def search_prompt() -> str:
    return "<b>Что искать?</b>\nНапример: /find молоко или /find #работа"


def search_empty(query: str) -> str:
    return f"<b>Ничего не найдено</b>\nПо запросу «{html.escape(query)}» заметок нет."


def search_header(count: int, *, truncated: bool, limit: int) -> str:
    header = f"🔎 <b>Найдено: {count}</b>"
    if truncated:
        header += f" (показаны первые {limit})"
    return header


def note_deleted(note_id: int) -> str:
    return f"Заметка <b>#{note_id}</b> удалена."


def note_missing(note_id: int) -> str:
    return f"<b>Заметки #{note_id} нет.</b>"


def edit_usage() -> str:
    return "<b>Формат:</b> <code>/edit 12 новый текст</code>"


def note_updated(note_id: int) -> str:
    return f"Заметка <b>#{note_id}</b> обновлена."


def note_deleted_toast(note_id: int, *, deleted: bool) -> str:
    return f"Заметка #{note_id} удалена" if deleted else "Уже удалена"


DEL_USAGE = "Укажите номер заметки: <code>/del 12</code>"
CAPTURE_MISSING = "Исходное сообщение не найдено"
CAPTURE_PAST = "Это время уже прошло"
ARCHIVE_SAVED = "Сохранено"
ARCHIVE_CHAT_EMPTY = "В этом чате нет сохранённых сообщений"
DONE_TOAST = "Готово ✅"
REMINDER_GONE = "Напоминание уже удалено"


def snooze_toast(hm: str) -> str:
    return f"Напомню в {hm}"


def removed_toast(deleted: bool) -> str:
    return "Удалено" if deleted else "Уже удалено"


def remind_help() -> str:
    return (
        "<b>Как поставить напоминание</b>\n"
        "Примеры:\n"
        "/remind через 15 минут выключить духовку\n"
        "/remind 18:30 позвонить маме\n"
        "/remind завтра в 9 оплатить счёт\n"
        "/remind 25.12 купить подарки\n"
        "/remind в пятницу 19:00 кино\n"
        "/remind каждый день 8:00 витамины\n"
        "/remind по будням 9:30 стендап\n"
        "/remind каждую пятницу 18:00 отчёт\n\n"
        "Без времени дня — в 9:00. Часовой пояс: /timezone"
    )


def remind_set(description_html: str) -> str:
    return f"⏰ <b>Напомню:</b> {description_html}"


def reminders_empty() -> str:
    return "<b>Активных напоминаний нет.</b> Создать: /remind"


def reminders_header(count: int, *, truncated: bool, limit: int) -> str:
    header = f"⏰ <b>Напоминания ({count})</b>"
    if truncated:
        header += f", показаны ближайшие {limit}"
    return header


def timezone_current(timezone: str, hm: str) -> str:
    return (
        f"Ваш часовой пояс: <b>{html.escape(timezone)}</b>, сейчас {hm}.\n"
        "Изменить: /timezone Europe/Moscow, /timezone +3 или /timezone мск"
    )


def timezone_unknown() -> str:
    return (
        "<b>Не знаю такой часовой пояс.</b>\nПример: /timezone Asia/Yekaterinburg или /timezone +5"
    )


def timezone_set(timezone: str, hm: str) -> str:
    return f"Часовой пояс: <b>{html.escape(timezone)}</b>, сейчас {hm}."


def digest_status(state: str, example: str) -> str:
    return (
        f"<b>Утренняя сводка</b> {state}. Пример сегодняшней:\n\n"
        f"{example}\n\n"
        "Включить: /digest 8:00 · выключить: /digest off"
    )


def digest_disabled() -> str:
    return "<b>Утренняя сводка выключена.</b>"


def digest_bad_time() -> str:
    return "<b>Не понял время.</b> Пример: /digest 8:00 или /digest off"


def digest_enabled(hm: str, timezone: str) -> str:
    return f"<b>Готово:</b> каждый день в {hm} ({html.escape(timezone)}) пришлю список дел на день."


def export_empty() -> str:
    return "<b>Заметок пока нет</b> — выгружать нечего."


def export_caption(count: int) -> str:
    return f"Заметок: {count}"


def morning_digest(name: str, items: list[str], notes_count: int) -> str:
    lines = [f"☀️ <b>Доброе утро, {html.escape(name)}!</b>", ""]
    if items:
        lines.append(f"Сегодня напоминаний: {len(items)}")
        lines.extend(items)
    else:
        lines.append("На сегодня напоминаний нет.")
    lines += ["", f"Заметок всего: {notes_count}. Отключить сводку: /digest off"]
    return "\n".join(lines)


def digest_item(hm: str, text: str, repeat: str) -> str:
    suffix = f" 🔁 {repeat}" if repeat else ""
    return f"• <b>{hm}</b> {html.escape(text)}{suffix}"


def reminder_fired(text: str) -> str:
    return f"⏰ <b>Напоминание</b>\n{html.escape(text)}"


CAPTURE_PROMPT = "<b>Что сделать с этим сообщением?</b>"


def captured_forward(note_id: int) -> str:
    return f"Сохранено в заметки как <b>#{note_id}</b>"


def captured_note(note_id: int) -> str:
    return f"📝 Сохранено в заметки как <b>#{note_id}</b>"


def captured_remind(when: str, text: str, repeat: str) -> str:
    suffix = f" 🔁 {repeat}" if repeat else ""
    return f"⏰ Напомню <b>{when}</b>{suffix}\n{html.escape(text)}"


WEB_NOT_CONFIGURED = "Веб-интерфейс не настроен: в .env не задан <code>WEB_APP_URL</code>."
APP_NEEDS_HTTPS = (
    "<b>Мини-приложение</b> в Telegram работает только по HTTPS.\n"
    "Сейчас доступен вход в браузере: /web"
)
APP_INTRO = "<b>Заметки и напоминания</b> в одном окне:"
WEB_PRIVATE_ONLY = "<b>Ссылку для входа</b> пришлю только в личном чате."


def web_link(url: str, minutes: int, home: str) -> str:
    return (
        f"<b>Ссылка для входа в браузере</b>\n{url}\n\n"
        f"Действует {minutes} минут и только один раз. Никому её не пересылайте.\n\n"
        f"Постоянный адрес: {home}\n"
        "Там можно войти кнопкой «Войти через Telegram», если домен указан "
        "в @BotFather (/setdomain)."
    )


def access_denied(user_id: object) -> str:
    return f"<b>Доступ к боту закрыт</b>\nВаш Telegram id: <code>{user_id}</code>"


ARCHIVE_HOW_TO = (
    "<b>Как подключить</b>\n"
    "1. В @BotFather: /mybots → бот → Bot Settings → Business Mode → Turn on.\n"
    "2. В Telegram: Настройки → Telegram Business → Чат-боты → выберите этого бота.\n"
    "Нужна подписка Telegram Premium.\n"
    "3. Укажите, к каким чатам дать доступ.\n\n"
    "Сохраняются только сообщения, пришедшие после подключения."
)


def archive_head(connected: bool) -> str:
    state = "подключён ✅" if connected else "не подключён"
    return f"🗄 <b>Архив чатов</b> — {state}"


def archive_stats(chats: int, messages: int, edited: int, deleted: int) -> str:
    return (
        f"Чатов: {chats} · сообщений: {messages}\n"
        f"Изменено собеседниками и вами: {edited} · удалено: {deleted}"
    )


def chats_empty() -> str:
    return "<b>В архиве пока нет чатов.</b> Подключение: /archive"


def chats_header() -> str:
    return "📁 <b>Чаты в архиве</b>\nНажмите, чтобы выгрузить файлом."


def deleted_empty() -> str:
    return "<b>Удалённых сообщений в архиве нет.</b>"


def deleted_header(count: int) -> str:
    return f"🗑 <b>Последние удалённые</b> ({count})"


BUSINESS_ON = (
    "🗄 <b>Архив чатов подключён.</b>\n\n"
    "Сохраняю сообщения из ваших личных чатов и пришлю сюда, если собеседник "
    "изменит или удалит сообщение. В сами чаты я ничего не пишу.\n\n"
    "/archive — состояние и настройки, /chats — чаты в архиве, "
    "/deleted — последние удалённые."
)
BUSINESS_OFF = "🗄 <b>Архив чатов отключён.</b> Уже сохранённые сообщения остались: /chats"


def message_edited(where: str, old: str, new: str) -> str:
    return f"✏️ <b>Сообщение изменено</b>\n{where}\n\n<b>Было:</b>\n{old}\n\n<b>Стало:</b>\n{new}"


def deleted_batch_header(total: int, chat: str) -> str:
    return f"🗑 <b>Удалено сообщений: {total}</b> · {chat}"


def deleted_batch_more(count: int) -> str:
    return f"…и ещё {count}: /deleted"


def deleted_batch_unknown(missing: int) -> str:
    return f"Текст {missing} из них неизвестен: они пришли до подключения архива."


def admin_error(update_id: int, exc_type: str, exc_text: str, trace: str) -> str:
    return (
        f"⚠️ <b>Ошибка в боте</b> (update {update_id})\n"
        f"<code>{html.escape(exc_type)}: {html.escape(exc_text)}</code>\n\n"
        f"<pre>{trace}</pre>"
    )


def bot_started(node_name: str) -> str:
    """Администраторам: узел начал работу (после запуска или переключения ПК ↔ облако)."""
    return f"🟢 Бот работает на узле <code>{html.escape(node_name)}</code>."
