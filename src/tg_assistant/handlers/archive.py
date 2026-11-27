"""Команды архива чатов: /archive, /chats, /deleted и выгрузка чата файлом."""

import html
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
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


def _status_markup(user: User, settings: Settings) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if settings.mini_app_enabled:
        kb.button(
            text="📱 Открыть в приложении",
            web_app=WebAppInfo(url=settings.app_url(open="archive")),
        )
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


def _target(user: User, settings: Settings, arg: str) -> int | None:
    """Чей архив показать: свой, либо для админа — указанный id аккаунта."""
    if not arg or user.id not in settings.admin_ids:
        return user.id
    return int(arg) if arg.lstrip("-").isdigit() else None


async def _accounts_text(session: AsyncSession) -> str:
    owners = await repo.archive_owners(session)
    if not owners:
        return "В архиве пока нет ни одного аккаунта."
    lines = ["<b>Аккаунты в архиве</b>", ""]
    for owner_id, count in owners:
        person = await session.get(User, owner_id)
        name = html.escape(person.first_name if person else str(owner_id))
        lines.append(
            f"• <b>{name}</b> ({owner_id}), {count} сообщ.: "
            f"/archive {owner_id} или /deleted {owner_id}"
        )
    return "\n".join(lines)


async def _status_text(session: AsyncSession, owner_id: int) -> str:
    connected = await repo.has_active_connection(session, owner_id)
    chats, messages, edited, deleted = await repo.counts(session, owner_id)
    text = f"{archive_head(connected)}\n\n{archive_stats(chats, messages, edited, deleted)}"
    if not connected:
        text += "\n\n" + ARCHIVE_HOW_TO
    return text


async def cmd_archive(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    user: User,
    settings: Settings,
):
    arg = (command.args or "").strip()
    if user.id in settings.admin_ids and not arg:
        await message.answer(await _accounts_text(session), parse_mode="HTML")
        return
    owner_id = _target(user, settings, arg)
    if owner_id is None:
        await message.answer("Укажите числовой id аккаунта: /archive 123", parse_mode="HTML")
        return
    # Чужой архив админ смотрит только как сводку: переключатели относятся к своему.
    markup = _status_markup(user, settings) if owner_id == user.id else None
    await message.answer(
        await _status_text(session, owner_id), reply_markup=markup, parse_mode="HTML"
    )


async def on_toggle(
    query: CallbackQuery,
    callback_data: ArchCb,
    session: AsyncSession,
    user: User,
    settings: Settings,
):
    if callback_data.action == "edits":
        user.notify_edits = not user.notify_edits
    else:
        user.notify_deletes = not user.notify_deletes
    await session.commit()
    if isinstance(query.message, Message):
        try:
            await query.message.edit_text(
                await _status_text(session, user.id),
                reply_markup=_status_markup(user, settings),
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


async def cmd_deleted(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    user: User,
    settings: Settings,
):
    owner_id = _target(user, settings, (command.args or "").strip())
    if owner_id is None:
        await message.answer("Укажите числовой id аккаунта: /deleted 123", parse_mode="HTML")
        return
    rows = await repo.recent_deleted(session, owner_id, limit=DELETED_LIMIT)
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
    router.message.register(cmd_deleted, Command("deleted"))
    router.callback_query.register(on_toggle, ArchCb.filter(F.action.in_({"edits", "deletes"})))
    router.callback_query.register(on_chats, ArchCb.filter(F.action == "chats"))
    router.callback_query.register(on_export, ArchCb.filter(F.action == "export"))
    return router
