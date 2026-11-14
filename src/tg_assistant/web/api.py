from datetime import UTC, datetime
from json import JSONDecodeError
from zoneinfo import ZoneInfo

from aiohttp import web

from ..db import Note, Reminder, User
from ..db import notes as notes_repo
from ..db import reminders as reminders_repo
from ..reminders.format import format_repeat, format_when
from ..reminders.timeparse import parse_reminder
from .auth import SESSION_COOKIE, SESSION_TTL
from .keys import DB, LOGIN_TOKENS, SETTINGS, SIGNER, USER

MAX_TEXT = 4000
PAGE_SIZE = 20
SEARCH_LIMIT = 50
REMINDERS_LIMIT = 100


def _error(status: int, message: str) -> web.Response:
    return web.json_response({"error": message}, status=status)


async def _body(request: web.Request) -> dict:
    if request.content_type != "application/json":
        raise web.HTTPUnsupportedMediaType(reason="Ожидается JSON")
    try:
        data = await request.json()
    except (JSONDecodeError, UnicodeDecodeError) as exc:
        raise web.HTTPBadRequest(reason="Некорректный JSON") from exc
    if not isinstance(data, dict):
        raise web.HTTPBadRequest(reason="Некорректный JSON")
    return data


def _text(data: dict) -> str:
    text = data.get("text")
    if not isinstance(text, str) or not text.strip():
        raise web.HTTPBadRequest(reason="Текст не может быть пустым")
    text = text.strip()
    if len(text) > MAX_TEXT:
        raise web.HTTPBadRequest(reason=f"Слишком длинный текст (максимум {MAX_TEXT} символов)")
    return text


def _id(request: web.Request) -> int:
    return int(request.match_info["id"])


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:  # SQLite отдаёт время без пояса; в БД оно в UTC
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _note(note: Note) -> dict:
    return {
        "id": note.id,
        "text": note.text,
        "created_at": _iso(note.created_at),
        "updated_at": _iso(note.updated_at),
    }


def _reminder(reminder: Reminder, user: User, now: datetime) -> dict:
    when = reminder.remind_at.astimezone(ZoneInfo(user.timezone))
    return {
        "id": reminder.id,
        "text": reminder.text,
        "remind_at": _iso(reminder.remind_at),
        "when": format_when(when, now),
        "repeat": format_repeat(reminder.repeat, when) or None,
    }


def _me(user: User) -> dict:
    now = datetime.now(ZoneInfo(user.timezone))
    return {
        "id": user.id,
        "first_name": user.first_name,
        "timezone": user.timezone,
        "local_time": f"{now:%H:%M}",
    }


# --- вход ------------------------------------------------------------------


async def login(request: web.Request) -> web.Response:
    token = (await _body(request)).get("token")
    user_id = request.app[LOGIN_TOKENS].redeem(token) if isinstance(token, str) else None
    settings = request.app[SETTINGS]
    if user_id is None or user_id not in settings.allowed_user_ids:
        return _error(401, "Ссылка для входа недействительна или уже использована")
    user = await request[DB].get(User, user_id)
    if user is None:
        return _error(401, "Сначала напишите боту /start")
    response = web.json_response(_me(user))
    response.set_cookie(
        SESSION_COOKIE,
        request.app[SIGNER].dumps(user_id),
        max_age=SESSION_TTL,
        httponly=True,
        samesite="Lax",
        secure=settings.web_app_url.startswith("https://"),
        path="/",
    )
    return response


async def logout(request: web.Request) -> web.Response:
    response = web.json_response({"ok": True})
    response.del_cookie(SESSION_COOKIE, path="/")
    return response


async def me(request: web.Request) -> web.Response:
    return web.json_response(_me(request[USER]))


# --- заметки ---------------------------------------------------------------


async def list_notes(request: web.Request) -> web.Response:
    session, user = request[DB], request[USER]
    query = request.query.get("q", "").strip()
    if query:
        found = await notes_repo.search_notes(session, user.id, query, limit=SEARCH_LIMIT)
        return web.json_response({"items": [_note(n) for n in found], "total": len(found)})
    try:
        offset = max(int(request.query.get("offset", 0)), 0)
    except ValueError:
        offset = 0
    items, total = await notes_repo.list_notes(session, user.id, offset=offset, limit=PAGE_SIZE)
    return web.json_response({"items": [_note(n) for n in items], "total": total})


async def create_note(request: web.Request) -> web.Response:
    text = _text(await _body(request))
    note = await notes_repo.add_note(request[DB], request[USER].id, text)
    return web.json_response(_note(note), status=201)


async def update_note(request: web.Request) -> web.Response:
    session, user = request[DB], request[USER]
    text = _text(await _body(request))
    if not await notes_repo.update_note(session, user.id, _id(request), text):
        return _error(404, "Заметка не найдена")
    return web.json_response(_note(await notes_repo.get_note(session, user.id, _id(request))))


async def delete_note(request: web.Request) -> web.Response:
    if not await notes_repo.delete_note(request[DB], request[USER].id, _id(request)):
        return _error(404, "Заметка не найдена")
    return web.json_response({"ok": True})


# --- напоминания -----------------------------------------------------------


async def list_reminders(request: web.Request) -> web.Response:
    session, user = request[DB], request[USER]
    now = datetime.now(ZoneInfo(user.timezone))
    items = await reminders_repo.list_active(session, user.id, limit=REMINDERS_LIMIT)
    return web.json_response({"items": [_reminder(r, user, now) for r in items]})


async def create_reminder(request: web.Request) -> web.Response:
    session, user = request[DB], request[USER]
    text = _text(await _body(request))
    now = datetime.now(ZoneInfo(user.timezone))
    parsed = parse_reminder(text, now)
    if parsed is None:
        return _error(
            400, "Не понял, когда напомнить. Начните со времени: «завтра в 9 позвонить маме»"
        )
    reminder = await reminders_repo.add_reminder(
        session, user.id, parsed.text, parsed.when, parsed.repeat
    )
    return web.json_response(_reminder(reminder, user, now), status=201)


async def delete_reminder(request: web.Request) -> web.Response:
    deleted = await reminders_repo.delete_reminder(request[DB], request[USER].id, _id(request))
    if not deleted:
        return _error(404, "Напоминание не найдено")
    return web.json_response({"ok": True})


def setup_routes(app: web.Application) -> None:
    r = app.router
    r.add_post("/api/login", login)
    r.add_post("/api/logout", logout)
    r.add_get("/api/me", me)
    r.add_get("/api/notes", list_notes)
    r.add_post("/api/notes", create_note)
    r.add_put(r"/api/notes/{id:\d+}", update_note)
    r.add_delete(r"/api/notes/{id:\d+}", delete_note)
    r.add_get("/api/reminders", list_reminders)
    r.add_post("/api/reminders", create_reminder)
    r.add_delete(r"/api/reminders/{id:\d+}", delete_reminder)
