"""Разбор времени напоминания из текста на русском.

Поддерживается:
- через 10 минут / через 2 часа / через полчаса / через час / через 3 дня / через неделю
- 18:30 текст            — сегодня, или завтра, если время уже прошло
- в 18 текст, в 18:30 текст
- сегодня / завтра / послезавтра [в] [ЧЧ:ММ]
- 25.12 [ЧЧ:ММ], 25.12.2026 [ЧЧ:ММ]
- [в] понедельник … воскресенье [ЧЧ:ММ] — ближайший такой день
- повторы: каждый день, ежедневно, по будням, каждый понедельник / каждую среду / …

Если указан день без времени, напоминание ставится на 9:00.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

DEFAULT_TIME = time(9, 0)

DAILY, WEEKDAYS, WEEKLY = "daily", "weekdays", "weekly"

_WEEKDAYS = {
    "понедельник": 0,
    "вторник": 1,
    "среда": 2,
    "среду": 2,
    "четверг": 3,
    "пятница": 4,
    "пятницу": 4,
    "суббота": 5,
    "субботу": 5,
    "воскресенье": 6,
}
_WD = "|".join(sorted(_WEEKDAYS, key=len, reverse=True))

_RELATIVE = re.compile(
    r"через\s+(?:(?P<half>пол)\s*(?P<half_unit>часа|минуты|дня)|(?:(?P<num>\d+)\s*)?"
    r"(?P<unit>минут[уы]?|мин|м|час(?:а|ов)?|ч|день|дн(?:я|ей)|д|недел[юиь]|нед))(?=\s|$|[,.:!-])",
    re.IGNORECASE,
)
_REPEAT = re.compile(
    rf"(?P<daily>каждый\s+день|ежедневно)|(?P<weekdays>по\s+будням)"
    rf"|(?:кажд(?:ый|ую|ое)\s+(?P<weekly>{_WD}))(?=\s|$)",
    re.IGNORECASE,
)
_DAY = re.compile(
    rf"(?P<word>сегодня|послезавтра|завтра)"
    rf"|(?:во?\s+)?(?P<weekday>{_WD})"
    r"|(?P<d>\d{1,2})\.(?P<m>\d{1,2})(?:\.(?P<y>\d{2}|\d{4}))?(?=\s|$)",
    re.IGNORECASE,
)
_TIME = re.compile(
    r"(?:в\s+)?(?P<h>\d{1,2}):(?P<min>\d{2})(?=\s|$)|в\s+(?P<h_only>\d{1,2})(?=\s|$)",
    re.IGNORECASE,
)

_UNITS = {"м": timedelta(minutes=1), "ч": timedelta(hours=1), "д": timedelta(days=1)}


@dataclass(frozen=True)
class ParsedReminder:
    when: datetime  # aware, в часовом поясе пользователя
    text: str
    repeat: str | None = None


def _match(pattern: re.Pattern[str], rest: str) -> tuple[re.Match[str] | None, str]:
    m = pattern.match(rest)
    return (m, rest[m.end() :].lstrip()) if m else (None, rest)


def _unit_delta(unit: str) -> timedelta:
    unit = unit.lower()
    if unit.startswith("нед"):
        return timedelta(weeks=1)
    if unit.startswith("мин") or unit == "м":
        return _UNITS["м"]
    if unit.startswith("час") or unit == "ч":
        return _UNITS["ч"]
    return _UNITS["д"]


def _clean_text(rest: str) -> str:
    return rest.lstrip(" ,.:;-—").strip()


def _parse_relative(rest: str, now: datetime) -> ParsedReminder | None:
    m, rest = _match(_RELATIVE, rest)
    if not m:
        return None
    if m["half"]:
        delta = _unit_delta(m["half_unit"]) / 2
    else:
        delta = _unit_delta(m["unit"]) * int(m["num"] or 1)
    if delta <= timedelta(0):
        return None
    return ParsedReminder(when=now + delta, text=_clean_text(rest))


def next_weekday(day: date, weekday: int) -> date:
    """Ближайшая дата с этим днём недели, начиная с `day` включительно."""
    return day + timedelta(days=(weekday - day.weekday()) % 7)


def next_occurrence(after: datetime, at: time, repeat: str, weekday: int | None = None) -> datetime:
    """Первый момент строго позже `after` для повторяющегося напоминания (в поясе `after`)."""
    tz = after.tzinfo
    day = after.date()
    for _ in range(8):
        candidate = datetime.combine(day, at, tzinfo=tz)
        ok = (
            repeat == DAILY
            or (repeat == WEEKDAYS and day.weekday() < 5)
            or (repeat == WEEKLY and day.weekday() == weekday)
        )
        if ok and candidate > after:
            return candidate
        day += timedelta(days=1)
    raise ValueError(f"Unknown repeat: {repeat}")


def parse_reminder(raw: str, now: datetime) -> ParsedReminder | None:
    """Разобрать «когда + текст». `now` — aware datetime в поясе пользователя."""
    rest = raw.strip()
    relative = _parse_relative(rest, now)
    if relative is not None:
        return relative if relative.text else None

    repeat_m, rest = _match(_REPEAT, rest)
    day_m, rest = (None, rest) if repeat_m else _match(_DAY, rest)
    time_m, rest = _match(_TIME, rest)
    text = _clean_text(rest)
    if not (repeat_m or day_m or time_m) or not text:
        return None

    try:
        if time_m:
            hour = int(time_m["h"] or time_m["h_only"])
            at = time(hour, int(time_m["min"] or 0))
        else:
            at = DEFAULT_TIME
    except ValueError:
        return None

    tz = now.tzinfo
    today = now.date()

    if repeat_m:
        if repeat_m["daily"]:
            repeat, weekday = DAILY, None
        elif repeat_m["weekdays"]:
            repeat, weekday = WEEKDAYS, None
        else:
            repeat, weekday = WEEKLY, _WEEKDAYS[repeat_m["weekly"].lower()]
        return ParsedReminder(
            when=next_occurrence(now, at, repeat, weekday), text=text, repeat=repeat
        )

    if day_m is None:
        when = datetime.combine(today, at, tzinfo=tz)
        if when <= now:
            when += timedelta(days=1)
        return ParsedReminder(when=when, text=text)

    if day_m["word"]:
        offset = {"сегодня": 0, "завтра": 1, "послезавтра": 2}[day_m["word"].lower()]
        day = today + timedelta(days=offset)
    elif day_m["weekday"]:
        day = next_weekday(today, _WEEKDAYS[day_m["weekday"].lower()])
        if datetime.combine(day, at, tzinfo=tz) <= now:
            day += timedelta(weeks=1)
    else:
        year = int(day_m["y"]) if day_m["y"] else today.year
        if year < 100:
            year += 2000
        try:
            day = date(year, int(day_m["m"]), int(day_m["d"]))
        except ValueError:
            return None
        if not day_m["y"] and datetime.combine(day, at, tzinfo=tz) <= now:
            try:
                day = day.replace(year=year + 1)
            except ValueError:  # 29.02
                return None

    when = datetime.combine(day, at, tzinfo=tz)
    if when <= now:
        return None
    return ParsedReminder(when=when, text=text)
