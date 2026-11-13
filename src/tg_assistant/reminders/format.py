import re
from datetime import datetime
from zoneinfo import ZoneInfo, available_timezones

from .timeparse import DAILY, WEEKDAYS, WEEKLY

_WD_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
_WD_EVERY = [
    "каждый понедельник",
    "каждый вторник",
    "каждую среду",
    "каждый четверг",
    "каждую пятницу",
    "каждую субботу",
    "каждое воскресенье",
]
_OFFSET = re.compile(r"^(?:utc|gmt)?\s*([+-])\s*(\d{1,2})$", re.IGNORECASE)
_ALIASES = {"мск": "Europe/Moscow", "москва": "Europe/Moscow", "msk": "Europe/Moscow"}


def format_when(when: datetime, now: datetime) -> str:
    """«пт 13.11 18:30» (год — только если не текущий). Оба аргумента в поясе пользователя."""
    date_part = f"{when:%d.%m}" if when.year == now.year else f"{when:%d.%m.%Y}"
    return f"{_WD_SHORT[when.weekday()]} {date_part} {when:%H:%M}"


def format_repeat(repeat: str | None, when: datetime) -> str:
    if repeat == DAILY:
        return "каждый день"
    if repeat == WEEKDAYS:
        return "по будням"
    if repeat == WEEKLY:
        return _WD_EVERY[when.weekday()]
    return ""


def parse_timezone(value: str) -> str | None:
    """Название пояса (Europe/Moscow, без учёта регистра), смещение (+3, UTC-5) или «мск»."""
    value = value.strip()
    if value.lower() in _ALIASES:
        return _ALIASES[value.lower()]
    if m := _OFFSET.match(value):
        hours = int(m[2])
        if hours == 0:
            return "UTC"
        if hours > 14:
            return None
        # В зонах Etc/GMT знак инвертирован: UTC+3 == Etc/GMT-3
        return f"Etc/GMT{'-' if m[1] == '+' else '+'}{hours}"
    lookup = {name.lower(): name for name in available_timezones()}
    name = lookup.get(value.lower())
    if name is None:
        return None
    ZoneInfo(name)
    return name
