"""Перенести данные из одной базы в другую, например SQLite → Postgres.

    python -m tg_assistant.copy_db sqlite+aiosqlite:///data/bot.db postgresql+asyncpg://...

Обе базы приводятся к последней схеме миграциями; целевая должна быть пустой.
"""

import asyncio
import sys

from .backup import dump, load
from .db import create_engine, run_migrations


async def copy(src_url: str, dst_url: str) -> dict[str, int]:
    src, dst = create_engine(src_url), create_engine(dst_url)
    try:
        async with src.connect() as s:
            data = await dump(s)
        async with dst.begin() as d:
            try:
                return await load(d, data)
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
    finally:
        await src.dispose()
        await dst.dispose()


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    src_url, dst_url = sys.argv[1:]
    run_migrations(src_url)
    run_migrations(dst_url)
    for name, count in asyncio.run(copy(src_url, dst_url)).items():
        print(f"{name}: {count}")


if __name__ == "__main__":
    main()
