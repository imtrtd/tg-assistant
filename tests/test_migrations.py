import sqlite3

from tg_assistant.db import run_migrations


def test_migrations_create_schema(tmp_path):
    db_path = tmp_path / "nested" / "bot.db"

    run_migrations(f"sqlite+aiosqlite:///{db_path}")

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0] for row in conn.execute("select name from sqlite_master where type='table'")
        }
    assert {"users", "notes", "reminders", "alembic_version"} <= tables
