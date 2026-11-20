"""Pure statistics over a list of public channel posts (no network I/O)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from .parse import extract_tme_usernames, normalize_username


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _username_of(entity: Any) -> str | None:
    if entity is None:
        return None
    username = getattr(entity, "username", None)
    if username:
        return normalize_username(str(username))
    return None


def _title_of(entity: Any) -> str | None:
    if entity is None:
        return None
    for attr in ("title", "first_name"):
        value = getattr(entity, attr, None)
        if value:
            return str(value)
    return None


def extract_forward_source(message: Any) -> str | None:
    """Best public label for the source of a forwarded post."""
    forward = getattr(message, "forward", None)
    if forward is not None:
        chat = getattr(forward, "chat", None)
        name = _username_of(chat)
        if name:
            return f"@{name}"
        title = _title_of(chat)
        if title:
            return title
        sender = getattr(forward, "sender", None)
        name = _username_of(sender)
        if name:
            return f"@{name}"
        title = _title_of(sender)
        if title:
            return title

    fwd = getattr(message, "fwd_from", None)
    if fwd is None:
        return None
    from_name = getattr(fwd, "from_name", None)
    if from_name:
        return str(from_name)
    from_id = getattr(fwd, "from_id", None)
    if from_id is not None:
        channel_id = getattr(from_id, "channel_id", None)
        if channel_id:
            return f"channel:{channel_id}"
        # Числовой id человека не показываем: это не публичный источник.
        chat_id = getattr(from_id, "chat_id", None)
        if chat_id:
            return f"chat:{chat_id}"
    return None


def extract_mentioned_channels(message: Any, extra_usernames: Iterable[str] = ()) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()

    def add(raw: str | None) -> None:
        name = normalize_username(raw or "")
        if not name:
            return
        key = name.lower()
        if key not in seen:
            seen.add(key)
            names.append(name)

    text = getattr(message, "message", None) or getattr(message, "raw_text", None) or ""
    for name in extract_tme_usernames(str(text)):
        add(name)
    for name in extra_usernames:
        add(name)

    for entity in getattr(message, "entities", None) or []:
        url = getattr(entity, "url", None)
        if url:
            for name in extract_tme_usernames(str(url)):
                add(name)
        mention = getattr(entity, "user", None)
        add(_username_of(mention) or "")

    forward_source = extract_forward_source(message)
    if forward_source and forward_source.startswith("@"):
        add(forward_source)
    return names


@dataclass
class ChannelStats:
    posts_analyzed: int = 0
    span_days: float = 0.0
    posts_per_day: float = 0.0
    posts_last_7d: int = 0
    average_views: float | None = None
    views_sample: int = 0
    top_forward_sources: list[tuple[str, int]] = field(default_factory=list)
    mentioned_channels: list[tuple[str, int]] = field(default_factory=list)
    first_post_date: datetime | None = None
    last_post_date: datetime | None = None


def compute_channel_stats(
    messages: Iterable[Any],
    *,
    now: datetime | None = None,
    top_n: int = 8,
) -> ChannelStats:
    posts = list(messages)
    stats = ChannelStats(posts_analyzed=len(posts))
    if not posts:
        return stats

    current = _as_utc(now or datetime.now(UTC))
    dates = [_as_utc(m.date) for m in posts if getattr(m, "date", None) is not None]
    if dates:
        stats.first_post_date = min(dates)
        stats.last_post_date = max(dates)
        span = (stats.last_post_date - stats.first_post_date).total_seconds()
        # Guard against a burst of posts in one second.
        stats.span_days = max(span / 86400.0, 1.0 / 24.0)
        stats.posts_per_day = round(len(dates) / stats.span_days, 2)
        week_ago = current - timedelta(days=7)
        stats.posts_last_7d = sum(1 for d in dates if d >= week_ago)

    views = [int(m.views) for m in posts if getattr(m, "views", None) is not None]
    if views:
        stats.views_sample = len(views)
        stats.average_views = round(sum(views) / len(views), 1)

    forwards: Counter[str] = Counter()
    mentions: Counter[str] = Counter()
    for message in posts:
        source = extract_forward_source(message)
        if source:
            forwards[source] += 1
        for name in extract_mentioned_channels(message):
            mentions[f"@{name}"] += 1

    stats.top_forward_sources = forwards.most_common(top_n)
    stats.mentioned_channels = mentions.most_common(top_n)
    return stats
