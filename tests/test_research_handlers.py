from datetime import UTC, datetime

from tg_assistant.bot import create_dispatcher
from tg_assistant.config import Settings

from .conftest import ALLOWED_ID, sent_texts, update_from


async def test_search_is_off_until_session_is_configured(bot, dp):
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/search imtrtd last:7d"))
    assert "Публичный поиск выключен" in sent_texts(bot)[-1]


async def test_sources_asks_for_a_topic(bot, session_factory, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "42:TEST")
    monkeypatch.setenv("ALLOWED_USER_IDS", str(ALLOWED_ID))
    monkeypatch.setenv("API_ID", "1")
    monkeypatch.setenv("API_HASH", "hash")
    monkeypatch.setenv("TELEGRAM_SESSION", "1")
    dispatcher = create_dispatcher(Settings(_env_file=None), session_factory)
    dispatcher["research_client"] = object()

    await dispatcher.feed_update(bot, update_from(ALLOWED_ID, "/sources"))

    assert "/sources osint" in sent_texts(bot)[-1]
    assert "/find" in sent_texts(bot)[-1]


async def test_watch_roundtrip(bot, session_factory, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "42:TEST")
    monkeypatch.setenv("ALLOWED_USER_IDS", str(ALLOWED_ID))
    monkeypatch.setenv("API_ID", "1")
    monkeypatch.setenv("API_HASH", "hash")
    monkeypatch.setenv("TELEGRAM_SESSION", "1")
    dispatcher = create_dispatcher(Settings(_env_file=None), session_factory)
    dispatcher["research_client"] = object()

    await dispatcher.feed_update(bot, update_from(ALLOWED_ID, "/watch  Brand   Name "))
    assert "Слежу за упоминаниями" in sent_texts(bot)[-1]
    assert "Brand Name" in sent_texts(bot)[-1]

    await dispatcher.feed_update(bot, update_from(ALLOWED_ID, "/watches"))
    assert "Brand Name" in sent_texts(bot)[-1]

    await dispatcher.feed_update(bot, update_from(ALLOWED_ID, "/unwatch brand name"))
    assert "Больше не слежу" in sent_texts(bot)[-1]

    await dispatcher.feed_update(bot, update_from(ALLOWED_ID, "/watches"))
    assert "нет активных наблюдений" in sent_texts(bot)[-1]


async def test_search_formats_public_hit(bot, session_factory, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "42:TEST")
    monkeypatch.setenv("ALLOWED_USER_IDS", str(ALLOWED_ID))
    monkeypatch.setenv("API_ID", "1")
    monkeypatch.setenv("API_HASH", "hash")
    monkeypatch.setenv("TELEGRAM_SESSION", "1")

    async def fake_search(_client, query, _config):
        assert query.text == "imtrtd"
        assert query.channels == ("durov",)
        return [
            {
                "peer_id": 1,
                "message_id": 2,
                "username": "durov",
                "title": "Durov",
                "date": datetime(2024, 1, 2, tzinfo=UTC),
                "url": "https://t.me/durov/2",
                "snippet": "hello imtrtd",
                "views": 3,
            }
        ]

    monkeypatch.setattr("tg_assistant.handlers.research.search_posts", fake_search)
    dispatcher = create_dispatcher(Settings(_env_file=None), session_factory)
    dispatcher["research_client"] = object()

    await dispatcher.feed_update(bot, update_from(ALLOWED_ID, "/search imtrtd in:@durov"))

    text = sent_texts(bot)[-1]
    assert "imtrtd" in text
    assert "https://t.me/durov/2" in text
    assert "hello imtrtd" in text
