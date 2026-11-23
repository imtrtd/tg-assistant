"""Фоновая проверка наблюдений. Запускается вместе с ботом, только на лидере."""

import asyncio
import logging
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import LinkPreviewOptions
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..db.models import User
from ..topics import RESEARCH, topic_kind
from .config import ResearchConfig
from .formatting import format_watch_alert, load_timezone
from .store import all_watches
from .watch_service import collect_new_hits

logger = logging.getLogger(__name__)


async def _timezone_for(session: AsyncSession, user_id: int, fallback: str) -> ZoneInfo:
    name = await session.scalar(select(User.timezone).where(User.id == user_id))
    return load_timezone(name or fallback)


async def deliver_due(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    client,
    config: ResearchConfig,
    fallback_timezone: str,
) -> int:
    """Найти новые упоминания и прислать их в чат, где включили наблюдение."""
    async with session_factory() as session:
        watches = await all_watches(session)
        if not watches:
            return 0
        alerts = await collect_new_hits(client, session, watches, config)
        zones = {
            watch.user_id: await _timezone_for(session, watch.user_id, fallback_timezone)
            for watch, _hit in alerts
        }
    sent = 0
    for watch, hit in alerts:
        text = format_watch_alert(watch.term, hit, zones.get(watch.user_id, ZoneInfo("UTC")))
        try:
            with topic_kind(RESEARCH):
                await bot.send_message(
                    watch.chat_id,
                    text,
                    parse_mode="HTML",
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                )
        except TelegramAPIError:
            logger.exception("Failed to deliver watch alert to chat %s", watch.chat_id)
        else:
            sent += 1
    return sent


async def run_watch_loop(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    client,
    config: ResearchConfig,
    fallback_timezone: str,
) -> None:
    interval = max(30, config.watch_interval_seconds)
    logger.info("Public mention watch started (every %ss)", interval)
    await asyncio.sleep(min(20, interval))
    while True:
        try:
            await deliver_due(bot, session_factory, client, config, fallback_timezone)
        except Exception:
            logger.exception("Mention watch iteration failed")
        await asyncio.sleep(interval)
