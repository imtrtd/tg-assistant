from datetime import UTC, datetime

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import (
    AnswerInlineQuery,
    DeleteBusinessMessages,
    GetMe,
    SendMessage,
)
from aiogram.types import (
    BusinessBotRights,
    BusinessConnection,
    Chat,
    ChosenInlineResult,
    InlineQuery,
    Message,
    Update,
)
from aiogram.types import User as TgUser
from sqlalchemy import select

from tg_assistant.db import ArchivedMessage
from tg_assistant.db import notes as notes_repo

from .conftest import ALLOWED_ID, sent_methods, update_from

BOT_USER = TgUser(id=42, is_bot=True, first_name="Ассистент", username="MyAssistBot")
OWNER = TgUser(id=ALLOWED_ID, is_bot=False, first_name="Аня")
FRIEND = TgUser(id=555, is_bot=False, first_name="Пётр")
CHAT = Chat(id=FRIEND.id, type="private", first_name="Пётр")
T0 = datetime(2026, 11, 16, 10, 0, tzinfo=UTC)
CONN = "biz-1"


@pytest.fixture
def tg(bot):
    state = {"delete_fails": False}

    async def answer(method, *args, **kwargs):
        if isinstance(method, GetMe):
            return BOT_USER
        if isinstance(method, DeleteBusinessMessages) and state["delete_fails"]:
            raise TelegramBadRequest(method=method, message="Bad Request: not enough rights")
        return True

    bot.calls.side_effect = answer
    return state


@pytest.fixture
async def connected(bot, dp, tg):
    conn = BusinessConnection(
        id=CONN,
        user=OWNER,
        user_chat_id=ALLOWED_ID,
        date=T0,
        is_enabled=True,
        rights=BusinessBotRights(can_delete_outgoing_messages=True),
    )
    await dp.feed_update(bot, Update(update_id=1, business_connection=conn))
    bot.calls.reset_mock()


def biz(message_id, text, *, sender=OWNER, reply_to=None):
    msg = Message(
        message_id=message_id,
        date=T0,
        chat=CHAT,
        from_user=sender,
        text=text,
        business_connection_id=CONN,
        reply_to_message=reply_to,
    )
    return Update(update_id=message_id, business_message=msg)


async def notes(session_factory):
    async with session_factory() as session:
        items, _ = await notes_repo.list_notes(session, ALLOWED_ID, offset=0, limit=50)
        return [n.text for n in items]


async def archived(session_factory):
    async with session_factory() as session:
        return list(await session.scalars(select(ArchivedMessage)))


async def test_owner_mention_saves_note_and_hides_message(bot, dp, tg, connected, session_factory):
    await dp.feed_update(bot, biz(10, "@MyAssistBot купить <хлеб>"))

    assert await notes(session_factory) == ["купить <хлеб>\n\n— из чата: Пётр"]
    (delete,) = sent_methods(bot, DeleteBusinessMessages)
    assert delete.business_connection_id == CONN and delete.message_ids == [10]
    (confirm,) = sent_methods(bot, SendMessage)
    assert confirm.chat_id == ALLOWED_ID and confirm.business_connection_id is None
    assert "Сохранено как" in confirm.text and "&lt;хлеб&gt;" in confirm.text
    assert "осталось в чате" not in confirm.text
    assert await archived(session_factory) == []  # служебное сообщение не архивируем


async def test_mention_is_case_insensitive_and_allows_newline(
    bot, dp, tg, connected, session_factory
):
    await dp.feed_update(bot, biz(11, "@myassistbot\nидея на завтра"))
    assert (await notes(session_factory))[0].startswith("идея на завтра")


async def test_reply_with_mention_saves_quoted_message(bot, dp, tg, connected, session_factory):
    original = Message(message_id=5, date=T0, chat=CHAT, from_user=FRIEND, text="адрес: Ленина 1")
    await dp.feed_update(bot, biz(12, "@MyAssistBot", reply_to=original))

    assert await notes(session_factory) == ["↪ Пётр\nадрес: Ленина 1\n\n— из чата: Пётр"]


async def test_reply_with_mention_and_comment(bot, dp, tg, connected, session_factory):
    original = Message(message_id=5, date=T0, chat=CHAT, from_user=FRIEND, text="встреча в 19")
    await dp.feed_update(bot, biz(13, "@MyAssistBot не забыть", reply_to=original))

    assert await notes(session_factory) == ["↪ Пётр\nвстреча в 19\n\nне забыть\n\n— из чата: Пётр"]


async def test_bare_mention_without_reply_explains(bot, dp, tg, connected, session_factory):
    await dp.feed_update(bot, biz(14, "@MyAssistBot"))
    assert await notes(session_factory) == []
    assert "Напишите текст" in sent_methods(bot, SendMessage)[0].text


async def test_mention_by_friend_is_just_archived(bot, dp, tg, connected, session_factory):
    await dp.feed_update(bot, biz(15, "@MyAssistBot привет", sender=FRIEND))

    assert await notes(session_factory) == []
    assert sent_methods(bot, DeleteBusinessMessages) == []
    assert [m.text for m in await archived(session_factory)] == ["@MyAssistBot привет"]


async def test_mention_in_middle_is_regular_message(bot, dp, tg, connected, session_factory):
    await dp.feed_update(bot, biz(16, "спроси у @MyAssistBot"))
    assert await notes(session_factory) == []
    assert len(await archived(session_factory)) == 1


async def test_without_delete_right_note_is_saved_and_owner_is_told(
    bot, dp, tg, connected, session_factory
):
    tg["delete_fails"] = True
    await dp.feed_update(bot, biz(17, "@MyAssistBot важное"))

    assert len(await notes(session_factory)) == 1
    assert "осталось в чате" in sent_methods(bot, SendMessage)[0].text


# --- инлайн-режим ----------------------------------------------------------


def inline_update(query_text, user=OWNER):
    query = InlineQuery(id="q1", from_user=user, query=query_text, offset="")
    return Update(update_id=100, inline_query=query)


def chosen_update(query_text, result_id="save-note", user=OWNER):
    chosen = ChosenInlineResult(result_id=result_id, from_user=user, query=query_text)
    return Update(update_id=101, chosen_inline_result=chosen)


async def test_inline_query_offers_save(bot, dp, tg):
    await dp.feed_update(bot, inline_update("купить молоко"))
    (answer,) = sent_methods(bot, AnswerInlineQuery)
    (result,) = answer.results
    assert result.id == "save-note" and result.input_message_content.message_text == "купить молоко"
    assert answer.is_personal and answer.button.start_parameter == "inline"


async def test_empty_inline_query_shows_only_help_button(bot, dp, tg):
    await dp.feed_update(bot, inline_update("  "))
    (answer,) = sent_methods(bot, AnswerInlineQuery)
    assert answer.results == []


async def test_chosen_inline_result_saves_note(bot, dp, tg, session_factory):
    await dp.feed_update(bot, chosen_update("купить молоко"))
    assert await notes(session_factory) == ["купить молоко"]
    assert "Сохранено как" in sent_methods(bot, SendMessage)[0].text


async def test_inline_from_stranger_is_ignored(bot, dp, tg, session_factory):
    stranger = TgUser(id=777, is_bot=False, first_name="Чужой")
    await dp.feed_update(bot, inline_update("секрет", user=stranger))
    await dp.feed_update(bot, chosen_update("секрет", user=stranger))
    assert sent_methods(bot, AnswerInlineQuery) == []
    async with session_factory() as session:
        items, _ = await notes_repo.list_notes(session, 777, offset=0, limit=5)
    assert items == []


async def test_start_inline_explains_both_ways(bot, dp, tg):
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/start inline"))
    (help_msg,) = sent_methods(bot, SendMessage)
    assert "@MyAssistBot текст" in help_msg.text and "Telegram Business" in help_msg.text
