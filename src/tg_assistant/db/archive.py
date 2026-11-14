"""Архив личных чатов (Telegram Business): запись, правки, удаления, выборки."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from aiogram.types import Message
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ArchivedMessage, BusinessConnection, MessageEdit

# Тип вложения -> атрибут Message. Порядок важен: у анимации есть и document.
MEDIA_TYPES = ("photo", "video", "animation", "video_note", "voice", "audio", "sticker", "document")
MEDIA_LABELS = {
    "photo": "фото",
    "video": "видео",
    "animation": "GIF",
    "video_note": "видеосообщение",
    "voice": "голосовое",
    "audio": "аудио",
    "sticker": "стикер",
    "document": "файл",
}


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def media_of(message: Message) -> tuple[str | None, str | None]:
    for kind in MEDIA_TYPES:
        value = getattr(message, kind, None)
        if value:
            item = value[-1] if isinstance(value, list) else value  # photo — список размеров
            return kind, item.file_id
    return None, None


def text_of(message: Message) -> str | None:
    return message.text or message.caption


def chat_title(message: Message) -> str:
    chat = message.chat
    return chat.full_name or chat.title or chat.username or str(chat.id)


def sender_name(message: Message) -> str:
    user = message.from_user
    if user is None:
        return chat_title(message)
    return user.full_name or (f"@{user.username}" if user.username else str(user.id))


# --- подключения -----------------------------------------------------------


async def save_connection(
    session: AsyncSession, connection_id: str, owner_id: int, is_enabled: bool
) -> BusinessConnection:
    row = await session.get(BusinessConnection, connection_id)
    if row is None:
        row = BusinessConnection(id=connection_id, owner_id=owner_id)
        session.add(row)
    row.owner_id = owner_id
    row.is_enabled = is_enabled
    row.updated_at = datetime.now(UTC)
    await session.commit()
    return row


async def get_connection(session: AsyncSession, connection_id: str) -> BusinessConnection | None:
    return await session.get(BusinessConnection, connection_id)


async def has_active_connection(session: AsyncSession, owner_id: int) -> bool:
    found = await session.scalar(
        select(BusinessConnection.id)
        .where(BusinessConnection.owner_id == owner_id, BusinessConnection.is_enabled.is_(True))
        .limit(1)
    )
    return found is not None


# --- сообщения -------------------------------------------------------------


async def find(
    session: AsyncSession, owner_id: int, chat_id: int, message_id: int
) -> ArchivedMessage | None:
    return await session.scalar(
        select(ArchivedMessage).where(
            ArchivedMessage.owner_id == owner_id,
            ArchivedMessage.chat_id == chat_id,
            ArchivedMessage.message_id == message_id,
        )
    )


async def store(session: AsyncSession, owner_id: int, message: Message) -> ArchivedMessage:
    """Сохранить новое сообщение (повторная доставка того же сообщения не дублирует запись)."""
    existing = await find(session, owner_id, message.chat.id, message.message_id)
    if existing is not None:
        return existing
    media_type, file_id = media_of(message)
    sender = message.from_user
    row = ArchivedMessage(
        owner_id=owner_id,
        chat_id=message.chat.id,
        chat_title=chat_title(message)[:256],
        message_id=message.message_id,
        sender_id=sender.id if sender else None,
        sender_name=sender_name(message)[:256],
        outgoing=bool(sender and sender.id == owner_id),
        text=text_of(message),
        media_type=media_type,
        file_id=file_id,
        sent_at=_aware(message.date),
    )
    session.add(row)
    await session.commit()
    return row


def _edit_time(message: Message) -> datetime:
    edit_date = message.edit_date
    if isinstance(edit_date, datetime):
        return _aware(edit_date)
    if isinstance(edit_date, int):
        return datetime.fromtimestamp(edit_date, UTC)
    return datetime.now(UTC)


@dataclass
class EditResult:
    message: ArchivedMessage
    old_text: str | None
    changed: bool


async def apply_edit(session: AsyncSession, owner_id: int, message: Message) -> EditResult:
    """Записать правку. Если исходного сообщения нет в архиве — сохранить текущую версию."""
    row = await find(session, owner_id, message.chat.id, message.message_id)
    new_text = text_of(message)
    if row is None:
        row = await store(session, owner_id, message)
        row.edited_at = _edit_time(message)
        await session.commit()
        return EditResult(row, None, changed=False)

    old_text = row.text
    media_type, file_id = media_of(message)
    changed = new_text != old_text or (file_id is not None and file_id != row.file_id)
    if changed:
        now = _edit_time(message)
        session.add(MessageEdit(message_id=row.id, text=old_text, replaced_at=now))
        row.text = new_text
        if file_id is not None:
            row.media_type, row.file_id = media_type, file_id
        row.edited_at = now
        await session.commit()
    return EditResult(row, old_text, changed)


async def mark_deleted(
    session: AsyncSession, owner_id: int, chat_id: int, message_ids: Sequence[int]
) -> tuple[list[ArchivedMessage], int]:
    """Пометить сообщения удалёнными. Возвращает найденные и число тех, которых в архиве нет."""
    rows = list(
        await session.scalars(
            select(ArchivedMessage)
            .where(
                ArchivedMessage.owner_id == owner_id,
                ArchivedMessage.chat_id == chat_id,
                ArchivedMessage.message_id.in_(list(message_ids)),
            )
            .order_by(ArchivedMessage.sent_at, ArchivedMessage.message_id)
        )
    )
    now = datetime.now(UTC)
    for row in rows:
        if row.deleted_at is None:
            row.deleted_at = now
    await session.commit()
    return rows, len(set(message_ids)) - len(rows)


async def edits_of(session: AsyncSession, archived_id: int) -> list[MessageEdit]:
    result = await session.scalars(
        select(MessageEdit).where(MessageEdit.message_id == archived_id).order_by(MessageEdit.id)
    )
    return list(result)


# --- выборки для команд и экспорта ----------------------------------------


@dataclass
class ChatSummary:
    chat_id: int
    title: str
    messages: int
    deleted: int
    last_at: datetime


async def list_chats(session: AsyncSession, owner_id: int, *, limit: int) -> list[ChatSummary]:
    last = func.max(ArchivedMessage.sent_at)
    result = await session.execute(
        select(
            ArchivedMessage.chat_id,
            func.max(ArchivedMessage.chat_title),
            func.count(),
            func.count(ArchivedMessage.deleted_at),
            last,
        )
        .where(ArchivedMessage.owner_id == owner_id)
        .group_by(ArchivedMessage.chat_id)
        .order_by(last.desc())
        .limit(limit)
    )
    return [
        ChatSummary(chat_id, title, total, deleted, _aware(last_at))
        for chat_id, title, total, deleted, last_at in result.all()
    ]


async def chat_messages(
    session: AsyncSession, owner_id: int, chat_id: int
) -> list[ArchivedMessage]:
    result = await session.scalars(
        select(ArchivedMessage)
        .where(ArchivedMessage.owner_id == owner_id, ArchivedMessage.chat_id == chat_id)
        .order_by(ArchivedMessage.sent_at, ArchivedMessage.message_id)
    )
    return list(result)


async def recent_deleted(
    session: AsyncSession, owner_id: int, *, limit: int
) -> list[ArchivedMessage]:
    result = await session.scalars(
        select(ArchivedMessage)
        .where(ArchivedMessage.owner_id == owner_id, ArchivedMessage.deleted_at.is_not(None))
        .order_by(ArchivedMessage.deleted_at.desc(), ArchivedMessage.id.desc())
        .limit(limit)
    )
    return list(result)


async def counts(session: AsyncSession, owner_id: int) -> tuple[int, int, int, int]:
    """(чатов, сообщений, изменённых, удалённых)."""
    row = (
        await session.execute(
            select(
                func.count(func.distinct(ArchivedMessage.chat_id)),
                func.count(),
                func.count(ArchivedMessage.edited_at),
                func.count(ArchivedMessage.deleted_at),
            ).where(ArchivedMessage.owner_id == owner_id)
        )
    ).one()
    return tuple(int(x or 0) for x in row)


async def purge_older_than(session: AsyncSession, days: int, now: datetime | None = None) -> int:
    cutoff = (now or datetime.now(UTC)) - timedelta(days=days)
    old_ids = select(ArchivedMessage.id).where(ArchivedMessage.sent_at < cutoff)
    await session.execute(delete(MessageEdit).where(MessageEdit.message_id.in_(old_ids)))
    result = await session.execute(delete(ArchivedMessage).where(ArchivedMessage.sent_at < cutoff))
    await session.commit()
    return result.rowcount or 0
