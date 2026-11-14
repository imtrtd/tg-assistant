import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import aiohttp
import pytest
from aiohttp.test_utils import TestClient, TestServer

from tg_assistant.config import Settings
from tg_assistant.db import User
from tg_assistant.db import notes as notes_repo
from tg_assistant.db import reminders as reminders_repo
from tg_assistant.web import LoginTokens, create_web_app
from tg_assistant.web.auth import SESSION_COOKIE, SESSION_TTL, SessionSigner

TOKEN = "42:TEST"
ANYA, BORIS, STRANGER = 100, 200, 999
JSON = {"Content-Type": "application/json"}


def init_data(user_id: int, *, auth_date: float | None = None, token: str = TOKEN) -> str:
    """Строка initData, подписанная так же, как это делает Telegram."""
    data = {
        "auth_date": str(int(auth_date or time.time())),
        "query_id": "AAE",
        "user": json.dumps({"id": user_id, "first_name": "Аня"}, ensure_ascii=False),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


def tma(user_id: int, **kwargs) -> dict:
    return {"Authorization": f"tma {init_data(user_id, **kwargs)}"}


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("ALLOWED_USER_IDS", f"{ANYA},{BORIS}")
    monkeypatch.setenv("WEB_APP_URL", "https://bot.example.com/")
    return Settings(_env_file=None)


@pytest.fixture
def tokens():
    return LoginTokens()


@pytest.fixture
async def client(settings, session_factory, tokens):
    app = create_web_app(settings, session_factory, tokens)
    jar = aiohttp.CookieJar(unsafe=True)  # тестовый сервер слушает на 127.0.0.1
    async with TestClient(TestServer(app), cookie_jar=jar) as client:
        yield client


@pytest.fixture
async def users(session_factory):
    async with session_factory() as session:
        session.add_all(
            [
                User(id=ANYA, first_name="Аня", timezone="Europe/Moscow"),
                User(id=BORIS, first_name="Борис", timezone="UTC"),
            ]
        )
        await session.commit()


# --- страница --------------------------------------------------------------


async def test_index_and_static_are_served_with_csp(client):
    page = await client.get("/")
    assert page.status == 200 and "text/html" in page.headers["Content-Type"]
    assert "script-src 'self' https://telegram.org" in page.headers["Content-Security-Policy"]
    assert 'src="/static/app.js"' in await page.text()
    for name in ("app.js", "app.css", "icon.svg"):
        assert (await client.get(f"/static/{name}")).status == 200


async def test_settings_strip_trailing_slash_and_detect_https(settings):
    assert settings.web_app_url == "https://bot.example.com"
    assert settings.web_enabled and settings.mini_app_enabled
    local = Settings(_env_file=None, web_app_url="http://localhost:8080")
    assert local.web_enabled and not local.mini_app_enabled


async def test_unknown_api_path_is_json_404(client):
    response = await client.get("/api/nope", headers=tma(ANYA))
    assert response.status == 404 and "error" in await response.json()


# --- вход: мини-приложение -------------------------------------------------


async def test_mini_app_user_is_registered_and_gets_profile(client, session_factory):
    response = await client.get("/api/me", headers=tma(ANYA))

    assert response.status == 200
    assert (await response.json())["first_name"] == "Аня"
    assert response.headers["Cache-Control"] == "no-store"
    async with session_factory() as session:
        assert await session.get(User, ANYA) is not None


async def test_no_credentials_is_401(client):
    assert (await client.get("/api/me")).status == 401


async def test_tampered_init_data_is_rejected(client):
    forged = init_data(ANYA).replace(f"%22id%22%3A+{ANYA}", f"%22id%22%3A+{BORIS}")
    assert forged != init_data(ANYA)
    assert (await client.get("/api/me", headers={"Authorization": f"tma {forged}"})).status == 401


async def test_init_data_signed_with_other_bot_token_is_rejected(client):
    assert (await client.get("/api/me", headers=tma(ANYA, token="43:OTHER"))).status == 401


async def test_stale_init_data_is_rejected(client):
    old = time.time() - 25 * 3600
    assert (await client.get("/api/me", headers=tma(ANYA, auth_date=old))).status == 401


async def test_user_outside_whitelist_is_denied_and_not_registered(client, session_factory):
    response = await client.get("/api/me", headers=tma(STRANGER))

    assert response.status == 403
    assert str(STRANGER) in (await response.json())["error"]
    async with session_factory() as session:
        assert await session.get(User, STRANGER) is None


# --- вход: браузер ---------------------------------------------------------


async def test_login_link_sets_session_cookie_and_works_once(client, tokens, users):
    token = tokens.issue(ANYA)

    first = await client.post("/api/login", json={"token": token})
    assert first.status == 200
    cookie = first.cookies[SESSION_COOKIE]
    assert cookie["httponly"] and cookie["secure"] and cookie["samesite"] == "Lax"
    # Cookie помечена Secure, тестовый клиент работает по http — передаём её явно.
    session = {SESSION_COOKIE: cookie.value}
    assert (await (await client.get("/api/me", cookies=session)).json())["id"] == ANYA

    assert (await client.post("/api/login", json={"token": token})).status == 401


async def test_login_rejects_unknown_and_expired_tokens(client, users):
    assert (await client.post("/api/login", json={"token": "nope"})).status == 401
    assert (await client.post("/api/login", json={})).status == 401
    expired = LoginTokens(ttl=0)
    assert expired.redeem(expired.issue(ANYA)) is None


async def test_login_requires_user_who_started_the_bot(client, tokens):
    assert (await client.post("/api/login", json={"token": tokens.issue(ANYA)})).status == 401


async def test_forged_or_expired_session_cookie_is_rejected(client, settings, users):
    signer = SessionSigner.from_bot_token(TOKEN)
    assert signer.loads(signer.dumps(ANYA)) == ANYA
    assert signer.loads(signer.dumps(ANYA, now=time.time() - SESSION_TTL - 1)) is None
    assert SessionSigner.from_bot_token("43:OTHER").loads(signer.dumps(ANYA)) is None

    good = signer.dumps(ANYA)
    forged = good.replace(str(ANYA), str(BORIS), 1)
    for value, status in ((forged, 401), ("garbage", 401), (good, 200)):
        response = await client.get("/api/me", cookies={SESSION_COOKIE: value})
        assert response.status == status, value


async def test_session_of_user_removed_from_whitelist_stops_working(
    settings, session_factory, tokens, users, monkeypatch
):
    cookie = SessionSigner.from_bot_token(TOKEN).dumps(BORIS)
    monkeypatch.setenv("ALLOWED_USER_IDS", str(ANYA))
    app = create_web_app(Settings(_env_file=None), session_factory, tokens)
    async with TestClient(TestServer(app)) as client:
        assert (await client.get("/api/me", cookies={SESSION_COOKIE: cookie})).status == 403


async def test_logout_clears_cookie(client, tokens, users):
    await client.post("/api/login", json={"token": tokens.issue(ANYA)})
    response = await client.post("/api/logout", json={})

    assert response.status == 200
    assert response.cookies[SESSION_COOKIE].value == ""
    assert response.cookies[SESSION_COOKIE]["max-age"] == "0"


async def test_cross_site_write_is_rejected(client, users):
    headers = {**tma(ANYA), "Origin": "https://evil.example"}
    response = await client.post("/api/notes", json={"text": "x"}, headers=headers)
    assert response.status == 403

    same = {**tma(ANYA), "Origin": f"http://{client.host}:{client.port}"}
    assert (await client.post("/api/notes", json={"text": "x"}, headers=same)).status == 201


# --- заметки ---------------------------------------------------------------


async def test_notes_crud(client, users):
    auth = tma(ANYA)
    created = await client.post(
        "/api/notes", json={"text": "  Купить <b>хлеб</b> #дом  "}, headers=auth
    )
    assert created.status == 201
    note = await created.json()
    assert note["text"] == "Купить <b>хлеб</b> #дом" and note["created_at"].endswith("Z")

    updated = await client.put(
        f"/api/notes/{note['id']}", json={"text": "Купить батон"}, headers=auth
    )
    assert (await updated.json())["updated_at"] is not None

    listing = await (await client.get("/api/notes", headers=auth)).json()
    assert [n["text"] for n in listing["items"]] == ["Купить батон"] and listing["total"] == 1

    assert (await client.delete(f"/api/notes/{note['id']}", headers=auth)).status == 200
    assert (await client.delete(f"/api/notes/{note['id']}", headers=auth)).status == 404


async def test_notes_pagination_and_search(client, session_factory, users):
    async with session_factory() as session:
        for i in range(25):
            await notes_repo.add_note(session, ANYA, f"заметка {i}")
        await notes_repo.add_note(session, ANYA, "Молоко #дом")
    auth = tma(ANYA)

    first = await (await client.get("/api/notes", headers=auth)).json()
    second = await (await client.get("/api/notes?offset=20", headers=auth)).json()
    found = await (await client.get("/api/notes", params={"q": "МОЛОКО #дом"}, headers=auth)).json()

    assert (len(first["items"]), len(second["items"]), first["total"]) == (20, 6, 26)
    assert first["items"][0]["text"] == "Молоко #дом"
    assert [n["text"] for n in found["items"]] == ["Молоко #дом"]


@pytest.mark.parametrize("payload", [{"text": "   "}, {"text": "x" * 4001}, {"text": 5}, {}, []])
async def test_note_validation(client, users, payload):
    response = await client.post("/api/notes", json=payload, headers=tma(ANYA))
    assert response.status == 400 and "error" in await response.json()


async def test_non_json_body_is_rejected(client, users):
    response = await client.post("/api/notes", data="text=x", headers=tma(ANYA))
    assert response.status == 415
    broken = await client.post("/api/notes", data="{", headers={**tma(ANYA), **JSON})
    assert broken.status == 400


async def test_notes_are_isolated_between_users(client, session_factory, users):
    async with session_factory() as session:
        secret = await notes_repo.add_note(session, BORIS, "секрет Бориса")
    auth = tma(ANYA)

    assert (await (await client.get("/api/notes", headers=auth)).json())["items"] == []
    found = await client.get("/api/notes", params={"q": "секрет"}, headers=auth)
    assert (await found.json())["items"] == []
    edit = await client.put(f"/api/notes/{secret.id}", json={"text": "взлом"}, headers=auth)
    assert edit.status == 404
    assert (await client.delete(f"/api/notes/{secret.id}", headers=auth)).status == 404
    async with session_factory() as session:
        assert (await notes_repo.get_note(session, BORIS, secret.id)).text == "секрет Бориса"


# --- напоминания -----------------------------------------------------------


async def test_reminder_is_created_from_russian_text(client, session_factory, users):
    auth = tma(ANYA)
    response = await client.post(
        "/api/reminders", json={"text": "каждый день 8:00 витамины"}, headers=auth
    )

    assert response.status == 201
    body = await response.json()
    assert (body["text"], body["repeat"]) == ("витамины", "каждый день")
    assert body["when"].endswith("08:00")
    # 8:00 по Москве — это 5:00 UTC
    assert body["remind_at"].endswith("T05:00:00Z")

    listing = await (await client.get("/api/reminders", headers=auth)).json()
    assert [r["id"] for r in listing["items"]] == [body["id"]]


async def test_reminder_without_time_is_400(client, session_factory, users):
    response = await client.post("/api/reminders", json={"text": "просто текст"}, headers=tma(ANYA))

    assert response.status == 400
    assert "Не понял" in (await response.json())["error"]
    async with session_factory() as session:
        assert await reminders_repo.list_active(session, ANYA, limit=10) == []


async def test_reminders_delete_and_isolation(client, session_factory, users):
    soon = datetime.now(UTC) + timedelta(hours=1)
    async with session_factory() as session:
        mine = await reminders_repo.add_reminder(session, ANYA, "моё", soon)
        foreign = await reminders_repo.add_reminder(session, BORIS, "чужое", soon)
    auth = tma(ANYA)

    listing = await (await client.get("/api/reminders", headers=auth)).json()
    assert [r["text"] for r in listing["items"]] == ["моё"]
    assert (await client.delete(f"/api/reminders/{foreign.id}", headers=auth)).status == 404
    assert (await client.delete(f"/api/reminders/{mine.id}", headers=auth)).status == 200
    async with session_factory() as session:
        assert [r.text for r in await reminders_repo.list_active(session, BORIS, limit=10)] == [
            "чужое"
        ]
