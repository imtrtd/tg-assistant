"""Отправка наступивших напоминаний.

Источник истины — таблица reminders: планировщик раз в несколько секунд выбирает
наступившие напоминания, поэтому после перезапуска бота ничего не теряется.
"""

import asyncio
import html
import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..db import Reminder
from ..db.archive import purge_older_than
from ..db.digest import build_digest, due_digests, next_digest_at
from ..db.reminders import due_reminders
from .keyboards import fired_keyboard
from .timeparse import next_occurrence

logger = logging.getLogger(__name__)

POLL_INTERVAL = 15.0


def advance(reminder: Reminder, tz_name: str, now: datetime) -> None:
    """После срабатывания: однократное выключить, повторяющееся перенести на следующий раз."""
    if reminder.repeat is None:
        reminder.active = False
        return
    tz = ZoneInfo(tz_name)
    local = reminder.remind_at.astimezone(tz)
    # от max(...) — чтобы после долгого простоя не слать пропущенные повторы пачкой
    after = max(local, now.astimezone(tz))
    reminder.remind_at = next_occurrence(after, local.time(), reminder.repeat, local.weekday())


async def fire_due(
    bot: Bot, session_factory: async_sessionmaker[AsyncSession], now: datetime | None = None
) -> int:
    """Отправить наступившие напоминания. Возвращает число отправленных."""
    now = now or datetime.now(UTC)
    sent = 0
    async with session_factory() as session:
        for reminder, tz_name in await due_reminders(session, now):
            try:
                await bot.send_message(
                    reminder.user_id,
                    f"⏰ {html.escape(reminder.text)}",
                    reply_markup=fired_keyboard(reminder),
                    parse_mode="HTML",
                )
            except TelegramForbiddenError:
                logger.info(
                    "User %s blocked the bot, disabling reminder %s", reminder.user_id, reminder.id
                )
                reminder.active = False
            except TelegramAPIError:
                logger.exception("Failed to send reminder %s, will retry", reminder.id)
                continue
            else:
                sent += 1
                advance(reminder, tz_name, now)
            await session.commit()
    return sent


async def fire_digests(
    bot: Bot, session_factory: async_sessionmaker[AsyncSession], now: datetime | None = None
) -> int:
    """Отправить утренние сводки, время которых наступило. Возвращает число отправленных."""
    now = now or datetime.now(UTC)
    sent = 0
    async with session_factory() as session:
        for user in await due_digests(session, now):
            try:
                text = await build_digest(session, user, now)
                await bot.send_message(user.id, text, parse_mode="HTML")
            except TelegramForbiddenError:
                logger.info("User %s blocked the bot, disabling digest", user.id)
                user.digest_time = None
                user.digest_next_at = None
            except TelegramAPIError:
                logger.exception("Failed to send digest to %s, will retry", user.id)
                continue
            else:
                sent += 1
                # от now — чтобы после простоя не слать пропущенные сводки пачкой
                user.digest_next_at = next_digest_at(user.digest_time, user.timezone, now)
            await session.commit()
    return sent


PURGE_INTERVAL = 3600.0


async def run_scheduler(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    interval: float = POLL_INTERVAL,
    archive_retention_days: int = 0,
) -> None:
    logger.info("Reminder scheduler started (every %.0fs)", interval)
    last_purge = 0.0
    loop = asyncio.get_running_loop()
    while True:
        try:
            await fire_due(bot, session_factory)
            await fire_digests(bot, session_factory)
            if archive_retention_days > 0 and loop.time() - last_purge >= PURGE_INTERVAL:
                last_purge = loop.time()
                async with session_factory() as session:
                    removed = await purge_older_than(session, archive_retention_days)
                if removed:
                    logger.info("Archive retention: removed %s old messages", removed)
        except Exception:
            logger.exception("Reminder scheduler iteration failed")
        await asyncio.sleep(interval)
