"""Parsing of user queries, public Telegram links, and date filters."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

# Public usernames: 5–32 chars, start with a letter, then letters/digits/underscore.
USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")

# Paths that are Telegram features, not public usernames.
_RESERVED = (
    "s",
    "c",
    "a",
    "iv",
    "share",
    "socks",
    "proxy",
    "joinchat",
    "addstickers",
    "addemoji",
    "addtheme",
    "setemoji",
    "login",
    "confirmphone",
    "invoice",
    "boost",
    "giftcode",
)
_RESERVED_ALT = "|".join(_RESERVED)

# t.me / telegram.me / telegram.dog public links. Invites (+hash, joinchat) and
# internal /c/<id> links are ignored — those are not public usernames.
TME_LINK_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:t(?:elegram)?\.me|telegram\.dog)/"
    r"(?:s/)?"
    rf"(?!(?:{_RESERVED_ALT})(?:/|$))"
    r"(?P<user>[A-Za-z][A-Za-z0-9_]{4,31})(?:/(?P<msg>\d+))?",
    re.IGNORECASE,
)

INVITE_OR_PRIVATE_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:t(?:elegram)?\.me|telegram\.dog)/"
    r"(?:c/\d+|\+[\w-]+|joinchat/[\w-]+)",
    re.IGNORECASE,
)

FROM_RE = re.compile(r"(?i)(?:^|\s)(?:from|since):(?P<date>\d{4}-\d{2}-\d{2})(?=\s|$)")
TO_RE = re.compile(r"(?i)(?:^|\s)(?:to|until|till):(?P<date>\d{4}-\d{2}-\d{2})(?=\s|$)")
LAST_RE = re.compile(r"(?i)(?:^|\s)last:(?P<num>\d+)(?P<unit>[hdw])(?=\s|$)")
IN_RE = re.compile(r"(?i)(?:^|\s)in:(?P<ref>@?[A-Za-z][A-Za-z0-9_]{4,31}|https?://\S+)(?=\s|$)")
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")

MIN_QUERY_LEN = 2
MAX_QUERY_LEN = 120


class ParseError(ValueError):
    """User-facing parse error."""


@dataclass(frozen=True)
class DateRange:
    start: datetime | None = None
    end: datetime | None = None

    def contains(self, when: datetime | None) -> bool:
        if when is None:
            return True
        instant = _as_utc(when)
        if self.start and instant < _as_utc(self.start):
            return False
        if self.end and instant > _as_utc(self.end):
            return False
        return True

    def is_empty(self) -> bool:
        return self.start is None and self.end is None


@dataclass(frozen=True)
class SearchQuery:
    text: str
    date_range: DateRange = field(default_factory=DateRange)
    channels: tuple[str, ...] = ()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def parse_date(value: str, *, end_of_day: bool = False) -> datetime:
    match = DATE_RE.match(value.strip())
    if not match:
        raise ParseError(f"Некорректная дата: {value}. Ожидается YYYY-MM-DD.")
    year, month, day = (int(p) for p in match.groups())
    try:
        if end_of_day:
            return datetime(year, month, day, 23, 59, 59, tzinfo=UTC)
        return datetime(year, month, day, 0, 0, 0, tzinfo=UTC)
    except ValueError as exc:
        raise ParseError(f"Некорректная дата: {value}.") from exc


def parse_last_window(num: int, unit: str, *, now: datetime | None = None) -> DateRange:
    if num <= 0:
        raise ParseError("Интервал last: должен быть больше нуля.")
    unit = unit.lower()
    if unit == "h":
        delta = timedelta(hours=num)
    elif unit == "d":
        delta = timedelta(days=num)
    elif unit == "w":
        delta = timedelta(weeks=num)
    else:
        raise ParseError("Единица last: должна быть h, d или w (например last:7d).")
    current = _as_utc(now or datetime.now(UTC))
    return DateRange(start=current - delta, end=current)


def normalize_username(value: str) -> str | None:
    """Return a public username without @, or None if the value is not public."""
    raw = value.strip()
    if not raw:
        return None
    if INVITE_OR_PRIVATE_RE.search(raw) and not TME_LINK_RE.search(raw):
        return None
    link = TME_LINK_RE.search(raw)
    if link:
        candidate = link.group("user")
    else:
        candidate = raw[1:] if raw.startswith("@") else raw
        # Bare paths like "t.me/name"
        if "/" in candidate:
            return None
    if candidate.lower() in {item.lower() for item in _RESERVED}:
        return None
    if not USERNAME_RE.match(candidate):
        return None
    return candidate


def extract_tme_usernames(text: str) -> list[str]:
    """Unique public usernames mentioned via @handle or t.me links, original order."""
    found: list[str] = []
    seen: set[str] = set()

    def add(name: str | None) -> None:
        if not name:
            return
        key = name.lower()
        if key not in seen:
            seen.add(key)
            found.append(name)

    if not text:
        return found
    for match in TME_LINK_RE.finditer(text):
        add(normalize_username(match.group("user")))
    for match in re.finditer(r"@([A-Za-z][A-Za-z0-9_]{4,31})", text):
        add(normalize_username(match.group(1)))
    return found


def extract_message_link(text: str) -> tuple[str, int] | None:
    """Return (username, message_id) if the text is a public post link."""
    match = TME_LINK_RE.search(text or "")
    if not match or not match.group("msg"):
        return None
    username = normalize_username(match.group("user"))
    if not username:
        return None
    return username, int(match.group("msg"))


def public_post_url(username: str | None, message_id: int) -> str | None:
    name = normalize_username(username or "")
    if not name or message_id <= 0:
        return None
    return f"https://t.me/{name}/{message_id}"


def _strip_tokens(text: str, matches: Iterable[re.Match[str]]) -> str:
    spans = [(m.start(), m.end()) for m in matches]
    if not spans:
        return text
    parts: list[str] = []
    cursor = 0
    for start, end in spans:
        parts.append(text[cursor:start])
        cursor = end
    parts.append(text[cursor:])
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def parse_search_query(raw: str, *, now: datetime | None = None) -> SearchQuery:
    text = (raw or "").strip()
    if not text:
        raise ParseError(
            "Укажите ключевые слова. Пример: /search imtrtd from:2024-01-01 to:2024-06-01"
        )

    last_match = LAST_RE.search(text)
    from_match = FROM_RE.search(text)
    to_match = TO_RE.search(text)
    in_matches = list(IN_RE.finditer(text))

    date_range = DateRange()
    if last_match:
        if from_match or to_match:
            raise ParseError("Не смешивайте last: с from:/to:. Выберите один способ фильтра дат.")
        date_range = parse_last_window(
            int(last_match.group("num")), last_match.group("unit"), now=now
        )
    else:
        start = parse_date(from_match.group("date")) if from_match else None
        end = parse_date(to_match.group("date"), end_of_day=True) if to_match else None
        if start and end and start > end:
            raise ParseError("Дата from: не может быть позже to:.")
        date_range = DateRange(start=start, end=end)

    channels: list[str] = []
    seen_ch: set[str] = set()
    for match in in_matches:
        name = normalize_username(match.group("ref"))
        if not name:
            raise ParseError(
                "in: принимает только публичный @username или ссылку t.me/username, "
                f"не «{match.group('ref')}»."
            )
        key = name.lower()
        if key not in seen_ch:
            seen_ch.add(key)
            channels.append(name)

    leftover = text
    leftover = _strip_tokens(leftover, [m for m in (last_match, from_match, to_match) if m])
    leftover = _strip_tokens(leftover, in_matches)
    leftover = leftover.strip()
    if len(leftover) < MIN_QUERY_LEN:
        raise ParseError("Слишком короткий запрос. Нужно минимум 2 символа ключевых слов.")
    if len(leftover) > MAX_QUERY_LEN:
        raise ParseError(f"Слишком длинный запрос (максимум {MAX_QUERY_LEN} символов).")
    return SearchQuery(text=leftover, date_range=date_range, channels=tuple(channels))


def parse_channel_ref(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        raise ParseError(
            "Укажите публичный канал: /channel @username или /channel https://t.me/username"
        )
    if INVITE_OR_PRIVATE_RE.search(text):
        raise ParseError(
            "Принимаются только публичные каналы и группы с username, не инвайт-ссылки."
        )
    name = normalize_username(text)
    if not name:
        raise ParseError(
            "Не удалось разобрать ссылку. Нужен публичный @username или https://t.me/username."
        )
    return name


def normalize_watch_term(raw: str) -> str:
    term = re.sub(r"\s+", " ", (raw or "").strip())
    if len(term) < MIN_QUERY_LEN:
        raise ParseError("Слишком короткое выражение для мониторинга. Минимум 2 символа.")
    if len(term) > MAX_QUERY_LEN:
        raise ParseError(f"Слишком длинное выражение (максимум {MAX_QUERY_LEN} символов).")
    return term


def snippet(text: str | None, term: str | None = None, limit: int = 240) -> str:
    compact = re.sub(r"\s+", " ", (text or "").strip())
    if not compact:
        return "— без текста —"
    if term:
        lowered = compact.lower()
        needle = term.lower().strip()
        pos = lowered.find(needle) if needle else -1
        if pos > 40:
            start = max(0, pos - 40)
            compact = ("…" if start else "") + compact[start:]
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"
