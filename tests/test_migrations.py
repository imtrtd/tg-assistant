import sqlite3

from tg_assistant.db import run_migrations


def test_migrations_create_schema(tmp_path):
    db_path = tmp_path / "nested" / "bot.db"

    run_migrations(f"sqlite+aiosqlite:///{db_path}")

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0] for row in conn.execute("select name from sqlite_master where type='table'")
        }
    assert {
        "users",
        "notes",
        "reminders",
        "archived_messages",
        "message_edits",
        "business_connections",
        "research_watches",
        "research_seen_posts",
    } <= tables
    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("pragma table_info(users)")}
    assert {"digest_time", "digest_next_at"} <= columns
