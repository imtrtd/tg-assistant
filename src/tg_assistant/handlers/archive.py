"""Команды архива чатов: /archive, /chats, /deleted и выгрузка чата файлом."""

import html
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import ArchivedMessage, User
from ..db import archive as repo
from ..db.archive import MEDIA_LABELS
from ..texts import (
    ARCHIVE_CHAT_EMPTY,
    ARCHIVE_HOW_TO,
    ARCHIVE_SAVED,
    archive_head,
    archive_stats,
    chats_empty,
    chats_header,
    deleted_empty,
    deleted_header,
)

CHATS_LIMIT = 20
DELETED_LIMIT = 15


class ArchCb(CallbackData, prefix="arch"):
    action: str  # "edits" | "deletes" | "chats" | "export"
    chat_id: int = 0


def _local(value: datetime, tz: str) -> datetime:
    return value.astimezone(ZoneInfo(tz))


def _status_markup(user: User) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(
        text=f"{'✅' if user.notify_edits else '⬜'} Сообщать об изменениях",
        callback_data=ArchCb(action="edits"),
    )
    kb.button(
        text=f"{'✅' if user.notify_deletes else '⬜'} Сообщать об удалениях",
        callback_data=ArchCb(action="deletes"),
    )
    kb.button(text="📁 Чаты в архиве", callback_data=ArchCb(action="chats"))
    kb.adjust(1)
    return kb.as_markup()


async def _status_text(session: AsyncSession, user: User) -> str:
    connected = await repo.has_active_connection(session, user.id)
    chats, messages, edited, deleted = await repo.counts(session, user.id)
    text = f"{archive_head(connected)}\n\n{archive_stats(chats, messages, edited, deleted)}"
    if not connected:
        text += "\n\n" + ARCHIVE_HOW_TO
    return text


async def cmd_archive(message: Message, session: AsyncSession, user: User):
    await message.answer(
        await _status_text(session, user), reply_markup=_status_markup(user), parse_mode="HTML"
    )


async def on_toggle(query: CallbackQuery, callback_data: ArchCb, session: AsyncSession, user: User):
    if callback_data.action == "edits":
        user.notify_edits = not user.notify_edits
    else:
        user.notify_deletes = not user.notify_deletes
    await session.commit()
    if isinstance(query.message, Message):
        try:
            await query.message.edit_text(
                await _status_text(session, user),
                reply_markup=_status_markup(user),
                parse_mode="HTML",
            )
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc):
                raise
    await query.answer(ARCHIVE_SAVED)


async def _chats_view(session: AsyncSession, user: User) -> tuple[str, InlineKeyboardMarkup | None]:
    chats = await repo.list_chats(session, user.id, limit=CHATS_LIMIT)
    if not chats:
        return chats_empty(), None
    lines = [chats_header(), ""]
    kb = InlineKeyboardBuilder()
    for chat in chats:
        last = _local(chat.last_at, user.timezone)
        deleted = f", удалено {chat.deleted}" if chat.deleted else ""
        lines.append(
            f"• <b>{html.escape(chat.title)}</b> — {chat.messages} сообщ.{deleted}, "
            f"последнее {last:%d.%m %H:%M}"
        )
        kb.button(
            text=f"⬇ {chat.title[:40]}", callback_data=ArchCb(action="export", chat_id=chat.chat_id)
        )
    kb.adjust(1)
    return "\n".join(lines), kb.as_markup()


async def cmd_chats(message: Message, session: AsyncSession, user: User):
    text, markup = await _chats_view(session, user)
    await message.answer(text, reply_markup=markup, parse_mode="HTML")


async def on_chats(query: CallbackQuery, session: AsyncSession, user: User):
    text, markup = await _chats_view(session, user)
    if isinstance(query.message, Message):
        await query.message.answer(text, reply_markup=markup, parse_mode="HTML")
    await query.answer()


def render_chat(rows: list[ArchivedMessage], edits: dict[int, list], tz: str) -> str:
    lines = []
    for row in rows:
        stamp = _local(row.sent_at, tz).strftime("%d.%m.%Y %H:%M")
        body = row.text or ""
        if row.media_type:
            label = f"[{MEDIA_LABELS.get(row.media_type, row.media_type)}]"
            body = f"{label} {body}".strip()
        marks = []
        if row.edited_at:
            marks.append("изменено")
        if row.deleted_at:
            marks.append(f"удалено {_local(row.deleted_at, tz):%d.%m.%Y %H:%M}")
        suffix = f"  ({', '.join(marks)})" if marks else ""
        lines.append(f"[{stamp}] {row.sender_name}: {body}{suffix}")
        for edit in edits.get(row.id, []):
            lines.append(
                f"    было до {_local(edit.replaced_at, tz):%d.%m %H:%M}: {edit.text or ''}"
            )
    return "\n".join(lines) + "\n"


async def on_export(query: CallbackQuery, callback_data: ArchCb, session: AsyncSession, user: User):
    rows = await repo.chat_messages(session, user.id, callback_data.chat_id)
    if not rows:
        await query.answer(ARCHIVE_CHAT_EMPTY, show_alert=True)
        return
    edits = {row.id: await repo.edits_of(session, row.id) for row in rows if row.edited_at}
    content = render_chat(rows, edits, user.timezone).encode("utf-8")
    title = rows[-1].chat_title
    safe = "".join(ch if ch.isalnum() else "_" for ch in title)[:40] or "chat"
    if isinstance(query.message, Message):
        await query.message.answer_document(
            BufferedInputFile(content, filename=f"chat-{safe}.txt"),
            caption=f"{title}: {len(rows)} сообщ.",
        )
    await query.answer()


async def cmd_deleted(message: Message, session: AsyncSession, user: User):
    rows = await repo.recent_deleted(session, user.id, limit=DELETED_LIMIT)
    if not rows:
        await message.answer(deleted_empty(), parse_mode="HTML")
        return
    lines = [deleted_header(len(rows)), ""]
    for row in rows:
        deleted = _local(row.deleted_at, user.timezone)
        body = row.text or ""
        if row.media_type:
            body = f"[{MEDIA_LABELS.get(row.media_type, row.media_type)}] {body}".strip()
        if len(body) > 300:
            body = body[:300] + "…"
        mine = " (вы)" if row.outgoing else ""
        lines.append(
            f"<b>{html.escape(row.sender_name)}</b>{mine} · {html.escape(row.chat_title)}, "
            f"удалено {deleted:%d.%m %H:%M}\n{html.escape(body) or '<i>(пусто)</i>'}\n"
        )
    await message.answer("\n".join(lines).strip(), parse_mode="HTML")


def create_router() -> Router:
    router = Router(name="archive")
    router.message.register(cmd_archive, Command("archive"))
    router.message.register(cmd_chats, Command("chats"))
    router.message.register(cmd_deleted, Command("deleted"))
    router.callback_query.register(on_toggle, ArchCb.filter(F.action.in_({"edits", "deletes"})))
    router.callback_query.register(on_chats, ArchCb.filter(F.action == "chats"))
    router.callback_query.register(on_export, ArchCb.filter(F.action == "export"))
    return router
