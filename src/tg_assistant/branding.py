"""Меню команд, описание бота и кнопка меню. Вызывается при каждом старте.

Повторный вызов с теми же текстами ничего не меняет у пользователя: Telegram
просто записывает то же самое. Аватар и картинку описания Bot API не ставит —
их загружают через @BotFather, см. docs/appearance.md.
"""

import logging
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import (
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault,
    MenuButtonCommands,
    MenuButtonWebApp,
    WebAppInfo,
)

from .config import Settings
from .texts import (
    BOT_COMMANDS,
    DESCRIPTION_EN,
    DESCRIPTION_RU,
    GROUP_COMMANDS,
    SHORT_EN,
    SHORT_RU,
)

logger = logging.getLogger(__name__)

ASSETS = Path(__file__).resolve().parent / "assets"
MENU_BUTTON_TEXT = "Открыть"

# Что бот выставляет себе через setMySettings. Остальное (группы, privacy mode,
# работа с другими ботами) не трогаем — оно остаётся как в @BotFather.
BOT_SETTINGS = {
    # темы в личке: бот сам создаёт постоянные (topics.py)
    "has_topics_enabled": True,
    # иначе Telegram заводит новую тему на каждое сообщение вне тем
    "allows_users_to_create_topics": False,
    # список тем боковой панелью
    "has_topic_sidebar": True,
    # архив чатов работает через Telegram Business
    "can_connect_to_business": True,
    # «@бот текст» в любом чате сохраняет заметку (handlers/mention.py)
    "supports_inline_queries": True,
}


def banner_file(section: str) -> Path:
    return ASSETS / "banners" / f"{section}.png"


async def setup_bot_profile(bot: Bot, settings: Settings) -> None:
    await _try(
        "commands for all chats",
        bot.set_my_commands(BOT_COMMANDS, scope=BotCommandScopeDefault()),
    )
    await _try(
        "commands for private chats",
        bot.set_my_commands(BOT_COMMANDS, scope=BotCommandScopeAllPrivateChats()),
    )
    await _try(
        "commands for groups",
        bot.set_my_commands(GROUP_COMMANDS, scope=BotCommandScopeAllGroupChats()),
    )
    for language, text in ((None, DESCRIPTION_RU), ("en", DESCRIPTION_EN)):
        await _try(
            f"description ({language or 'default'})",
            bot.set_my_description(text, language_code=language),
        )
    for language, text in ((None, SHORT_RU), ("en", SHORT_EN)):
        await _try(
            f"short description ({language or 'default'})",
            bot.set_my_short_description(text, language_code=language),
        )
    await setup_menu_button(bot, settings)
    if settings.bot_settings_sync:
        await _try("bot settings", bot.set_my_settings(**BOT_SETTINGS))


async def setup_menu_button(bot: Bot, settings: Settings) -> None:
    """Кнопка слева от поля ввода: мини-приложение при HTTPS-адресе, иначе список команд."""
    if settings.mini_app_enabled:
        button = MenuButtonWebApp(
            text=MENU_BUTTON_TEXT, web_app=WebAppInfo(url=settings.web_app_url)
        )
    else:
        button = MenuButtonCommands()
    await _try("menu button", bot.set_chat_menu_button(menu_button=button))


async def _try(label: str, call) -> None:
    try:
        await call
    except TelegramAPIError:
        logger.exception("Bot profile: failed to set %s", label)
