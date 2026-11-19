"""Бэкап всей базы в один файл .json.gz — одинаково для SQLite и Postgres.

    python -m tg_assistant.backup export backup.json.gz    # из DATABASE_URL
    python -m tg_assistant.backup restore backup.json.gz   # в пустую базу DATABASE_URL

Бот сам присылает такой файл администраторам (ADMIN_IDS) раз в BACKUP_INTERVAL_HOURS.
"""

import asyncio
import gzip
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Integer, func, select, text
from sqlalchemy.ext.asyncio import AsyncConnection

from .db import Base, create_engine, run_migrations

FORMAT = "tg-assistant-backup/1"
# Кто сейчас лидер — живое состояние узлов, его не переносим.
SKIP_TABLES = {"cluster_nodes"}


def _tables():
    return [t for t in Base.metadata.sorted_tables if t.name not in SKIP_TABLES]


def _encode_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return {"$dt": value.isoformat()}
    return value


def _decode_value(value: Any) -> Any:
    if isinstance(value, dict) and "$dt" in value:
        return datetime.fromisoformat(value["$dt"])
    return value


async def dump(conn: AsyncConnection) -> dict[str, Any]:
    tables = {}
    for table in _tables():
        rows = await conn.execute(select(table))
        tables[table.name] = [
            {key: _encode_value(value) for key, value in row._mapping.items()} for row in rows
        ]
    return {"format": FORMAT, "created_at": datetime.now(UTC).isoformat(), "tables": tables}


async def load(conn: AsyncConnection, data: dict[str, Any]) -> dict[str, int]:
    """Залить данные в пустую базу. Возвращает число строк по таблицам."""
    if data.get("format") != FORMAT:
        raise ValueError(f"Unknown backup format: {data.get('format')!r}")
    for table in _tables():
        if await conn.scalar(select(func.count()).select_from(table)):
            raise ValueError(f"Target table {table.name} is not empty")
    counts = {}
    for table in _tables():
        rows = [
            {key: _decode_value(value) for key, value in row.items() if key in table.c}
            for row in data["tables"].get(table.name, [])
        ]
        if rows:
            await conn.execute(table.insert(), rows)
        counts[table.name] = len(rows)
    await reset_sequences(conn)
    return counts


async def reset_sequences(conn: AsyncConnection) -> None:
    """Postgres: после вставки с явными id счётчики надо передвинуть за максимум."""
    if conn.dialect.name != "postgresql":
        return
    for table in Base.metadata.sorted_tables:
        pk = list(table.primary_key.columns)
        if len(pk) == 1 and isinstance(pk[0].type, Integer) and pk[0].autoincrement:
            await conn.execute(
                text(
                    f"SELECT setval(pg_get_serial_sequence('{table.name}', '{pk[0].name}'), "
                    f"COALESCE(MAX({pk[0].name}), 0) + 1, false) FROM {table.name}"
                )
            )


def encode(data: dict[str, Any]) -> bytes:
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
    return gzip.compress(raw, mtime=0)


def decode(blob: bytes) -> dict[str, Any]:
    return json.loads(gzip.decompress(blob))


async def _export(url: str) -> dict[str, Any]:
    engine = create_engine(url)
    try:
        async with engine.connect() as conn:
            return await dump(conn)
    finally:
        await engine.dispose()


async def _restore(url: str, data: dict[str, Any]) -> dict[str, int]:
    engine = create_engine(url)
    try:
        async with engine.begin() as conn:
            return await load(conn, data)
    finally:
        await engine.dispose()


def main() -> None:
    from .config import DatabaseSettings

    if len(sys.argv) != 3 or sys.argv[1] not in ("export", "restore"):
        raise SystemExit(__doc__)
    command, path = sys.argv[1:]
    url = DatabaseSettings().database_url
    run_migrations(url)
    file = Path(path)
    if command == "export":
        data = asyncio.run(_export(url))
        file.write_bytes(encode(data))
        counts = {name: len(rows) for name, rows in data["tables"].items()}
    else:
        counts = asyncio.run(_restore(url, decode(file.read_bytes())))
    for name, count in counts.items():
        print(f"{name}: {count}")


if __name__ == "__main__":
    main()
