from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import EditMessageText, SendDocument, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, MessageOriginUser, Update
from aiogram.types import User as TgUser

from tg_assistant.db import Reminder, User
from tg_assistant.db import notes as notes_repo
from tg_assistant.db import reminders as reminders_repo
from tg_assistant.db.digest import build_digest, next_digest_at, parse_digest_time, set_digest
from tg_assistant.handlers import errors
from tg_assistant.handlers.capture import CaptureCb
from tg_assistant.reminders.scheduler import fire_digests

from .conftest import ALLOWED_ID, sent_methods, sent_texts, update_from

MSK = ZoneInfo("Europe/Moscow")
# пятница, 13.11.2026, 05:00 UTC = 08:00 МСК
NOW = datetime(2026, 11, 13, 5, 0, tzinfo=UTC)


@pytest.fixture
async def anya(session_factory):
    async with session_factory() as session:
        session.add(User(id=ALLOWED_ID, first_name="Аня", timezone="Europe/Moscow"))
        await session.commit()


async def _user(session_factory) -> User:
    async with session_factory() as session:
        return await session.get(User, ALLOWED_ID)


# --- время сводки ----------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("8", "08:00"),
        ("8:30", "08:30"),
        ("08.05", "08:05"),
        ("23:59", "23:59"),
        ("24:00", None),
        ("7:60", None),
        ("утром", None),
        ("", None),
        ("123", None),
    ],
)
def test_parse_digest_time(raw, expected):
    assert parse_digest_time(raw) == expected


def test_next_digest_at_uses_local_time():
    # 08:00 МСК уже наступило ровно сейчас -> завтра
    assert next_digest_at("08:00", "Europe/Moscow", NOW) == NOW + timedelta(days=1)
    assert next_digest_at("09:00", "Europe/Moscow", NOW) == NOW + timedelta(hours=1)
    assert next_digest_at("09:00", "UTC", NOW) == datetime(2026, 11, 13, 9, 0, tzinfo=UTC)


# --- рассылка сводки -------------------------------------------------------


async def test_digest_lists_only_todays_reminders(session_factory, anya):
    async with session_factory() as session:
        today = datetime(2026, 11, 13, 18, 30, tzinfo=MSK)
        await reminders_repo.add_reminder(session, ALLOWED_ID, "<созвон>", today)
        await reminders_repo.add_reminder(session, ALLOWED_ID, "завтра", today + timedelta(days=1))
        await notes_repo.add_note(session, ALLOWED_ID, "заметка")
        text = await build_digest(session, await session.get(User, ALLOWED_ID), NOW)

    assert "Сегодня напоминаний: 1" in text
    assert "<b>18:30</b> &lt;созвон&gt;" in text and "завтра" not in text
    assert "Заметок всего: 1" in text


async def test_fire_digests_sends_once_and_schedules_next_day(bot, session_factory, anya):
    async with session_factory() as session:
        user = await session.get(User, ALLOWED_ID)
        set_digest(user, "08:00", now=NOW - timedelta(minutes=5))
        await session.commit()

    assert await fire_digests(bot, session_factory, NOW) == 1
    assert await fire_digests(bot, session_factory, NOW) == 0
    assert "Доброе утро, Аня" in sent_texts(bot)[0]
    assert (await _user(session_factory)).digest_next_at == NOW + timedelta(days=1)


async def test_fire_digests_after_downtime_sends_one(bot, session_factory, anya):
    async with session_factory() as session:
        user = await session.get(User, ALLOWED_ID)
        set_digest(user, "08:00", now=NOW - timedelta(days=5))
        await session.commit()

    assert await fire_digests(bot, session_factory, NOW) == 1
    assert await fire_digests(bot, session_factory, NOW) == 0


async def test_blocked_user_digest_is_disabled(bot, session_factory, anya):
    async with session_factory() as session:
        set_digest(await session.get(User, ALLOWED_ID), "08:00", now=NOW - timedelta(hours=1))
        await session.commit()
    bot.calls.side_effect = TelegramForbiddenError(method=AsyncMock(), message="blocked")

    assert await fire_digests(bot, session_factory, NOW) == 0
    user = await _user(session_factory)
    assert user.digest_time is None and user.digest_next_at is None


# --- команды ---------------------------------------------------------------


async def test_digest_command_enable_show_disable(bot, dp, session_factory):
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/digest 7:30"))
    user = await _user(session_factory)
    assert user.digest_time == "07:30" and user.digest_next_at > datetime.now(UTC)
    assert "каждый день в 07:30" in sent_texts(bot)[-1]

    await dp.feed_update(bot, update_from(ALLOWED_ID, "/digest"))
    assert "включена, в 07:30" in sent_texts(bot)[-1]

    await dp.feed_update(bot, update_from(ALLOWED_ID, "/digest утром"))
    assert "Не понял время" in sent_texts(bot)[-1]

    await dp.feed_update(bot, update_from(ALLOWED_ID, "/digest off"))
    user = await _user(session_factory)
    assert user.digest_time is None and user.digest_next_at is None


async def test_timezone_change_reschedules_digest(bot, dp, session_factory):
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/digest 8:00"))
    before = (await _user(session_factory)).digest_next_at
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/timezone Asia/Vladivostok"))
    after = (await _user(session_factory)).digest_next_at

    assert after != before
    assert after.astimezone(ZoneInfo("Asia/Vladivostok")).strftime("%H:%M") == "08:00"


async def test_export_sends_txt_file(bot, dp):
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/export"))
    assert "выгружать нечего" in sent_texts(bot)[-1]

    await dp.feed_update(bot, update_from(ALLOWED_ID, "/note первая #тег"))
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/note вторая"))
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/export"))

    (doc,) = sent_methods(bot, SendDocument)
    assert doc.document.filename.startswith("notes-") and doc.document.filename.endswith(".txt")
    content = doc.document.data.decode()
    assert content.index("первая #тег") < content.index("вторая")
    assert doc.caption == "Заметок: 2"


# --- быстрое сохранение ----------------------------------------------------


def _message(text, *, forward_from=None, reply_to=None, message_id=1, user_id=ALLOWED_ID):
    user = TgUser(id=user_id, is_bot=False, first_name="Аня")
    origin = (
        MessageOriginUser(date=datetime.now(), sender_user=forward_from) if forward_from else None
    )
    return Message(
        message_id=message_id,
        date=datetime.now(),
        chat=Chat(id=user_id, type="private"),
        from_user=user,
        text=text,
        forward_origin=origin,
        reply_to_message=reply_to,
    )


def _choice(action: str, original: Message | None) -> Update:
    prompt = Message(
        message_id=50,
        date=datetime.now(),
        chat=Chat(id=ALLOWED_ID, type="private"),
        text="Что сделать с этим сообщением?",
        reply_to_message=original,
    )
    query = CallbackQuery(
        id="q",
        from_user=TgUser(id=ALLOWED_ID, is_bot=False, first_name="Аня"),
        chat_instance="ci",
        message=prompt,
        data=CaptureCb(action=action).pack(),
    )
    return Update(update_id=9, callback_query=query)


async def _all_notes(session_factory):
    async with session_factory() as session:
        items, _ = await notes_repo.list_notes(session, ALLOWED_ID, offset=0, limit=100)
        return [n.text for n in items]


async def test_plain_text_offers_note_and_reminder(bot, dp):
    await dp.feed_update(bot, Update(update_id=1, message=_message("завтра в 9 позвонить маме")))

    (prompt,) = sent_methods(bot, SendMessage)
    assert prompt.reply_parameters.message_id == 1
    labels = [b.text for row in prompt.reply_markup.inline_keyboard for b in row]
    assert labels[0] == "📝 В заметки" and labels[1].startswith("⏰ ") and labels[2] == "✖"


async def test_text_without_time_offers_only_note(bot, dp):
    await dp.feed_update(bot, Update(update_id=1, message=_message("просто мысль")))
    (prompt,) = sent_methods(bot, SendMessage)
    labels = [b.text for row in prompt.reply_markup.inline_keyboard for b in row]
    assert labels == ["📝 В заметки", "✖"]


async def test_unknown_command_is_not_captured(bot, dp):
    await dp.feed_update(bot, Update(update_id=1, message=_message("/nope")))
    assert sent_methods(bot, SendMessage) == []


async def test_forwarded_message_is_saved_with_source(bot, dp, session_factory):
    author = TgUser(id=5, is_bot=False, first_name="Пётр", last_name="Иванов")
    await dp.feed_update(
        bot, Update(update_id=1, message=_message("адрес: Ленина 1", forward_from=author))
    )

    assert await _all_notes(session_factory) == ["↪ Пётр Иванов\nадрес: Ленина 1"]
    assert "Сохранено в заметки" in sent_texts(bot)[-1]


async def test_choice_note_saves_original_text(bot, dp, session_factory):
    await dp.feed_update(bot, _choice("note", _message("идея для отпуска")))

    assert await _all_notes(session_factory) == ["идея для отпуска"]
    (edit,) = sent_methods(bot, EditMessageText)
    assert "Сохранено в заметки" in edit.text


async def test_choice_remind_creates_reminder(bot, dp, session_factory):
    await dp.feed_update(bot, _choice("remind", _message("через 15 минут выключить духовку")))

    async with session_factory() as session:
        (reminder,) = await reminders_repo.list_active(session, ALLOWED_ID, limit=5)
    assert reminder.text == "выключить духовку"
    assert timedelta(minutes=14) < reminder.remind_at - datetime.now(UTC) <= timedelta(minutes=15)
    assert "Напомню" in sent_methods(bot, EditMessageText)[0].text


async def test_choice_without_original_does_nothing(bot, dp, session_factory):
    await dp.feed_update(bot, _choice("note", None))
    assert await _all_notes(session_factory) == []
    async with session_factory() as session:
        assert (await session.scalar(Reminder.__table__.select().limit(1))) is None


# --- оповещение админа -----------------------------------------------------


async def test_admin_is_notified_about_errors_once_per_interval(bot, session_factory, monkeypatch):
    from tg_assistant.bot import create_dispatcher
    from tg_assistant.config import Settings
    from tg_assistant.handlers import common

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "42:TEST")
    monkeypatch.setenv("ALLOWED_USER_IDS", str(ALLOWED_ID))
    monkeypatch.setenv("ADMIN_IDS", "777")
    monkeypatch.setattr(errors, "_last_alert", None)
    monkeypatch.setattr(errors.time, "monotonic", lambda: 5.0)  # как сразу после загрузки
    monkeypatch.setattr(common, "HELP_TEXT", None)  # answer(None) -> ошибка в хендлере
    dp = create_dispatcher(Settings(_env_file=None), session_factory)

    await dp.feed_update(bot, update_from(ALLOWED_ID, "/help"))
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/help"))

    to_admin = [m for m in sent_methods(bot, SendMessage) if m.chat_id == 777]
    assert len(to_admin) == 1
    text = to_admin[0].text
    assert "Ошибка в боте" in text and "ValidationError" in text and "<pre>" in text
    assert len(text) < 4096  # лимит Telegram


def test_alert_fits_telegram_limit_even_with_heavy_escaping():
    try:
        raise ValueError("<&>" * 2000)
    except ValueError as exc:
        event = errors.ErrorEvent(update=Update(update_id=1), exception=exc)
    text = errors.format_alert(event)
    assert len(text) < 4096
    body = text.split("<pre>")[1]
    assert "&lt;" in body and not body.startswith(("lt;", "gt;", "amp;"))
