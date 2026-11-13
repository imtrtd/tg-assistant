from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from aiogram.exceptions import TelegramForbiddenError, TelegramNetworkError

from tg_assistant.db import Reminder, User
from tg_assistant.db import reminders as repo
from tg_assistant.reminders.format import format_when, parse_timezone
from tg_assistant.reminders.keyboards import RemCb
from tg_assistant.reminders.scheduler import fire_due
from tg_assistant.reminders.timeparse import DAILY

from .conftest import ALLOWED_ID, callback_from, edited_texts, sent_texts, update_from

MSK = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 11, 13, 11, 0, tzinfo=UTC)  # 14:00 по Москве, пятница


@pytest.fixture
async def owner(session_factory):
    async with session_factory() as session:
        session.add(User(id=ALLOWED_ID, first_name="Аня", timezone="Europe/Moscow"))
        await session.commit()


async def _add(session_factory, when, repeat=None, text="дело"):
    async with session_factory() as session:
        return await repo.add_reminder(session, ALLOWED_ID, text, when, repeat)


async def _get(session_factory, reminder_id) -> Reminder:
    async with session_factory() as session:
        return await session.get(Reminder, reminder_id)


# --- планировщик -----------------------------------------------------------


async def test_fires_due_one_off_once(bot, session_factory, owner):
    due = await _add(session_factory, NOW - timedelta(minutes=1), text="<срочно>")
    future = await _add(session_factory, NOW + timedelta(minutes=1))

    assert await fire_due(bot, session_factory, NOW) == 1
    assert await fire_due(bot, session_factory, NOW) == 0

    assert sent_texts(bot) == ["⏰ &lt;срочно&gt;"]
    assert not (await _get(session_factory, due.id)).active
    assert (await _get(session_factory, future.id)).active


async def test_daily_moves_to_next_day_keeping_local_time(bot, session_factory, owner):
    first = datetime(2026, 11, 13, 9, 0, tzinfo=MSK)
    reminder = await _add(session_factory, first, repeat=DAILY)

    await fire_due(bot, session_factory, NOW)

    stored = await _get(session_factory, reminder.id)
    assert stored.active
    assert stored.remind_at.astimezone(MSK) == datetime(2026, 11, 14, 9, 0, tzinfo=MSK)


async def test_repeat_after_long_downtime_fires_once_and_skips_missed(bot, session_factory, owner):
    week_ago = datetime(2026, 11, 6, 9, 0, tzinfo=MSK)
    reminder = await _add(session_factory, week_ago, repeat=DAILY)

    assert await fire_due(bot, session_factory, NOW) == 1
    assert await fire_due(bot, session_factory, NOW) == 0
    stored = await _get(session_factory, reminder.id)
    assert stored.remind_at.astimezone(MSK) == datetime(2026, 11, 14, 9, 0, tzinfo=MSK)


async def test_blocked_user_disables_reminder(bot, session_factory, owner):
    reminder = await _add(session_factory, NOW - timedelta(minutes=1))
    bot.calls.side_effect = TelegramForbiddenError(method=AsyncMock(), message="blocked")

    assert await fire_due(bot, session_factory, NOW) == 0
    assert not (await _get(session_factory, reminder.id)).active


async def test_network_error_keeps_reminder_for_retry(bot, session_factory, owner):
    reminder = await _add(session_factory, NOW - timedelta(minutes=1))
    bot.calls.side_effect = TelegramNetworkError(method=AsyncMock(), message="timeout")

    await fire_due(bot, session_factory, NOW)
    assert (await _get(session_factory, reminder.id)).active

    bot.calls.side_effect = None
    assert await fire_due(bot, session_factory, NOW) == 1


async def test_stored_time_roundtrips_as_aware_utc(session_factory, owner):
    when = datetime(2026, 11, 13, 18, 30, tzinfo=MSK)
    reminder = await _add(session_factory, when)

    stored = await _get(session_factory, reminder.id)
    assert stored.remind_at == when and stored.remind_at.tzinfo == UTC


# --- команды ---------------------------------------------------------------


async def _active(session_factory):
    async with session_factory() as session:
        return await repo.list_active(session, ALLOWED_ID, limit=100)


async def test_remind_command_creates_reminder(bot, dp, session_factory):
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/remind через 10 минут <чай>"))

    (reminder,) = await _active(session_factory)
    assert reminder.text == "<чай>"
    delta = reminder.remind_at - datetime.now(UTC)
    assert timedelta(minutes=9) < delta <= timedelta(minutes=10)
    assert "Напомню" in sent_texts(bot)[-1] and "&lt;чай&gt;" in sent_texts(bot)[-1]


async def test_remind_without_time_shows_help(bot, dp, session_factory):
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/remind просто текст"))

    assert await _active(session_factory) == []
    assert sent_texts(bot)[-1].startswith("Не понял, когда напомнить")


async def test_reminders_list_and_delete_button(bot, dp, session_factory):
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/remind каждый день 8:00 витамины"))
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/reminders"))
    assert "🔁 каждый день" in sent_texts(bot)[-1]

    (reminder,) = await _active(session_factory)
    data = RemCb(action="del", reminder_id=reminder.id).pack()
    await dp.feed_update(bot, callback_from(ALLOWED_ID, data))

    assert await _active(session_factory) == []
    assert "Активных напоминаний нет" in edited_texts(bot)[-1]


async def test_snooze_one_off_reactivates(bot, dp, session_factory):
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/start"))  # регистрирует пользователя
    reminder = await _add(session_factory, NOW - timedelta(hours=1))
    async with session_factory() as session:
        (await session.get(Reminder, reminder.id)).active = False
        await session.commit()

    data = RemCb(action="snooze", reminder_id=reminder.id, minutes=10).pack()
    await dp.feed_update(bot, callback_from(ALLOWED_ID, data))

    stored = await _get(session_factory, reminder.id)
    assert stored.active
    assert timedelta(minutes=9) < stored.remind_at - datetime.now(UTC) <= timedelta(minutes=10)


async def test_snooze_repeating_creates_one_off_copy(bot, dp, session_factory):
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/remind каждый день 8:00 витамины"))
    (daily,) = await _active(session_factory)
    original_time = daily.remind_at

    data = RemCb(action="snooze", reminder_id=daily.id, minutes=60).pack()
    await dp.feed_update(bot, callback_from(ALLOWED_ID, data))

    reminders = await _active(session_factory)
    assert len(reminders) == 2
    assert (await _get(session_factory, daily.id)).remind_at == original_time
    copy = next(r for r in reminders if r.id != daily.id)
    assert copy.repeat is None and copy.text == "витамины"


async def test_cannot_snooze_foreign_reminder(bot, dp, session_factory):
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/start"))
    async with session_factory() as session:
        session.add(User(id=999, first_name="Чужой", timezone="UTC"))
        await session.commit()
        foreign = await repo.add_reminder(session, 999, "чужое", NOW)
        foreign.active = False
        await session.commit()

    data = RemCb(action="snooze", reminder_id=foreign.id, minutes=10).pack()
    await dp.feed_update(bot, callback_from(ALLOWED_ID, data))

    assert not (await _get(session_factory, foreign.id)).active


async def test_timezone_command(bot, dp, session_factory):
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/timezone +5"))
    async with session_factory() as session:
        assert (await session.get(User, ALLOWED_ID)).timezone == "Etc/GMT-5"

    await dp.feed_update(bot, update_from(ALLOWED_ID, "/timezone Марс"))
    assert "Не знаю такой часовой пояс" in sent_texts(bot)[-1]


# --- форматирование --------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("europe/moscow", "Europe/Moscow"),
        ("Asia/Yekaterinburg", "Asia/Yekaterinburg"),
        ("мск", "Europe/Moscow"),
        ("+3", "Etc/GMT-3"),
        ("UTC-5", "Etc/GMT+5"),
        ("utc+0", "UTC"),
        ("+15", None),
        ("Mars/Olympus", None),
    ],
)
def test_parse_timezone(raw, expected):
    assert parse_timezone(raw) == expected


def test_format_when():
    now = datetime(2026, 11, 13, 14, 0, tzinfo=MSK)
    assert format_when(datetime(2026, 11, 13, 18, 30, tzinfo=MSK), now) == "пт 13.11 18:30"
    assert format_when(datetime(2027, 1, 4, 9, 0, tzinfo=MSK), now) == "пн 04.01.2027 09:00"


async def test_fired_message_has_buttons(bot, session_factory, owner):
    await _add(session_factory, NOW - timedelta(minutes=1))
    await fire_due(bot, session_factory, NOW)

    (method,) = [c.args[0] for c in bot.calls.await_args_list]
    labels = [b.text for row in method.reply_markup.inline_keyboard for b in row]
    assert labels == ["✅ Готово", "⏰ 10 мин", "⏰ 1 час"]
