"""Один активный экземпляр бота на общую базу Postgres.

Telegram отдаёт обновления только одному getUpdates, а напоминания должен рассылать ровно
один планировщик. Поэтому экземпляры (ПК, облако) договариваются через Postgres:

* лидером становится тот, кто взял advisory-блокировку ``pg_try_advisory_lock``;
  блокировка живёт, пока открыто соединение, и снимается сама, если узел пропал;
* каждый узел раз в ``interval`` секунд отмечается в таблице ``cluster_nodes``;
* лидер уступает, если видит живой узел с большим приоритетом (ПК вернулся) —
  сначала останавливает бота, потом отпускает блокировку;
* если связь с базой пропала, лидер сразу останавливает бота: блокировку он мог уже потерять.

С SQLite всё это не нужно — бот просто запускается.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

# Произвольный, но постоянный ключ блокировки для этого бота.
LOCK_KEY = 0x74_67_61_31  # "tga1"

# Стандартные TCP keepalive Postgres — 2 часа: столько база держала бы блокировку
# за пропавшим узлом. Делаем ~30 секунд.
_KEEPALIVE = {
    "tcp_keepalives_idle": "10",
    "tcp_keepalives_interval": "5",
    "tcp_keepalives_count": "3",
}

RunBot = Callable[[asyncio.Event], Awaitable[None]]


def uses_leader_election(database_url: str) -> bool:
    return make_url(database_url).get_backend_name() == "postgresql"


def create_lock_engine(database_url: str) -> AsyncEngine:
    connect_args = {}
    if make_url(database_url).get_driver_name() == "asyncpg":
        connect_args = {"server_settings": dict(_KEEPALIVE), "timeout": 10}
    return create_async_engine(database_url, poolclass=NullPool, connect_args=connect_args)


async def _heartbeat(conn: AsyncConnection, name: str, priority: int, leader: bool) -> None:
    await conn.execute(
        text(
            "INSERT INTO cluster_nodes (name, priority, is_leader, seen_at) "
            "VALUES (:name, :priority, :leader, timezone('utc', now())) "
            "ON CONFLICT (name) DO UPDATE SET priority = excluded.priority, "
            "is_leader = excluded.is_leader, seen_at = excluded.seen_at"
        ),
        {"name": name, "priority": priority, "leader": leader},
    )
    await conn.commit()


async def _stronger_peer(conn: AsyncConnection, name: str, priority: int, ttl: float) -> str | None:
    """Имя живого узла с большим приоритетом, если такой есть."""
    peer = await conn.scalar(
        text(
            "SELECT name FROM cluster_nodes WHERE name <> :name AND priority > :priority "
            "AND seen_at > timezone('utc', now()) - make_interval(secs => :ttl) "
            "ORDER BY priority DESC LIMIT 1"
        ),
        {"name": name, "priority": priority, "ttl": ttl},
    )
    await conn.commit()
    return peer


async def _try_lock(conn: AsyncConnection) -> bool:
    got = bool(await conn.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_KEY}))
    await conn.commit()
    return got


async def _unlock(conn: AsyncConnection) -> None:
    await conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
    await conn.commit()


async def _stop_bot(task: asyncio.Task, stop: asyncio.Event, grace: float) -> None:
    stop.set()
    try:
        await asyncio.wait_for(asyncio.shield(task), grace)
    except TimeoutError:
        task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task


async def _lead(
    conn: AsyncConnection,
    run_bot: RunBot,
    shutdown: asyncio.Event,
    *,
    name: str,
    priority: int,
    interval: float,
    ttl: float,
) -> None:
    """Работать лидером, пока не пора уступить. Исключение — потеряна связь с базой."""
    await _heartbeat(conn, name, priority, leader=True)
    stop = asyncio.Event()
    task = asyncio.create_task(run_bot(stop))
    logger.info("Node %s (priority %d) is the leader: bot started", name, priority)
    try:
        while not task.done():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(shutdown.wait(), interval)
            if shutdown.is_set():
                break
            await _heartbeat(conn, name, priority, leader=True)
            peer = await _stronger_peer(conn, name, priority, ttl)
            if peer:
                logger.info("Node %s has higher priority: handing over leadership", peer)
                break
        if task.done() and not shutdown.is_set():
            exc = task.exception()
            logger.error("Bot stopped unexpectedly: %r", exc)
    finally:
        await _stop_bot(task, stop, grace=interval)
    await _heartbeat(conn, name, priority, leader=False)
    await _unlock(conn)


async def run_with_leadership(
    engine: AsyncEngine,
    run_bot: RunBot,
    shutdown: asyncio.Event,
    *,
    name: str,
    priority: int,
    interval: float = 10.0,
    ttl: float = 30.0,
) -> None:
    """Ждать лидерства, работать, уступать — до ``shutdown``."""
    was_standby = False
    while not shutdown.is_set():
        try:
            async with engine.connect() as conn:
                while not shutdown.is_set():
                    await _heartbeat(conn, name, priority, leader=False)
                    if await _try_lock(conn):
                        if peer := await _stronger_peer(conn, name, priority, ttl):
                            # Сильный узел жив и сейчас заберёт блокировку — не мешаем.
                            await _unlock(conn)
                            logger.debug("Node %s is alive: letting it lead", peer)
                        else:
                            was_standby = False
                            await _lead(
                                conn,
                                run_bot,
                                shutdown,
                                name=name,
                                priority=priority,
                                interval=interval,
                                ttl=ttl,
                            )
                            # Уступили — даём сильному узлу взять блокировку.
                            await _sleep(shutdown, interval * 2)
                            continue
                    if not was_standby:
                        logger.info("Node %s is on standby: another node is the leader", name)
                        was_standby = True
                    await _sleep(shutdown, interval)
        except Exception:
            # Связь с базой пропала — бот уже остановлен в _lead, ждём и пробуем снова.
            logger.exception("Leader election: database connection lost, retrying")
            was_standby = False
            await _sleep(shutdown, interval)


async def _sleep(shutdown: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(shutdown.wait(), seconds)
