"""Перенести данные из одной базы в другую, например SQLite → Postgres.

    python -m tg_assistant.copy_db sqlite+aiosqlite:///data/bot.db postgresql+asyncpg://...

Обе базы приводятся к последней схеме миграциями; целевая должна быть пустой.
"""

import asyncio
import sys

from sqlalchemy import Integer, func, select, text

from .db import Base, create_engine, run_migrations


async def copy(src_url: str, dst_url: str) -> dict[str, int]:
    src, dst = create_engine(src_url), create_engine(dst_url)
    counts: dict[str, int] = {}
    try:
        async with src.connect() as s, dst.begin() as d:
            for table in Base.metadata.sorted_tables:
                if await d.scalar(select(func.count()).select_from(table)):
                    raise SystemExit(f"Target table {table.name} is not empty")
            for table in Base.metadata.sorted_tables:
                rows = [dict(r._mapping) for r in await s.execute(select(table))]
                if rows:
                    await d.execute(table.insert(), rows)
                counts[table.name] = len(rows)
            if dst.dialect.name == "postgresql":
                # Счётчики id после вставки с явными id.
                for table in Base.metadata.sorted_tables:
                    pk = list(table.primary_key.columns)
                    if len(pk) == 1 and isinstance(pk[0].type, Integer) and pk[0].autoincrement:
                        await d.execute(
                            text(
                                f"SELECT setval(pg_get_serial_sequence('{table.name}', "
                                f"'{pk[0].name}'), COALESCE(MAX({pk[0].name}), 0) + 1, false) "
                                f"FROM {table.name}"
                            )
                        )
    finally:
        await src.dispose()
        await dst.dispose()
    return counts


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
