from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from aiogram.types import Message
from sqlalchemy import func, select

from tg_assistant.db import (
    ArchivedMessage,
    MessageEdit,
    Note,
    Reminder,
    ResearchSeenPost,
    ResearchWatch,
    User,
)
from tg_assistant.db import wipe as wipe_repo
from tg_assistant.handlers import wipe as wipe_handlers

NOW = datetime(2026, 11, 25, tzinfo=UTC)


def test_password_hash_roundtrip():
    stored = wipe_repo.hash_password("секрет-123")
    assert stored.startswith("scrypt$") and "секрет" not in stored
    assert wipe_repo.check_password("секрет-123", stored)
    assert not wipe_repo.check_password("другой", stored)
    assert not wipe_repo.check_password("секрет-123", None)
    assert not wipe_repo.check_password("секрет-123", "мусор")


async def _fill(session, user_id, other_id):
    for uid in (user_id, other_id):
        session.add(User(id=uid, first_name="u", timezone="UTC"))
    await session.flush()
    for uid in (user_id, other_id):
        session.add(Note(user_id=uid, text="n", search_text="n"))
        session.add(Reminder(user_id=uid, text="r", remind_at=NOW))
        archived = ArchivedMessage(
            owner_id=uid,
            chat_id=1,
            chat_title="c",
            message_id=uid,
            sender_name="s",
            outgoing=False,
            text="t",
            sent_at=NOW,
        )
        session.add(archived)
        await session.flush()
        session.add(MessageEdit(message_id=archived.id, text="old", replaced_at=NOW))
        watch = ResearchWatch(chat_id=uid, user_id=uid, term="x", term_key="x", created_at=NOW)
        session.add(watch)
        await session.flush()
        session.add(ResearchSeenPost(watch_id=watch.id, peer_id=1, message_id=1, found_at=NOW))
    await session.commit()


async def _count(session, model):
    return await session.scalar(select(func.count()).select_from(model))


async def test_wipe_archive_touches_only_archive_of_owner(session):
    await _fill(session, 1, 2)
    assert await wipe_repo.wipe_archive(session, 1) == 1
    assert await _count(session, ArchivedMessage) == 1
    assert await _count(session, MessageEdit) == 1
    assert await _count(session, Note) == 2


async def test_wipe_everything_keeps_user_and_other_people(session):
    await _fill(session, 1, 2)
    counts = await wipe_repo.wipe_everything(session, 1)
    assert counts == {"архив": 1, "заметки": 1, "напоминания": 1, "наблюдения": 1}
    for model in (Note, Reminder, ArchivedMessage, MessageEdit, ResearchWatch, ResearchSeenPost):
        assert await _count(session, model) == 1
    assert await session.get(User, 1) is not None


def handlers():
    router = wipe_handlers.create_router()
    found = {}
    for observer in (router.message, router.callback_query):
        for handler in observer.handlers:
            found[handler.callback.__name__] = handler.callback
    return found


def message(text="", chat_type="private", mid=50):
    msg = MagicMock()
    msg.text = text
    msg.message_id = mid
    msg.chat.type = chat_type
    msg.chat.id = 1
    msg.from_user.id = 1
    msg.answer = AsyncMock()
    msg.delete = AsyncMock()
    return msg


def command(args):
    cmd = MagicMock()
    cmd.args = args
    return cmd


def query(action, msg):
    q = MagicMock()
    q.message = msg
    q.answer = AsyncMock()
    return q, wipe_handlers.WipeCb(action=action)


async def test_wipe_requires_password_first(session):
    h = handlers()
    user = User(id=1, first_name="u", timezone="UTC")
    msg = message("/wipe")
    await h["cmd_wipe"](msg, command(None), user, session)
    assert "/wipe set" in msg.answer.await_args.args[0]
    assert "reply_markup" not in msg.answer.await_args.kwargs


async def test_set_and_change_password_deletes_message(session):
    h = handlers()
    session.add(User(id=1, first_name="u", timezone="UTC"))
    await session.commit()
    user = await session.get(User, 1)

    msg = message("/wipe set секрет-123")
    await h["cmd_wipe"](msg, command("set секрет-123"), user, session)
    msg.delete.assert_awaited()
    assert wipe_repo.check_password("секрет-123", user.wipe_password_hash)

    short = message()
    await h["cmd_wipe"](short, command("set старый-но-неверный новый-пароль"), user, session)
    assert wipe_repo.check_password("секрет-123", user.wipe_password_hash)

    ok = message()
    await h["cmd_wipe"](ok, command("set секрет-123 новый-пароль"), user, session)
    assert wipe_repo.check_password("новый-пароль", user.wipe_password_hash)


async def _armed(session, action):
    h = handlers()
    session.add(User(id=1, first_name="u", timezone="UTC"))
    await session.commit()
    user = await session.get(User, 1)
    user.wipe_password_hash = wipe_repo.hash_password("секрет-123")
    await session.commit()
    msg = MagicMock(spec=Message)
    msg.answer = AsyncMock()
    q, cb = query(action, msg)
    await h["on_button"](q, cb, user)
    return h, user


async def test_archive_button_needs_correct_password(session):
    h, user = await _armed(session, wipe_handlers.ARCHIVE)
    await _fill_archive(session)

    wrong = message("не тот пароль")
    await h["on_password"](wrong, AsyncMock(), user, session)
    wrong.delete.assert_awaited()
    assert "Осталось попыток: 4" in wrong.answer.await_args.args[0]
    assert await _count(session, ArchivedMessage) == 1

    right = message("секрет-123")
    await h["on_password"](right, AsyncMock(), user, session)
    right.delete.assert_awaited()
    assert await _count(session, ArchivedMessage) == 0
    assert "Архив стёрт" in right.answer.await_args.args[0]


async def _fill_archive(session):
    session.add(
        ArchivedMessage(
            owner_id=1,
            chat_id=1,
            chat_title="c",
            message_id=1,
            sender_name="s",
            outgoing=False,
            text="t",
            sent_at=NOW,
        )
    )
    await session.commit()


async def test_lockout_after_five_wrong_passwords(session):
    h, user = await _armed(session, wipe_handlers.ARCHIVE)
    await _fill_archive(session)
    for _ in range(wipe_handlers.MAX_ATTEMPTS):
        # после каждой неудачи пароль ждёт дальше, пока не наступит блокировка
        msg = message("неверный")
        await h["on_password"](msg, AsyncMock(), user, session)
    assert "Слишком много" in msg.answer.await_args.args[0]

    right = message("секрет-123")
    locked_msg = MagicMock(spec=Message)
    q, cb = query(wipe_handlers.ARCHIVE, locked_msg)
    await h["on_button"](q, cb, user)
    assert q.answer.await_args.kwargs.get("show_alert") is True
    await h["on_password"](right, AsyncMock(), user, session)  # ожидания уже нет
    assert await _count(session, ArchivedMessage) == 1


async def test_password_ignored_when_nothing_pending():
    router = wipe_handlers.create_router()
    on_password = next(h for h in router.message.handlers if h.callback.__name__ == "on_password")
    check = on_password.filters[-1].callback
    # без нажатой кнопки обычный текст не принимается за пароль
    assert check(message("просто текст")) is False


async def test_chat_wipe_deletes_in_batches():
    bot = MagicMock()
    bot.delete_messages = AsyncMock()
    await wipe_handlers.wipe_chat(bot, 1, 250)
    ids = [i for call in bot.delete_messages.await_args_list for i in call.args[1]]
    assert max(ids) == 250 and min(ids) == 1 and len(ids) == len(set(ids)) == 250
    assert all(len(call.args[1]) <= 100 for call in bot.delete_messages.await_args_list)
