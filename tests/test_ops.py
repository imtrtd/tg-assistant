import asyncio
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from aiogram.methods import SendDocument
from aiohttp import web
from sqlalchemy.ext.asyncio import create_async_engine

from tg_assistant import backup, ops
from tg_assistant.db import AppState, Base, Reminder, User, create_session_factory
from tg_assistant.db import notes as notes_repo

from .conftest import sent_methods


async def _fill(session_factory):
    async with session_factory() as session:
        session.add(User(id=1, first_name="Аня", timezone="Europe/Kyiv"))
        await session.flush()
        session.add(
            Reminder(
                user_id=1, text="позвонить", remind_at=datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
            )
        )
        await session.commit()
        await notes_repo.add_note(session, 1, "заметка #дом")


async def test_backup_roundtrip_into_empty_database(session_factory):
    await _fill(session_factory)
    async with session_factory() as session:
        blob = backup.encode(await backup.dump(await session.connection()))

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with engine.begin() as conn:
        counts = await backup.load(conn, backup.decode(blob))
    assert counts["users"] == 1 and counts["notes"] == 1 and counts["reminders"] == 1
    async with create_session_factory(engine)() as session:
        restored = await session.get(Reminder, 1)
        assert restored.remind_at == datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
    async with engine.begin() as conn:  # повторно в непустую — отказ
        with pytest.raises(ValueError, match="not empty"):
            await backup.load(conn, backup.decode(blob))
    await engine.dispose()


def test_heartbeat_file_and_staleness(tmp_path):
    path = tmp_path / "data" / "heartbeat"
    assert not ops.heartbeat_is_fresh(path)
    hb = ops.Heartbeat(path, stale_after=60)
    hb.beat()
    assert ops.heartbeat_is_fresh(path)
    assert not hb.stale()
    old = path.stat().st_mtime - 300
    os.utime(path, (old, old))
    assert not ops.heartbeat_is_fresh(path)
    hb._last -= 120
    assert hb.stale()


async def test_send_backup_to_admins(bot, session_factory):
    await _fill(session_factory)
    assert await ops.send_backup(bot, session_factory, {7, 8}, "pc")
    docs = sent_methods(bot, SendDocument)
    assert sorted(d.chat_id for d in docs) == [7, 8]
    assert docs[0].document.filename.endswith(".json.gz")
    assert "pc" in docs[0].caption
    data = backup.decode(docs[0].document.data)
    assert len(data["tables"]["notes"]) == 1


async def test_backup_loop_respects_interval(bot, session_factory):
    await _fill(session_factory)
    task = asyncio.create_task(
        ops.backup_loop(bot, session_factory, {7}, "pc", interval_hours=24, check_every=0.01)
    )
    await asyncio.sleep(0.2)
    task.cancel()
    assert len(sent_methods(bot, SendDocument)) == 1  # одна копия, а не на каждой проверке

    async with session_factory() as session:  # прошли сутки — пора снова
        state = await session.get(AppState, ops.LAST_BACKUP_KEY)
        state.value = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
        await session.commit()
    task = asyncio.create_task(
        ops.backup_loop(bot, session_factory, {7}, "pc", interval_hours=24, check_every=0.01)
    )
    await asyncio.sleep(0.2)
    task.cancel()
    assert len(sent_methods(bot, SendDocument)) == 2


async def test_ping_loop_hits_healthcheck_url():
    hits = []

    async def handler(request):
        hits.append(request.path)
        return web.Response(text="OK")

    app = web.Application()
    app.router.add_get("/ping/abc", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    task = asyncio.create_task(ops.ping_loop(f"http://127.0.0.1:{port}/ping/abc", interval=0.05))
    await asyncio.sleep(0.3)
    task.cancel()
    await runner.cleanup()
    assert len(hits) >= 2


async def test_notify_admins_survives_errors():
    bot = AsyncMock()
    bot.send_message.side_effect = [RuntimeError("blocked"), None]
    await ops.notify_admins(bot, [1, 2], "hi")
    assert bot.send_message.await_count == 2
