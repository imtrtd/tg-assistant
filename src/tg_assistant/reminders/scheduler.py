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


async def run_scheduler(
    bot: Bot, session_factory: async_sessionmaker[AsyncSession], interval: float = POLL_INTERVAL
) -> None:
    logger.info("Reminder scheduler started (every %.0fs)", interval)
    while True:
        try:
            await fire_due(bot, session_factory)
        except Exception:
            logger.exception("Reminder scheduler iteration failed")
        await asyncio.sleep(interval)
