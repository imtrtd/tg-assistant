from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from tg_assistant.reminders.timeparse import (
    DAILY,
    WEEKDAYS,
    WEEKLY,
    next_occurrence,
    parse_reminder,
)

TZ = ZoneInfo("Europe/Moscow")
# пятница, 13 ноября 2026, 14:00
NOW = datetime(2026, 11, 13, 14, 0, tzinfo=TZ)


def dt(*args):
    return datetime(*args, tzinfo=TZ)


@pytest.mark.parametrize(
    ("raw", "when", "text"),
    [
        ("через 10 минут позвонить", dt(2026, 11, 13, 14, 10), "позвонить"),
        ("через 10мин чай", dt(2026, 11, 13, 14, 10), "чай"),
        ("через 2 часа встреча", dt(2026, 11, 13, 16, 0), "встреча"),
        ("через час обед", dt(2026, 11, 13, 15, 0), "обед"),
        ("через полчаса выйти", dt(2026, 11, 13, 14, 30), "выйти"),
        ("через 3 дня оплатить", dt(2026, 11, 16, 14, 0), "оплатить"),
        ("через неделю отчёт", dt(2026, 11, 20, 14, 0), "отчёт"),
        ("18:30 Позвонить маме", dt(2026, 11, 13, 18, 30), "Позвонить маме"),
        ("9:00 зарядка", dt(2026, 11, 14, 9, 0), "зарядка"),  # уже прошло -> завтра
        ("в 18 спорт", dt(2026, 11, 13, 18, 0), "спорт"),
        ("в 18:05 - спорт", dt(2026, 11, 13, 18, 5), "спорт"),
        ("завтра купить хлеб", dt(2026, 11, 14, 9, 0), "купить хлеб"),
        ("Завтра в 7:30 будильник", dt(2026, 11, 14, 7, 30), "будильник"),
        ("послезавтра 20:00 кино", dt(2026, 11, 15, 20, 0), "кино"),
        ("сегодня 23:59 спать", dt(2026, 11, 13, 23, 59), "спать"),
        ("25.12 подарки", dt(2026, 12, 25, 9, 0), "подарки"),
        ("01.02 10:00 налоги", dt(2027, 2, 1, 10, 0), "налоги"),  # дата прошла -> след. год
        ("01.02.2028 10:00 виза", dt(2028, 2, 1, 10, 0), "виза"),
        ("в понедельник 10:00 планёрка", dt(2026, 11, 16, 10, 0), "планёрка"),
        ("в среду созвон", dt(2026, 11, 18, 9, 0), "созвон"),
        ("пятница 15:00 ревью", dt(2026, 11, 13, 15, 0), "ревью"),  # сегодня, ещё не прошло
        ("пятницу 10:00 ревью", dt(2026, 11, 20, 10, 0), "ревью"),  # сегодня прошло -> через неделю
    ],
)
def test_one_off(raw, when, text):
    parsed = parse_reminder(raw, NOW)
    assert parsed is not None, raw
    assert (parsed.when, parsed.text, parsed.repeat) == (when, text, None)


@pytest.mark.parametrize(
    ("raw", "when", "repeat"),
    [
        ("каждый день 8:00 витамины", dt(2026, 11, 14, 8, 0), DAILY),
        ("ежедневно в 21 дневник", dt(2026, 11, 13, 21, 0), DAILY),
        ("по будням 9:30 стендап", dt(2026, 11, 16, 9, 30), WEEKDAYS),  # пт 9:30 прошло -> пн
        ("каждую пятницу 18:00 отчёт", dt(2026, 11, 13, 18, 0), WEEKLY),
        ("каждое воскресенье уборка", dt(2026, 11, 15, 9, 0), WEEKLY),
    ],
)
def test_repeating(raw, when, repeat):
    parsed = parse_reminder(raw, NOW)
    assert parsed is not None, raw
    assert (parsed.when, parsed.repeat) == (when, repeat)


@pytest.mark.parametrize(
    "raw",
    [
        "просто текст",
        "через 10 минут",  # нет текста
        "18:30",
        "25:00 ошибка",
        "31.02 ошибка",
        "через 0 минут ноль",
        "13.11.2026 10:00 в прошлом",
    ],
)
def test_invalid(raw):
    assert parse_reminder(raw, NOW) is None


def test_weekdays_skip_weekend():
    saturday = dt(2026, 11, 14, 10, 0)
    assert next_occurrence(saturday, time(9, 30), WEEKDAYS) == dt(2026, 11, 16, 9, 30)


def test_next_occurrence_is_strictly_after():
    assert next_occurrence(dt(2026, 11, 13, 8, 0), time(8, 0), DAILY) == dt(2026, 11, 14, 8, 0)


def test_next_occurrence_keeps_local_time_across_dst():
    berlin = ZoneInfo("Europe/Berlin")
    before_switch = datetime(2026, 10, 24, 9, 0, tzinfo=berlin)  # переход 25.10
    after = next_occurrence(before_switch, time(9, 0), DAILY)
    assert after == datetime(2026, 10, 25, 9, 0, tzinfo=berlin)
    assert after.utcoffset() != before_switch.utcoffset()
