import io
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiohttp.test_utils import TestClient, TestServer

from tg_assistant.config import Settings
from tg_assistant.db import ArchivedMessage, BusinessConnection, MessageEdit, User
from tg_assistant.web import LoginTokens, create_web_app

from .test_web import ANYA, BORIS, TOKEN, tma

T0 = datetime(2026, 11, 14, 10, 0, tzinfo=UTC)


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("ALLOWED_USER_IDS", f"{ANYA},{BORIS}")
    monkeypatch.setenv("WEB_APP_URL", "https://bot.example.com")
    return Settings(_env_file=None)


@pytest.fixture
def bot():
    bot = MagicMock()
    bot.get_file = AsyncMock(return_value=MagicMock(file_path="photos/1.jpg", file_size=3))
    bot.download_file = AsyncMock(return_value=io.BytesIO(b"JPG"))
    bot.send_message = AsyncMock()
    bot.send_voice = AsyncMock()
    bot.send_photo = AsyncMock()
    return bot


@pytest.fixture
async def client(settings, session_factory, bot):
    app = create_web_app(settings, session_factory, LoginTokens(), bot)
    async with TestClient(TestServer(app)) as client:
        yield client


def msg(owner, chat, message_id, *, text="t", sent=T0, **extra):
    return ArchivedMessage(
        owner_id=owner,
        chat_id=chat,
        chat_title=extra.pop("chat_title", f"чат {chat}"),
        message_id=message_id,
        sender_id=extra.pop("sender_id", chat),
        sender_name=extra.pop("sender_name", "Пётр"),
        outgoing=extra.pop("outgoing", False),
        text=text,
        sent_at=sent,
        **extra,
    )


@pytest.fixture
async def data(session_factory):
    async with session_factory() as session:
        session.add_all(
            [
                User(id=ANYA, first_name="Аня", timezone="Europe/Moscow"),
                User(id=BORIS, first_name="Борис", timezone="UTC"),
                BusinessConnection(id="c1", owner_id=ANYA, is_enabled=True, updated_at=T0),
            ]
        )
        rows = [
            msg(ANYA, 555, i, text=f"сообщение {i}", sent=T0 + timedelta(minutes=i))
            for i in range(1, 61)
        ]
        rows[0].deleted_at = T0 + timedelta(hours=1)
        rows[1].edited_at = T0 + timedelta(hours=2)
        rows.append(msg(ANYA, 777, 1, text="другой чат", chat_title="Вера", sender_name="Вера"))
        rows.append(msg(ANYA, 555, 100, text=None, media_type="photo", file_id="ph1"))
        rows.append(msg(ANYA, 555, 101, text=None, media_type="voice", file_id="vo1"))
        rows.append(msg(BORIS, 555, 1, text="секрет Бориса", chat_title="чужой"))
        session.add_all(rows)
        await session.commit()
        session.add(MessageEdit(message_id=rows[1].id, text="старая версия", replaced_at=T0))
        await session.commit()
        return {
            r.message_id
            if r.owner_id == ANYA and r.chat_id == 555
            else (r.owner_id, r.chat_id, r.message_id): r.id
            for r in rows
        }


async def test_overview_and_notify_settings(client, data):
    auth = tma(ANYA)
    body = await (await client.get("/api/archive", headers=auth)).json()
    assert body["connected"] is True
    assert (body["chats"], body["messages"], body["edited"], body["deleted"]) == (2, 63, 1, 1)
    assert body["notify_edits"] and body["notify_deletes"]

    response = await client.put(
        "/api/archive/settings", json={"notify_deletes": False}, headers=auth
    )
    assert (await response.json())["notify_deletes"] is False
    bad = await client.put("/api/archive/settings", json={"notify_edits": "yes"}, headers=auth)
    assert bad.status == 400


async def test_chats_list_only_own(client, data):
    body = await (await client.get("/api/archive/chats", headers=tma(ANYA))).json()
    assert {c["title"] for c in body["items"]} == {"чат 555", "Вера"}
    chat = next(c for c in body["items"] if c["chat_id"] == 555)
    assert (chat["messages"], chat["deleted"]) == (62, 1)

    boris = await (await client.get("/api/archive/chats", headers=tma(BORIS))).json()
    assert [c["title"] for c in boris["items"]] == ["чужой"]


async def test_chat_messages_paginate_with_edits(client, data):
    auth = tma(ANYA)
    first = await (await client.get("/api/archive/chats/555", headers=auth)).json()
    assert first["has_more"] and len(first["items"]) == 50
    ids = [m["id"] for m in first["items"]]
    assert ids == sorted(ids)  # по возрастанию внутри страницы
    assert first["items"][-1]["media_type"] == "voice"

    older = await (await client.get(f"/api/archive/chats/555?before={ids[0]}", headers=auth)).json()
    assert not older["has_more"] and len(older["items"]) == 12
    by_text = {m["text"]: m for m in older["items"]}
    assert by_text["сообщение 1"]["deleted_at"].endswith("Z")
    assert by_text["сообщение 2"]["edits"] == [
        {"text": "старая версия", "replaced_at": "2026-11-14T10:00:00Z"}
    ]


async def test_foreign_chat_is_not_found(client, data):
    assert (await client.get("/api/archive/chats/555", headers=tma(BORIS))).status == 200
    assert (await client.get("/api/archive/chats/777", headers=tma(BORIS))).status == 404
    assert (await client.get("/api/archive/chats/555?before=x", headers=tma(ANYA))).status == 400


async def test_deleted_list(client, data):
    body = await (await client.get("/api/archive/deleted", headers=tma(ANYA))).json()
    assert [m["text"] for m in body["items"]] == ["сообщение 1"]


async def test_photo_is_served_through_bot(client, data, bot):
    photo_id = data[100]
    response = await client.get(f"/api/archive/messages/{photo_id}/media", headers=tma(ANYA))
    assert response.status == 200
    assert response.headers["Content-Type"] == "image/jpeg" and await response.read() == b"JPG"
    bot.get_file.assert_awaited_once_with("ph1")

    voice = await client.get(f"/api/archive/messages/{data[101]}/media", headers=tma(ANYA))
    assert voice.status == 404  # голосовое не показываем картинкой — только «прислать»


async def test_media_of_foreign_message_is_hidden(client, data, bot):
    foreign = data[(BORIS, 555, 1)]
    response = await client.get(f"/api/archive/messages/{foreign}/media", headers=tma(ANYA))
    assert response.status == 404
    bot.get_file.assert_not_awaited()


async def test_expired_file_is_reported(client, data, bot):
    bot.get_file.side_effect = TelegramBadRequest(method=MagicMock(), message="file is too old")
    response = await client.get(f"/api/archive/messages/{data[100]}/media", headers=tma(ANYA))
    assert response.status == 410


async def test_send_to_telegram_goes_to_owner_only(client, data, bot):
    response = await client.post(
        f"/api/archive/messages/{data[101]}/send", json={}, headers=tma(ANYA)
    )
    assert response.status == 200
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.args[0] == ANYA
    assert "Из архива" in bot.send_message.await_args.args[1]
    bot.send_voice.assert_awaited_once_with(chat_id=ANYA, voice="vo1")

    foreign = data[(BORIS, 555, 1)]
    other = await client.post(f"/api/archive/messages/{foreign}/send", json={}, headers=tma(ANYA))
    assert other.status == 404


async def test_archive_requires_auth(client, data):
    assert (await client.get("/api/archive")).status == 401
    assert (await client.get("/api/archive/chats/555")).status == 401


async def test_without_bot_media_is_unavailable(settings, session_factory, data):
    app = create_web_app(settings, session_factory, LoginTokens())
    async with TestClient(TestServer(app)) as client:
        media = await client.get(f"/api/archive/messages/{data[100]}/media", headers=tma(ANYA))
        send = await client.post(
            f"/api/archive/messages/{data[100]}/send", json={}, headers=tma(ANYA)
        )
    assert media.status == 404 and send.status == 503


async def test_page_includes_archive_script(client):
    page = await (await client.get("/")).text()
    assert page.index("/static/archive.js") < page.index("/static/app.js")
    assert (await client.get("/static/archive.js")).status == 200
    csp = (await client.get("/")).headers["Content-Security-Policy"]
    assert "img-src 'self' data: blob:" in csp
