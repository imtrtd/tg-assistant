"""Главное меню: баннер, inline-разделы и reply-клавиатура частых действий."""

from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    LinkPreviewOptions,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from ..branding import ASSETS, banner_file
from ..config import Settings
from ..db import User
from ..texts import (
    BOTFATHER_URL,
    DOCS_URL,
    GUIDES,
    REPLY_DIGEST,
    REPLY_MENU,
    REPLY_NOTES,
    REPLY_REMINDERS,
    screen_app,
    screen_archive,
    screen_digest,
    screen_guide,
    screen_notes,
    screen_reminders,
    screen_settings,
    welcome,
    with_extra,
)
from .archive import cmd_archive
from .extras import cmd_export, show_digest
from .notes import cmd_notes
from .reminders import cmd_reminders

_NO_EXTRA = object()


class MenuCb(CallbackData, prefix="menu"):
    section: str


def main_keyboard(settings: Settings) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Заметки", callback_data=MenuCb(section="notes"))
    kb.button(text="⏰ Напоминания", callback_data=MenuCb(section="reminders"))
    kb.button(text="🗄 Архив чатов", callback_data=MenuCb(section="archive"))
    kb.button(text="☀️ Сводка", callback_data=MenuCb(section="digest"))
    kb.button(text="⚙️ Настройки", callback_data=MenuCb(section="settings"))
    if settings.mini_app_enabled:
        kb.button(text="📱 Мини-приложение", web_app=WebAppInfo(url=settings.web_app_url))
    else:
        kb.button(text="📱 Мини-приложение", callback_data=MenuCb(section="app"))
    kb.button(text="📖 Инструкции", callback_data=MenuCb(section="guide"))
    kb.adjust(2)
    return kb.as_markup()


def section_keyboard(section: str, settings: Settings) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if section == "notes":
        kb.button(text="Мои заметки", callback_data=MenuCb(section="open-notes"))
    elif section == "reminders":
        kb.button(text="Мои напоминания", callback_data=MenuCb(section="open-reminders"))
    elif section == "archive":
        if settings.mini_app_enabled:
            kb.button(
                text="📱 Архив в приложении",
                web_app=WebAppInfo(url=settings.app_url(open="archive")),
            )
        kb.button(text="Открыть архив", callback_data=MenuCb(section="open-archive"))
    elif section == "digest":
        kb.button(text="Показать сводку", callback_data=MenuCb(section="open-digest"))
    elif section == "settings":
        kb.button(text="Выгрузить заметки", callback_data=MenuCb(section="open-export"))
    elif section == "app" and settings.mini_app_enabled:
        kb.button(text="Открыть", web_app=WebAppInfo(url=settings.web_app_url))
    elif section == "guide":
        return guide_keyboard()
    kb.button(text="← Назад", callback_data=MenuCb(section="home"))
    kb.adjust(1)
    return kb.as_markup()


GUIDE_BUTTONS = (
    ("🚀 Деплой и перезапуск", "deploy"),
    ("🤖 @BotFather", "botfather"),
    ("🖼 Картинки для BotFather", "pics"),
    ("🗄 Архив чатов", "archive"),
    ("🔐 Стирание данных", "wipe"),
    ("📱 Приложение и темы", "app"),
)


def guide_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for text, topic in GUIDE_BUTTONS:
        kb.button(text=text, callback_data=MenuCb(section=f"guide-{topic}"))
    kb.button(text="📚 Документация", url=DOCS_URL)
    kb.button(text="↗ @BotFather", url=BOTFATHER_URL)
    kb.button(text="← Назад", callback_data=MenuCb(section="home"))
    kb.adjust(1, 2, 2, 1, 2, 1)
    return kb.as_markup()


async def send_guide(message: Message, topic: str) -> None:
    """Тема инструкции отдельным сообщением; «pics» — картинки для @BotFather файлами."""
    if topic == "pics":
        for name, caption in (
            ("avatar.png", "Аватар: @BotFather → /setuserpic"),
            ("description.png", "Картинка в пустом чате: @BotFather → /setdescriptionpic"),
            (
                "splash.svg",
                "Иконка загрузки: @BotFather → Mini Apps → Launch Screen → Set Splash Icon. "
                "Фон и шапка: #0a0a0f в Light и Dark Mode",
            ),
        ):
            await message.answer_document(FSInputFile(ASSETS / name), caption=caption)
        return
    await message.answer(
        GUIDES[topic],
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


def reply_keyboard() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.button(text=REPLY_NOTES)
    kb.button(text=REPLY_REMINDERS)
    kb.button(text=REPLY_DIGEST)
    kb.button(text=REPLY_MENU)
    kb.adjust(2)
    return kb.as_markup(
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Сообщение, время или команда",
    )


def _caption(section: str, user: User, settings: Settings, extra: object = _NO_EXTRA) -> str:
    if section == "home":
        text = welcome(user.first_name)
        if extra is _NO_EXTRA:
            return text
        if not isinstance(extra, str):
            raise TypeError("help text must be a string")
        return with_extra(text, extra)
    if section == "notes":
        return screen_notes()
    if section == "reminders":
        return screen_reminders()
    if section == "archive":
        return screen_archive()
    if section == "digest":
        return screen_digest()
    if section == "settings":
        hm = datetime.now(ZoneInfo(user.timezone)).strftime("%H:%M")
        return screen_settings(user.timezone, user.digest_time, hm)
    if section == "app":
        return screen_app(web_enabled=settings.web_enabled, mini_app=settings.mini_app_enabled)
    if section == "guide":
        return screen_guide()
    return welcome(user.first_name)


def _markup(section: str, settings: Settings) -> InlineKeyboardMarkup:
    if section == "home":
        return main_keyboard(settings)
    return section_keyboard(section, settings)


async def send_screen(
    message: Message,
    section: str,
    user: User,
    settings: Settings,
    extra: object = _NO_EXTRA,
) -> None:
    caption = _caption(section, user, settings, extra)
    markup = _markup(section, settings)
    path = banner_file(section if section != "home" else "home")
    if path.is_file():
        await message.answer_photo(
            FSInputFile(path), caption=caption, parse_mode="HTML", reply_markup=markup
        )
        return
    await message.answer(caption, parse_mode="HTML", reply_markup=markup)


async def _edit_screen(query: CallbackQuery, section: str, user: User, settings: Settings) -> None:
    message = query.message
    if not isinstance(message, Message):
        await query.answer()
        return
    caption = _caption(section, user, settings)
    markup = _markup(section, settings)
    path = banner_file(section)
    try:
        if message.photo and path.is_file():
            await message.edit_media(
                InputMediaPhoto(media=FSInputFile(path), caption=caption, parse_mode="HTML"),
                reply_markup=markup,
            )
        else:
            await message.edit_text(caption, parse_mode="HTML", reply_markup=markup)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise
    await query.answer()


async def on_menu(
    query: CallbackQuery,
    callback_data: MenuCb,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    section = callback_data.section
    message = query.message if isinstance(query.message, Message) else None
    if section == "open-notes" and message is not None:
        await query.answer()
        await cmd_notes(message, session, user)
        return
    if section == "open-reminders" and message is not None:
        await query.answer()
        await cmd_reminders(message, session, user)
        return
    if section == "open-archive" and message is not None:
        await query.answer()
        await cmd_archive(message, session, user, settings)
        return
    if section == "open-digest" and message is not None:
        await query.answer()
        await show_digest(message, session, user, "")
        return
    if section == "open-export" and message is not None:
        await query.answer()
        await cmd_export(message, session, user)
        return
    topic = section.removeprefix("guide-")
    if (
        section.startswith("guide-")
        and message is not None
        and (topic in GUIDES or topic == "pics")
    ):
        await query.answer()
        await send_guide(message, topic)
        return
    if section not in {
        "home",
        "notes",
        "reminders",
        "archive",
        "digest",
        "settings",
        "app",
        "guide",
    }:
        section = "home"
    await _edit_screen(query, section, user, settings)


async def on_reply_notes(message: Message, session: AsyncSession, user: User) -> None:
    await cmd_notes(message, session, user)


async def on_reply_reminders(message: Message, session: AsyncSession, user: User) -> None:
    await cmd_reminders(message, session, user)


async def on_reply_digest(message: Message, session: AsyncSession, user: User) -> None:
    await show_digest(message, session, user, "")


async def on_reply_menu(message: Message, user: User, settings: Settings) -> None:
    await send_screen(message, "home", user, settings)


def create_router() -> Router:
    router = Router(name="menu")
    router.message.register(on_reply_notes, F.text == REPLY_NOTES)
    router.message.register(on_reply_reminders, F.text == REPLY_REMINDERS)
    router.message.register(on_reply_digest, F.text == REPLY_DIGEST)
    router.message.register(on_reply_menu, F.text == REPLY_MENU)
    router.callback_query.register(on_menu, MenuCb.filter())
    return router
