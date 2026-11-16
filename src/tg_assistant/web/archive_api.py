"""API архива чатов для мини-приложения.

Все выборки — только по владельцу текущей сессии (`USER`). Медиа хранится как file_id
Telegram: фото и стикеры отдаются через бота (getFile), остальное бот может переслать
владельцу в личку.
"""

import logging
from datetime import UTC, datetime

from aiogram.exceptions import TelegramAPIError
from aiohttp import web

from ..archive_delivery import resend_archived
from ..db import ArchivedMessage, MessageEdit
from ..db import archive as repo
from ..db.archive import MEDIA_LABELS
from ..topics import ARCHIVE, DELETED, topic_kind
from .api import _body
from .keys import BOT, DB, USER

logger = logging.getLogger(__name__)

CHATS_LIMIT = 200
PAGE_LIMIT = 50
DELETED_LIMIT = 100
# Что можно показать прямо на странице (картинкой). Анимированные стикеры (.tgs/.webm) — нет.
INLINE_MEDIA = {"photo": "image/jpeg", "sticker": "image/webp"}
MAX_INLINE_BYTES = 10 * 1024 * 1024


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _error(status: int, message: str) -> web.Response:
    return web.json_response({"error": message}, status=status)


def _message(row: ArchivedMessage, edits: list[MessageEdit] | None = None) -> dict:
    return {
        "id": row.id,
        "chat_id": row.chat_id,
        "chat_title": row.chat_title,
        "sender_name": row.sender_name,
        "outgoing": row.outgoing,
        "text": row.text,
        "media_type": row.media_type,
        "media_label": MEDIA_LABELS.get(row.media_type) if row.media_type else None,
        "media_inline": row.media_type in INLINE_MEDIA and bool(row.file_id),
        "sent_at": _iso(row.sent_at),
        "edited_at": _iso(row.edited_at),
        "deleted_at": _iso(row.deleted_at),
        "edits": [{"text": e.text, "replaced_at": _iso(e.replaced_at)} for e in edits or []],
    }


async def _int_param(request: web.Request, name: str) -> int | None:
    value = request.query.get(name)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise web.HTTPBadRequest(reason=f"Некорректный параметр {name}") from exc


async def overview(request: web.Request) -> web.Response:
    session, user = request[DB], request[USER]
    chats, messages, edited, deleted = await repo.counts(session, user.id)
    return web.json_response(
        {
            "connected": await repo.has_active_connection(session, user.id),
            "chats": chats,
            "messages": messages,
            "edited": edited,
            "deleted": deleted,
            "notify_edits": user.notify_edits,
            "notify_deletes": user.notify_deletes,
        }
    )


async def update_settings(request: web.Request) -> web.Response:
    data = await _body(request)
    user = request[USER]
    for field in ("notify_edits", "notify_deletes"):
        if field in data:
            if not isinstance(data[field], bool):
                return _error(400, f"{field}: ожидается true или false")
            setattr(user, field, data[field])
    await request[DB].commit()
    return await overview(request)


async def chats(request: web.Request) -> web.Response:
    items = await repo.list_chats(request[DB], request[USER].id, limit=CHATS_LIMIT)
    return web.json_response(
        {
            "items": [
                {
                    "chat_id": c.chat_id,
                    "title": c.title,
                    "messages": c.messages,
                    "deleted": c.deleted,
                    "last_at": _iso(c.last_at),
                }
                for c in items
            ]
        }
    )


async def chat_messages(request: web.Request) -> web.Response:
    session, user = request[DB], request[USER]
    chat_id = int(request.match_info["chat_id"])
    before = await _int_param(request, "before")
    rows, has_more = await repo.chat_page(
        session, user.id, chat_id, before_id=before, limit=PAGE_LIMIT
    )
    if not rows and before is None:
        return _error(404, "Чат не найден в архиве")
    edits = await repo.edits_for(session, [r.id for r in rows if r.edited_at])
    return web.json_response(
        {
            "title": rows[-1].chat_title if rows else "",
            "items": [_message(r, edits.get(r.id)) for r in rows],
            "has_more": has_more,
        }
    )


async def deleted(request: web.Request) -> web.Response:
    rows = await repo.recent_deleted(request[DB], request[USER].id, limit=DELETED_LIMIT)
    return web.json_response({"items": [_message(r) for r in rows]})


async def _owned(request: web.Request) -> ArchivedMessage:
    row = await repo.get_owned(request[DB], request[USER].id, int(request.match_info["id"]))
    if row is None:
        raise web.HTTPNotFound(reason="Сообщение не найдено")
    return row


async def media(request: web.Request) -> web.StreamResponse:
    row = await _owned(request)
    content_type = INLINE_MEDIA.get(row.media_type or "")
    bot = request.app.get(BOT)
    if content_type is None or not row.file_id or bot is None:
        return _error(404, "Для этого сообщения нет картинки")
    try:
        file = await bot.get_file(row.file_id)
        if file.file_size and file.file_size > MAX_INLINE_BYTES:
            return _error(413, "Файл слишком большой — пришлю его в Telegram")
        data = await bot.download_file(file.file_path)
    except TelegramAPIError:
        logger.warning("Could not fetch media for archived message %s", row.id)
        return _error(410, "Telegram больше не отдаёт этот файл")
    return web.Response(
        body=data.read(),
        content_type=content_type,
        headers={"Cache-Control": "private, max-age=86400"},
    )


async def send_to_telegram(request: web.Request) -> web.Response:
    """Переслать сообщение из архива владельцу в личку с ботом."""
    row = await _owned(request)
    bot = request.app.get(BOT)
    if bot is None:
        return _error(503, "Бот недоступен")
    try:
        with topic_kind(DELETED if row.deleted_at else ARCHIVE):
            await resend_archived(bot, request[USER].id, row)
    except TelegramAPIError:
        logger.exception("Failed to resend archived message %s", row.id)
        return _error(502, "Telegram не принял сообщение, попробуйте позже")
    return web.json_response({"ok": True})


def setup_routes(app: web.Application) -> None:
    r = app.router
    r.add_get("/api/archive", overview)
    r.add_put("/api/archive/settings", update_settings)
    r.add_get("/api/archive/chats", chats)
    r.add_get(r"/api/archive/chats/{chat_id:-?\d+}", chat_messages)
    r.add_get("/api/archive/deleted", deleted)
    r.add_get(r"/api/archive/messages/{id:\d+}/media", media)
    r.add_post(r"/api/archive/messages/{id:\d+}/send", send_to_telegram)
