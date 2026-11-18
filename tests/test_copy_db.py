import asyncio
import os

from sqlalchemy import select

from tg_assistant.copy_db import copy
from tg_assistant.db import Note, User, create_engine, create_session_factory, run_migrations
from tg_assistant.db import notes as repo


def test_copy_moves_rows_and_keeps_ids(tmp_path):
    # TEST_COPY_TARGET_URL=postgresql+asyncpg://... — проверить перенос в пустой Postgres.
    src = f"sqlite+aiosqlite:///{tmp_path / 'src.db'}"
    dst = os.environ.get("TEST_COPY_TARGET_URL", f"sqlite+aiosqlite:///{tmp_path / 'dst.db'}")
    run_migrations(src)  # миграции вызываются вне event loop
    run_migrations(dst)
    asyncio.run(_check_copy(src, dst))


async def _check_copy(src: str, dst: str) -> None:
    engine = create_engine(src)
    async with create_session_factory(engine)() as session:
        session.add(User(id=1, first_name="Аня", timezone="UTC"))
        await session.flush()
        await repo.add_note(session, 1, "a")
        await repo.add_note(session, 1, "b")
    await engine.dispose()

    counts = await copy(src, dst)

    assert counts["users"] == 1 and counts["notes"] == 2
    engine = create_engine(dst)
    async with create_session_factory(engine)() as session:
        await repo.add_note(session, 1, "c")  # новые id не пересекаются со старыми
        ids = (await session.scalars(select(Note.id).order_by(Note.id))).all()
    await engine.dispose()
    assert ids == [1, 2, 3]
