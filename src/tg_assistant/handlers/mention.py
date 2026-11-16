"""Заметки из других чатов по упоминанию бота.

1. Через Telegram Business (бот подключён к аккаунту): владелец пишет в любом личном
   чате «@бот текст» — бот сохраняет заметку и удаляет это сообщение, чтобы собеседник
   его не видел. Если так ответить на сообщение собеседника (можно просто «@бот»),
   сохранится текст того сообщения.
2. Инлайн-режим: «@бот текст» в любом чате → пункт «Сохранить в заметки». Текст при
   этом отправляется в чат как обычное сообщение, заметка сохраняется по выбору пункта.

Подтверждение приходит только владельцу в личку с ботом — в чаты бот ничего не пишет.
"""

import html
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandStart
from aiogram.types import (
    ChosenInlineResult,
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultsButton,
    InputTextMessageContent,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import User
from ..db import notes as notes_repo
from ..db.archive import chat_title, sender_name, text_of
from ..topics import NOTES, topic_kind

logger = logging.getLogger(__name__)

INLINE_RESULT_ID = "save-note"
PREVIEW = 100


async def mention_text(bot: Bot, message: Message) -> str | None:
    """Текст после упоминания бота, если сообщение начинается с «@бот». Иначе None."""
    text = text_of(message)
    if not text:
        return None
    me = await bot.me()
    if not me.username:
        return None
    mention = f"@{me.username}".lower()
    head, _, rest = text.strip().partition(" ")
    if head.lower() != mention and not text.strip().lower().startswith(mention + "\n"):
        return None
    if head.lower() != mention:  # «@бот\nтекст»
        rest = text.strip()[len(mention) :]
    return rest.strip()


def _note_body(message: Message, own_text: str) -> str | None:
    """Что сохранить: свой текст, а при ответе на сообщение — ещё и его текст с автором."""
    replied = message.reply_to_message
    quoted = text_of(replied) if replied is not None else None
    parts = []
    if quoted:
        parts.append(f"↪ {sender_name(replied)}\n{quoted}")
    if own_text:
        parts.append(own_text)
    if not parts:
        return None
    parts.append(f"— из чата: {chat_title(message)}")
    return "\n\n".join(parts)


async def handle_business_mention(
    message: Message, bot: Bot, session: AsyncSession, owner: User
) -> bool:
    """Обработать «@бот …» владельца в бизнес-чате. True — сообщение было командой."""
    if message.from_user is None or message.from_user.id != owner.id:
        return False
    own_text = await mention_text(bot, message)
    if own_text is None:
        return False

    body = _note_body(message, own_text)
    if body is None:
        with topic_kind(NOTES):
            await bot.send_message(
                owner.id,
                "Напишите текст после упоминания или ответьте упоминанием на сообщение.",
            )
        return True

    note = await notes_repo.add_note(session, owner.id, body)
    # Убираем служебное сообщение из переписки (нужно право удалять исходящие).
    hidden = True
    try:
        await bot.delete_business_messages(
            business_connection_id=message.business_connection_id,
            message_ids=[message.message_id],
        )
    except TelegramAPIError:
        hidden = False
        logger.info("Could not delete mention message in chat %s", message.chat.id)

    preview = body if len(body) <= PREVIEW * 3 else body[: PREVIEW * 3] + "…"
    lines = [
        f"📝 Сохранено как <b>#{note.id}</b> из чата <b>{html.escape(chat_title(message))}</b>",
        "",
        html.escape(preview),
    ]
    if not hidden:
        lines += [
            "",
            "Сообщение с упоминанием осталось в чате: разрешите боту удалять исходящие "
            "сообщения (Настройки → Telegram Business → Чат-боты).",
        ]
    with topic_kind(NOTES):
        await bot.send_message(owner.id, "\n".join(lines), parse_mode="HTML")
    return True


def mention_help(username: str | None) -> str:
    bot = f"@{username}" if username else "@имя_бота"
    return (
        "📝 <b>Заметки из других чатов</b>\n\n"
        f"<b>В любом личном чате</b> (нужен Telegram Business, см. /archive): напишите "
        f"<code>{bot} текст</code> — сохраню заметку и сотру это сообщение, собеседник его "
        f"не увидит. Ответьте <code>{bot}</code> на чужое сообщение — сохраню его текст.\n\n"
        f"<b>В любом чате</b> (инлайн-режим): начните сообщение с <code>{bot} текст</code> и "
        "выберите «Сохранить в заметки». Текст уйдёт в чат и сохранится у меня."
    )


async def cmd_start_inline(message: Message, bot: Bot):
    me = await bot.me()
    await message.answer(mention_help(me.username), parse_mode="HTML")


# --- инлайн-режим ----------------------------------------------------------


async def on_inline_query(query: InlineQuery, user: User):
    text = query.query.strip()
    button = InlineQueryResultsButton(
        text="Как сохранять заметки из чатов", start_parameter="inline"
    )
    if not text:
        await query.answer([], cache_time=0, is_personal=True, button=button)
        return
    preview = text if len(text) <= PREVIEW else text[:PREVIEW] + "…"
    result = InlineQueryResultArticle(
        id=INLINE_RESULT_ID,
        title="📝 Сохранить в заметки",
        description=f"Текст уйдёт в чат и сохранится: {preview}",
        input_message_content=InputTextMessageContent(message_text=text),
    )
    await query.answer([result], cache_time=0, is_personal=True, button=button)


async def on_chosen_inline_result(
    chosen: ChosenInlineResult, bot: Bot, session: AsyncSession, user: User
):
    if chosen.result_id != INLINE_RESULT_ID or not chosen.query.strip():
        return
    note = await notes_repo.add_note(session, user.id, chosen.query.strip())
    with topic_kind(NOTES):
        await bot.send_message(user.id, f"📝 Сохранено как <b>#{note.id}</b>", parse_mode="HTML")


def create_router() -> Router:
    router = Router(name="mention")
    router.message.register(
        cmd_start_inline, CommandStart(deep_link=True, magic=F.args == "inline")
    )
    router.inline_query.register(on_inline_query)
    router.chosen_inline_result.register(on_chosen_inline_result)
    return router
