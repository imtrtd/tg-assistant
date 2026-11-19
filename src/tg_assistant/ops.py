"""Живучесть: heartbeat со сторожем, пинг healthchecks.io, уведомления и бэкапы в Telegram.

* Heartbeat — каждые 30 секунд процесс пишет время в HEARTBEAT_FILE. Отдельный поток-сторож
  завершает процесс, если цикл событий завис дольше 2 минут; Docker/systemd/Railway
  перезапускают его. ``python -m tg_assistant.ops healthcheck`` — проверка для HEALTHCHECK.
* HEALTHCHECK_PING_URL — адрес проверки на healthchecks.io. Лидер пингует его раз в минуту;
  если не работает ни один узел (выключены ПК и облако), healthchecks.io сам напишет вам.
* Администраторам (ADMIN_IDS) приходит сообщение, когда узел начинает работу, и
  бэкап базы раз в BACKUP_INTERVAL_HOURS (0 — не присылать).
"""

import asyncio
import contextlib
import logging
import os
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiohttp
from aiogram import Bot
from aiogram.types import BufferedInputFile
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from . import backup
from .db import AppState

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 30.0
STALE_AFTER = 120.0
# Насколько сторож может «проспать» сверх своей паузы, прежде чем считать, что спала машина.
SUSPEND_SLACK = 30.0
PING_INTERVAL = 60.0
BACKUP_CHECK_INTERVAL = 600.0
LAST_BACKUP_KEY = "last_backup_at"
# Пауза циклов; в тестах подменяется, чтобы считать итерации без реального ожидания.
_sleep = asyncio.sleep
# Telegram принимает от ботов файлы до 50 МБ.
MAX_BACKUP_BYTES = 49 * 1024 * 1024


class Heartbeat:
    """Отметки живости цикла событий и сторож, который перезапускает зависший процесс."""

    def __init__(self, path: str | Path, stale_after: float = STALE_AFTER):
        self.path = Path(path)
        self.stale_after = stale_after
        self._last = time.monotonic()

    def beat(self) -> None:
        self._last = time.monotonic()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(datetime.now(UTC).isoformat())
        except OSError:
            logger.warning("Cannot write heartbeat file %s", self.path, exc_info=True)

    def stale(self) -> bool:
        return time.monotonic() - self._last > self.stale_after

    async def run(self, interval: float = HEARTBEAT_INTERVAL) -> None:
        while True:
            self.beat()
            await asyncio.sleep(interval)

    def check(self, slept: float, check_every: float) -> bool:
        """Вызывается сторожем после паузы. True — цикл событий завис, пора выходить.

        Если и сам сторож проспал намного дольше положенного, на паузе была вся машина
        (сон ноутбука, пауза ВМ). Это не зависание: даём циклу время проснуться.
        """
        if slept > check_every + SUSPEND_SLACK:
            logger.warning("System was suspended for ~%.0fs, resetting watchdog", slept)
            self._last = time.monotonic()
            return False
        return self.stale()

    def start_watchdog(self, check_every: float = HEARTBEAT_INTERVAL) -> threading.Thread:
        def watch() -> None:
            while True:
                started = time.monotonic()
                time.sleep(check_every)
                if self.check(time.monotonic() - started, check_every):
                    logger.critical(
                        "Event loop is stuck for over %.0fs, exiting so the bot is restarted",
                        self.stale_after,
                    )
                    logging.shutdown()
                    os._exit(70)

        thread = threading.Thread(target=watch, name="watchdog", daemon=True)
        thread.start()
        return thread


def heartbeat_is_fresh(path: str | Path, stale_after: float = STALE_AFTER) -> bool:
    try:
        return time.time() - Path(path).stat().st_mtime < stale_after
    except OSError:
        return False


async def ping_loop(url: str, interval: float = PING_INTERVAL) -> None:
    """Пинговать healthchecks.io, пока узел — лидер."""
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as http:
        while True:
            try:
                async with http.get(url) as response:
                    if response.status >= 400:
                        logger.warning("Healthcheck ping returned HTTP %s", response.status)
            except (aiohttp.ClientError, TimeoutError) as exc:
                logger.warning("Healthcheck ping failed: %r", exc)
            await _sleep(interval)


async def notify_admins(bot: Bot, admin_ids, text: str) -> None:
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML")
        except Exception:
            logger.exception("Failed to notify admin %s", admin_id)


async def _last_backup(session: AsyncSession) -> datetime | None:
    state = await session.get(AppState, LAST_BACKUP_KEY)
    return datetime.fromisoformat(state.value) if state else None


async def send_backup(
    bot: Bot, session_factory: async_sessionmaker[AsyncSession], admin_ids, node_name: str
) -> bool:
    """Выгрузить базу и отправить администраторам. True — хотя бы одному дошло."""
    async with session_factory() as session:
        conn = await session.connection()
        blob = backup.encode(await backup.dump(conn))
    now = datetime.now(UTC)
    if len(blob) > MAX_BACKUP_BYTES:
        logger.error("Backup is %d bytes, too big for Telegram; skipped", len(blob))
        await notify_admins(
            bot,
            admin_ids,
            f"Бэкап базы — {len(blob) // 1024 // 1024} МБ, больше лимита Telegram (50 МБ). "
            "Сократите ARCHIVE_RETENTION_DAYS или делайте копии на сервере.",
        )
        return False
    name = f"tg-assistant-{now:%Y%m%d-%H%M}.json.gz"
    caption = (
        f"Бэкап базы, узел <code>{node_name}</code>, {len(blob) // 1024 + 1} КБ.\n"
        "Восстановление: <code>python -m tg_assistant.backup restore файл</code>"
    )
    delivered = False
    for admin_id in admin_ids:
        try:
            await bot.send_document(
                admin_id,
                BufferedInputFile(blob, filename=name),
                caption=caption,
                parse_mode="HTML",
                disable_notification=True,
            )
            delivered = True
        except Exception:
            logger.exception("Failed to send backup to admin %s", admin_id)
    return delivered


async def backup_loop(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    admin_ids,
    node_name: str,
    interval_hours: float,
    check_every: float = BACKUP_CHECK_INTERVAL,
) -> None:
    """Раз в interval_hours присылать бэкап. Время последнего хранится в базе — общее для узлов."""
    period = timedelta(hours=interval_hours)
    while True:
        try:
            async with session_factory() as session:
                last = await _last_backup(session)
            now = datetime.now(UTC)
            if last is None or now - last >= period:
                if await send_backup(bot, session_factory, admin_ids, node_name):
                    async with session_factory() as session:
                        await session.merge(AppState(key=LAST_BACKUP_KEY, value=now.isoformat()))
                        await session.commit()
                    logger.info("Backup sent to admins")
        except Exception:
            logger.exception("Backup iteration failed")
        await _sleep(check_every)


async def cancel(task: asyncio.Task | None) -> None:
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def main() -> None:
    from .config import DEFAULT_HEARTBEAT_FILE

    if sys.argv[1:] != ["healthcheck"]:
        raise SystemExit("usage: python -m tg_assistant.ops healthcheck")
    path = os.environ.get("HEARTBEAT_FILE", DEFAULT_HEARTBEAT_FILE)
    raise SystemExit(0 if heartbeat_is_fresh(path) else 1)


if __name__ == "__main__":
    main()
