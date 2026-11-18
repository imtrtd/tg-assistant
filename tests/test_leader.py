"""Выбор лидера на общей базе Postgres. Нужен TEST_DATABASE_URL=postgresql+asyncpg://..."""

import asyncio
import os

import pytest

from tg_assistant.db import Base
from tg_assistant.leader import create_lock_engine, run_with_leadership, uses_leader_election

URL = os.environ.get("TEST_DATABASE_URL", "")
pg_only = pytest.mark.skipif(not uses_leader_election(URL or "sqlite://"), reason="needs Postgres")


def test_only_postgres_uses_election():
    assert uses_leader_election("postgresql+asyncpg://u:p@h/db")
    assert not uses_leader_election("sqlite+aiosqlite:///data/bot.db")


class Node:
    def __init__(self, name: str, priority: int):
        self.name, self.priority = name, priority
        self.running = False
        self.starts = 0
        self.shutdown = asyncio.Event()
        self.engine = create_lock_engine(URL)

    async def run_bot(self, stop: asyncio.Event) -> None:
        self.running, self.starts = True, self.starts + 1
        try:
            await stop.wait()
        finally:
            self.running = False

    def start(self) -> asyncio.Task:
        return asyncio.create_task(
            run_with_leadership(
                self.engine,
                self.run_bot,
                self.shutdown,
                name=self.name,
                priority=self.priority,
                interval=0.2,
                ttl=0.6,
            )
        )


async def wait_for(cond):
    async with asyncio.timeout(5):
        for _ in iter(cond, True):  # noqa: B007 — опрашиваем, пока cond() не станет True
            await asyncio.sleep(0.05)


@pg_only
async def test_failover_and_handover():
    setup = create_lock_engine(URL)
    async with setup.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await setup.dispose()

    cloud, pc = Node("cloud", 0), Node("pc", 10)
    cloud_task = cloud.start()
    await wait_for(lambda: cloud.running)  # ПК выключен — работает облако

    pc_task = pc.start()
    await wait_for(lambda: pc.running and not cloud.running)  # ПК включился — забрал
    for _ in range(10):  # и никогда не работают оба сразу
        assert not (pc.running and cloud.running)
        await asyncio.sleep(0.1)

    pc.shutdown.set()
    await pc_task
    await wait_for(lambda: cloud.running)  # ПК снова выключили — облако подхватило
    assert cloud.starts == 2

    cloud.shutdown.set()
    await cloud_task
    assert not cloud.running
    await pc.engine.dispose()
    await cloud.engine.dispose()


@pg_only
async def test_leader_stops_bot_when_database_connection_is_lost():
    from sqlalchemy import text

    from tg_assistant.leader import LOCK_KEY

    setup = create_lock_engine(URL)
    async with setup.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    node = Node("solo", 0)
    task = node.start()
    await wait_for(lambda: node.running)
    first = node.starts

    async with setup.connect() as conn:  # обрываем соединение лидера со стороны базы
        await conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_locks "
                "WHERE locktype = 'advisory' AND objid = :key"
            ),
            {"key": LOCK_KEY},
        )
        await conn.commit()
    await wait_for(lambda: not node.running)
    await wait_for(lambda: node.running and node.starts == first + 1)  # переподключился

    node.shutdown.set()
    await task
    await node.engine.dispose()
    await setup.dispose()
