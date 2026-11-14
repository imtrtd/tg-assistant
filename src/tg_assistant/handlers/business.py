"""Telegram Business: архив личных чатов владельца, правки и удаления.

Пользователь подключает бота в Telegram: Настройки → Telegram Business → Чат-боты.
После этого Telegram присылает боту сообщения из его личных чатов. Бот только
сохраняет их и сообщает владельцу об изменениях — сам в эти чаты ничего не пишет.
"""

import html
import logging
from zoneinfo import ZoneInfo

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BusinessConnection as TgBusinessConnection
from aiogram.types import BusinessMessagesDeleted, Message
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..db import ArchivedMessage, User
from ..db import archive as repo
from ..db.archive import MEDIA_LABELS
from ..db.users import get_or_create_user

logger = logging.getLogger(__name__)

TEXT_LIMIT = 1500  # на одну версию текста: «было» + «стало» должны влезть в 4096
SHOW_DELETED = 10  # сколько удалённых показывать в одном уведомлении
MEDIA_SENDERS = {
    "photo": ("send_photo", "photo", True),
    "video": ("send_video", "video", True),
    "animation": ("send_animation", "animation", True),
    "voice": ("send_voice", "voice", True),
    "audio": ("send_audio", "audio", True),
    "document": ("send_document", "document", True),
    "video_note": ("send_video_note", "video_note", False),
    "sticker": ("send_sticker", "sticker", False),
}


def _short(text: str | None, limit: int = TEXT_LIMIT) -> str:
    if not text:
        return "<i>(без текста)</i>"
    if len(text) > limit:
        text = text[:limit] + "…"
    return html.escape(text)


def _describe(row: ArchivedMessage) -> str:
    parts = []
    if row.media_type:
        parts.append(f"[{MEDIA_LABELS.get(row.media_type, row.media_type)}]")
    if row.text:
        parts.append(_short(row.text, 600))
    return " ".join(parts) or "<i>(пусто)</i>"


def _where(row: ArchivedMessage) -> str:
    who = html.escape(row.sender_name)
    chat = html.escape(row.chat_title)
    return f"👤 <b>{who}</b>" if who == chat else f"👤 <b>{who}</b> · {chat}"


async def resolve_owner(
    bot: Bot, session: AsyncSession, settings: Settings, connection_id: str | None
) -> User | None:
    """Владелец подключения, если оно активно и владелец есть в белом списке."""
    if not connection_id:
        return None
    connection = await repo.get_connection(session, connection_id)
    if connection is None:
        # Подключение могло случиться до запуска бота — спросим Telegram.
        try:
            info = await bot.get_business_connection(business_connection_id=connection_id)
        except TelegramAPIError:
            logger.warning("Unknown business connection %s", connection_id)
            return None
        connection = await repo.save_connection(session, info.id, info.user.id, info.is_enabled)
        if info.user.id in settings.allowed_user_ids:
            # Владелец мог ни разу не писать боту — тогда записи о нём ещё нет.
            await get_or_create_user(session, info.user, settings.default_timezone)
    if not connection.is_enabled or connection.owner_id not in settings.allowed_user_ids:
        return None
    return await session.get(User, connection.owner_id)


async def on_connection(
    connection: TgBusinessConnection, bot: Bot, session: AsyncSession, settings: Settings
):
    owner = connection.user
    if owner.id not in settings.allowed_user_ids:
        logger.warning("Business connection from user %s outside whitelist ignored", owner.id)
        return
    await repo.save_connection(session, connection.id, owner.id, connection.is_enabled)
    await get_or_create_user(session, owner, settings.default_timezone)
    if connection.is_enabled:
        text = (
            "🗄 <b>Архив чатов подключён.</b>\n\n"
            "Сохраняю сообщения из ваших личных чатов и пришлю сюда, если собеседник "
            "изменит или удалит сообщение. В сами чаты я ничего не пишу.\n\n"
            "/archive — состояние и настройки, /chats — чаты в архиве, "
            "/deleted — последние удалённые."
        )
    else:
        text = "🗄 Архив чатов отключён. Уже сохранённые сообщения остались: /chats"
    try:
        await bot.send_message(connection.user_chat_id, text, parse_mode="HTML")
    except TelegramAPIError:
        logger.exception("Failed to notify owner %s about business connection", owner.id)


async def on_business_message(
    message: Message, bot: Bot, session: AsyncSession, settings: Settings
):
    owner = await resolve_owner(bot, session, settings, message.business_connection_id)
    if owner is not None:
        await repo.store(session, owner.id, message)


async def on_edited_business_message(
    message: Message, bot: Bot, session: AsyncSession, settings: Settings
):
    owner = await resolve_owner(bot, session, settings, message.business_connection_id)
    if owner is None:
        return
    result = await repo.apply_edit(session, owner.id, message)
    row = result.message
    if not result.changed or row.outgoing or not owner.notify_edits:
        return
    text = (
        f"✏️ <b>Сообщение изменено</b>\n{_where(row)}\n\n"
        f"<b>Было:</b>\n{_short(result.old_text)}\n\n"
        f"<b>Стало:</b>\n{_short(row.text)}"
    )
    try:
        await bot.send_message(owner.id, text, parse_mode="HTML")
    except TelegramAPIError:
        logger.exception("Failed to notify %s about edited message", owner.id)


async def _resend_media(bot: Bot, owner_id: int, row: ArchivedMessage) -> None:
    sender = MEDIA_SENDERS.get(row.media_type or "")
    if sender is None or not row.file_id:
        return
    method, field, has_caption = sender
    kwargs = {"chat_id": owner_id, field: row.file_id}
    if has_caption:
        kwargs["caption"] = f"🗑 Удалено · {row.sender_name}"[:1024]
    try:
        await getattr(bot, method)(**kwargs)
    except TelegramAPIError:
        logger.warning("Could not resend deleted %s %s", row.media_type, row.id)


async def on_deleted_business_messages(
    event: BusinessMessagesDeleted, bot: Bot, session: AsyncSession, settings: Settings
):
    owner = await resolve_owner(bot, session, settings, event.business_connection_id)
    if owner is None:
        return
    rows, missing = await repo.mark_deleted(session, owner.id, event.chat.id, event.message_ids)
    incoming = [row for row in rows if not row.outgoing]
    if not owner.notify_deletes or (not incoming and not missing):
        return

    chat = html.escape(event.chat.full_name or event.chat.title or str(event.chat.id))
    total = len(incoming) + missing
    lines = [f"🗑 <b>Удалено сообщений: {total}</b> · {chat}", ""]
    for row in incoming[:SHOW_DELETED]:
        sent = row.sent_at.astimezone(ZoneInfo(owner.timezone))
        lines.append(f"{_where(row)}, {sent:%d.%m %H:%M}\n{_describe(row)}\n")
    if len(incoming) > SHOW_DELETED:
        lines.append(f"…и ещё {len(incoming) - SHOW_DELETED}: /deleted")
    if missing:
        lines.append(f"Текст {missing} из них неизвестен: они пришли до подключения архива.")
    try:
        await bot.send_message(owner.id, "\n".join(lines).strip(), parse_mode="HTML")
        for row in incoming[:SHOW_DELETED]:
            await _resend_media(bot, owner.id, row)
    except TelegramAPIError:
        logger.exception("Failed to notify %s about deleted messages", owner.id)


def create_router() -> Router:
    router = Router(name="business")
    router.business_connection.register(on_connection)
    router.business_message.register(on_business_message)
    router.edited_business_message.register(on_edited_business_message)
    router.deleted_business_messages.register(on_deleted_business_messages)
    return router
