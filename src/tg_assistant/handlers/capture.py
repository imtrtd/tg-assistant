"""Быстрое сохранение: любое сообщение без команды.

- Пересланное сообщение сразу сохраняется заметкой.
- Обычный текст: бот отвечает кнопками «В заметки» и, если в тексте есть время,
  «Напомнить …». Текст берётся из сообщения, на которое ответил бот, поэтому
  ничего не нужно хранить между нажатиями.

Роутер подключается последним, чтобы не перехватывать команды и другие обработчики.
"""

import html
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import User
from ..db import notes as notes_repo
from ..db import reminders as reminders_repo
from ..reminders.format import format_repeat, format_when
from ..reminders.timeparse import parse_reminder


class CaptureCb(CallbackData, prefix="cap"):
    action: str  # "note" | "remind" | "cancel"


def _text_of(message: Message | None) -> str | None:
    if message is None:
        return None
    text = message.text or message.caption
    return text.strip() if text and text.strip() else None


def _forward_source(message: Message) -> str | None:
    origin = message.forward_origin
    if origin is None:
        return None
    for attr in ("sender_user", "chat", "sender_chat"):
        source = getattr(origin, attr, None)
        if source is not None:
            name = getattr(source, "full_name", None) or getattr(source, "title", None)
            if name:
                return name
    return getattr(origin, "sender_user_name", None)


async def on_text(message: Message, session: AsyncSession, user: User):
    text = _text_of(message)
    if text is None:
        return

    if message.forward_origin is not None:
        source = _forward_source(message)
        body = f"↪ {source}\n{text}" if source else text
        note = await notes_repo.add_note(session, user.id, body)
        await message.reply(f"Сохранено в заметки как <b>#{note.id}</b>", parse_mode="HTML")
        return

    kb = InlineKeyboardBuilder()
    kb.button(text="📝 В заметки", callback_data=CaptureCb(action="note"))
    parsed = parse_reminder(text, datetime.now(ZoneInfo(user.timezone)))
    if parsed is not None:
        kb.button(
            text=f"⏰ {format_when(parsed.when, parsed.when)}",
            callback_data=CaptureCb(action="remind"),
        )
    kb.button(text="✖", callback_data=CaptureCb(action="cancel"))
    kb.adjust(2 if parsed is None else 3)
    await message.reply("Что сделать с этим сообщением?", reply_markup=kb.as_markup())


async def on_choice(
    query: CallbackQuery, callback_data: CaptureCb, session: AsyncSession, user: User
):
    prompt = query.message if isinstance(query.message, Message) else None
    original = prompt.reply_to_message if prompt else None
    text = _text_of(original)

    if callback_data.action == "cancel" or text is None:
        if prompt:
            await prompt.delete()
        await query.answer("Исходное сообщение не найдено" if text is None else None)
        return

    if callback_data.action == "note":
        note = await notes_repo.add_note(session, user.id, text)
        result = f"📝 Сохранено в заметки как <b>#{note.id}</b>"
    else:
        now = datetime.now(ZoneInfo(user.timezone))
        parsed = parse_reminder(text, now)
        if parsed is None:
            await query.answer("Это время уже прошло", show_alert=True)
            return
        reminder = await reminders_repo.add_reminder(
            session, user.id, parsed.text, parsed.when, parsed.repeat
        )
        when = reminder.remind_at.astimezone(ZoneInfo(user.timezone))
        repeat = format_repeat(reminder.repeat, when)
        result = f"⏰ Напомню <b>{format_when(when, now)}</b>" + (f" 🔁 {repeat}" if repeat else "")
        result += f"\n{html.escape(reminder.text)}"

    if prompt:
        await prompt.edit_text(result, parse_mode="HTML")
    await query.answer()


def create_router() -> Router:
    router = Router(name="capture")
    router.message.register(on_text, F.chat.type == "private", ~F.text.startswith("/"))
    router.callback_query.register(on_choice, CaptureCb.filter())
    return router
