"""Отправка сообщений из архива владельцу в личку с ботом.

Используется и уведомлениями об удалениях, и кнопкой «Прислать в Telegram»
в мини-приложении. Отправляет только владельцу — никогда в бизнес-чаты.
"""

import html

from aiogram import Bot

from .db import ArchivedMessage
from .db.archive import MEDIA_LABELS

CAPTION_LIMIT = 1024
TEXT_LIMIT = 4000

# media_type -> (метод бота, имя параметра, поддерживает ли подпись)
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


async def send_media(bot: Bot, owner_id: int, row: ArchivedMessage, caption: str | None) -> bool:
    """Отправить вложение по file_id. False — если вложения нет или тип не поддержан."""
    sender = MEDIA_SENDERS.get(row.media_type or "")
    if sender is None or not row.file_id:
        return False
    method, field, has_caption = sender
    kwargs = {"chat_id": owner_id, field: row.file_id}
    if has_caption and caption:
        kwargs["caption"] = caption[:CAPTION_LIMIT]
    await getattr(bot, method)(**kwargs)
    return True


def archived_header(row: ArchivedMessage) -> str:
    who = html.escape(row.sender_name)
    chat = html.escape(row.chat_title)
    where = who if who == chat else f"{who} · {chat}"
    stamp = row.sent_at.strftime("%d.%m.%Y %H:%M UTC")
    marks = []
    if row.edited_at:
        marks.append("изменено")
    if row.deleted_at:
        marks.append("удалено")
    suffix = f" ({', '.join(marks)})" if marks else ""
    return f"🗄 <b>Из архива</b>: {where}, {stamp}{suffix}"


async def resend_archived(bot: Bot, owner_id: int, row: ArchivedMessage) -> None:
    """Прислать владельцу сообщение из архива: заголовок с текстом, затем вложение."""
    header = archived_header(row)
    text = row.text or ""
    if row.media_type and not row.text:
        text = f"[{MEDIA_LABELS.get(row.media_type, row.media_type)}]"
    body = html.escape(text[:TEXT_LIMIT])
    await bot.send_message(owner_id, f"{header}\n\n{body}" if body else header, parse_mode="HTML")
    await send_media(bot, owner_id, row, caption=None)
