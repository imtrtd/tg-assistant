"""Команды публичного поиска. Сессия Telethon и лимиты приходят из диспетчера."""

import logging
from datetime import UTC, datetime

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import LinkPreviewOptions, Message
from sqlalchemy.ext.asyncio import AsyncSession
from telethon import TelegramClient

from ..config import Settings
from ..db import User
from ..research.channel_info import fetch_channel_summary
from ..research.config import research_config
from ..research.find_chats import find_chats
from ..research.flood import FloodLimitExceeded
from ..research.formatting import (
    date_range_note,
    format_channel_summary,
    format_find_results,
    format_search_results,
    load_timezone,
)
from ..research.parse import ParseError, normalize_watch_term, parse_channel_ref, parse_search_query
from ..research.rate_limit import SlidingWindowLimiter
from ..research.search_posts import search_posts
from ..research.store import add_watch, list_watches, remove_watch

logger = logging.getLogger(__name__)

MAX_MESSAGE = 3900
NOT_CONFIGURED = (
    "Публичный поиск выключен.\n"
    "Нужны API_ID, API_HASH и TELEGRAM_SESSION "
    "(строку сессии выдаёт <code>python -m tg_assistant.research.login</code>)."
)
_PREVIEW = LinkPreviewOptions(is_disabled=True)


def _split_chunk(text: str, limit: int) -> tuple[str, str]:
    if len(text) <= limit:
        return text, ""
    cut = text.rfind("\n", 0, limit)
    if cut < limit // 2:
        cut = limit
    return text[:cut].rstrip(), text[cut:].lstrip()


async def _reply(message: Message, text: str) -> None:
    remaining = text
    while remaining:
        chunk, remaining = _split_chunk(remaining, MAX_MESSAGE)
        await message.answer(chunk, parse_mode="HTML", link_preview_options=_PREVIEW)


def _friendly_error(exc: Exception) -> str:
    if isinstance(exc, ParseError):
        return str(exc)
    if isinstance(exc, FloodLimitExceeded):
        return f"Telegram временно ограничил запросы (FloodWait {exc.seconds} с). Попробуйте позже."
    if isinstance(exc, ValueError):
        return str(exc)
    logger.exception("Research command failed")
    return "Не удалось выполнить запрос. Попробуйте позже или уточните условие."


async def _ready(
    message: Message,
    user: User,
    settings: Settings,
    client: TelegramClient | None,
    limiter: SlidingWindowLimiter,
) -> bool:
    if client is None or not settings.research_enabled:
        await _reply(message, NOT_CONFIGURED)
        return False
    result = limiter.check(user.id)
    if result.allowed:
        return True
    wait = max(1, int(result.retry_after + 0.999))
    await message.answer(f"Слишком много запросов. Повторите через {wait} с.")
    return False


async def cmd_search(
    message: Message,
    command: CommandObject,
    user: User,
    settings: Settings,
    research_client: TelegramClient | None,
    research_limiter: SlidingWindowLimiter,
) -> None:
    if not await _ready(message, user, settings, research_client, research_limiter):
        return
    config = research_config(settings)
    assert config is not None and research_client is not None
    tz = load_timezone(user.timezone)
    try:
        query = parse_search_query((command.args or "").strip(), now=datetime.now(UTC))
        await message.bot.send_chat_action(message.chat.id, "typing")
        hits = await search_posts(research_client, query, config)
        note = date_range_note(query.date_range.start, query.date_range.end, tz)
        if query.channels:
            extra = "каналы: " + ", ".join(f"@{name}" for name in query.channels)
            note = f"{note}; {extra}" if note else extra
        await _reply(message, format_search_results(query.text, hits, tz, date_note=note))
    except Exception as exc:
        await _reply(message, _friendly_error(exc))


async def cmd_sources(
    message: Message,
    command: CommandObject,
    user: User,
    settings: Settings,
    research_client: TelegramClient | None,
    research_limiter: SlidingWindowLimiter,
) -> None:
    if not await _ready(message, user, settings, research_client, research_limiter):
        return
    topic = (command.args or "").strip()
    if len(topic) < 2:
        await _reply(
            message,
            "Укажите тему: /sources osint\n"
            "Поиск по заметкам по-прежнему /find. /sources ищет публичные каналы и чаты.",
        )
        return
    config = research_config(settings)
    assert config is not None and research_client is not None
    try:
        await message.bot.send_chat_action(message.chat.id, "typing")
        chats = await find_chats(research_client, topic, config)
        await _reply(message, format_find_results(topic, chats))
    except Exception as exc:
        await _reply(message, _friendly_error(exc))


async def cmd_channel(
    message: Message,
    command: CommandObject,
    user: User,
    settings: Settings,
    research_client: TelegramClient | None,
    research_limiter: SlidingWindowLimiter,
) -> None:
    if not await _ready(message, user, settings, research_client, research_limiter):
        return
    config = research_config(settings)
    assert config is not None and research_client is not None
    tz = load_timezone(user.timezone)
    try:
        username = parse_channel_ref(command.args or "")
        await message.bot.send_chat_action(message.chat.id, "typing")
        info, stats = await fetch_channel_summary(research_client, username, config)
        await _reply(message, format_channel_summary(info, stats, tz))
    except Exception as exc:
        await _reply(message, _friendly_error(exc))


async def cmd_watch(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    user: User,
    settings: Settings,
    research_client: TelegramClient | None,
    research_limiter: SlidingWindowLimiter,
) -> None:
    if not await _ready(message, user, settings, research_client, research_limiter):
        return
    try:
        term = normalize_watch_term(command.args or "")
        watch, created = await add_watch(session, message.chat.id, user.id, term)
        if created:
            await _reply(
                message,
                f"Слежу за упоминаниями «{watch.term}» в публичных каналах. "
                f"Новые совпадения придут сюда. Снять: /unwatch {watch.term}",
            )
        else:
            await _reply(message, f"Это выражение уже в списке наблюдения (id {watch.id}).")
    except Exception as exc:
        await _reply(message, _friendly_error(exc))


async def cmd_unwatch(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    user: User,
    settings: Settings,
    research_client: TelegramClient | None,
    research_limiter: SlidingWindowLimiter,
) -> None:
    if not await _ready(message, user, settings, research_client, research_limiter):
        return
    try:
        term = normalize_watch_term(command.args or "")
        if await remove_watch(session, message.chat.id, term):
            await _reply(message, f"Больше не слежу за «{term}».")
        else:
            await _reply(message, "Такого наблюдения в этом чате нет. Список: /watches")
    except Exception as exc:
        await _reply(message, _friendly_error(exc))


async def cmd_watches(
    message: Message,
    session: AsyncSession,
    user: User,
    settings: Settings,
    research_client: TelegramClient | None,
    research_limiter: SlidingWindowLimiter,
) -> None:
    if not await _ready(message, user, settings, research_client, research_limiter):
        return
    watches = await list_watches(session, message.chat.id)
    if not watches:
        await _reply(message, "В этом чате нет активных наблюдений. Добавить: /watch термин")
        return
    lines = ["Наблюдения в этом чате:"]
    lines.extend(f"· {watch.term}" for watch in watches)
    await _reply(message, "\n".join(lines))


def create_router() -> Router:
    router = Router(name="research")
    router.message.register(cmd_search, Command("search"))
    router.message.register(cmd_sources, Command("sources"))
    router.message.register(cmd_channel, Command("channel"))
    router.message.register(cmd_watch, Command("watch"))
    router.message.register(cmd_unwatch, Command("unwatch"))
    router.message.register(cmd_watches, Command("watches"))
    return router
