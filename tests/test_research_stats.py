from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from tg_assistant.research.stats import (
    compute_channel_stats,
    extract_forward_source,
    extract_mentioned_channels,
)


def _dt(day: int, hour: int = 12) -> datetime:
    return datetime(2024, 6, day, hour, 0, tzinfo=UTC)


def _msg(*, day: int, views=None, text="", fwd=None, hour: int = 12, forward=None):
    return SimpleNamespace(
        id=day,
        date=_dt(day, hour),
        views=views,
        message=text,
        fwd_from=fwd,
        forward=forward,
        entities=[],
    )


def test_frequency_views_and_forwards():
    now = _dt(10)
    messages = [
        _msg(day=1, views=100, text="hello https://t.me/Alpha"),
        _msg(day=2, views=200, text="ping @BetaOS and t.me/Alpha/3"),
        _msg(
            day=9,
            views=300,
            text="forwarded",
            forward=SimpleNamespace(
                chat=SimpleNamespace(username="Gamma", title="Gamma News"),
                sender=None,
            ),
        ),
        _msg(
            day=10,
            views=400,
            text="see https://t.me/BetaOS/9",
            fwd=SimpleNamespace(from_name="Gamma News", from_id=None),
        ),
    ]
    stats = compute_channel_stats(messages, now=now, top_n=5)

    assert stats.posts_analyzed == 4
    # span from day 1 12:00 to day 10 12:00 = 9 days, 4 posts
    assert abs(stats.span_days - 9.0) < 1e-9
    assert stats.posts_per_day == round(4 / 9.0, 2)
    assert stats.posts_last_7d == 2  # days 9 and 10
    assert stats.average_views == 250.0
    assert stats.views_sample == 4
    assert stats.top_forward_sources[0] == ("@Gamma", 1)
    # Second forward falls back to from_name
    assert ("Gamma News", 1) in stats.top_forward_sources
    mentioned = dict(stats.mentioned_channels)
    assert mentioned["@Alpha"] == 2
    assert mentioned["@BetaOS"] == 2
    assert mentioned["@Gamma"] == 1


def test_empty_history():
    stats = compute_channel_stats([])
    assert stats.posts_analyzed == 0
    assert stats.average_views is None
    assert stats.top_forward_sources == []
    assert stats.mentioned_channels == []


def test_same_second_burst_uses_minimum_span():
    same = _dt(1, 0)
    messages = [
        SimpleNamespace(
            date=same, views=None, message="", fwd_from=None, forward=None, entities=[]
        ),
        SimpleNamespace(
            date=same, views=None, message="", fwd_from=None, forward=None, entities=[]
        ),
    ]
    stats = compute_channel_stats(messages, now=same)
    assert stats.span_days == 1.0 / 24.0
    assert stats.posts_per_day == round(2 / (1.0 / 24.0), 2)
    assert stats.average_views is None


def test_forward_source_skips_numeric_user_id():
    message = SimpleNamespace(
        forward=None,
        fwd_from=SimpleNamespace(
            from_name=None,
            from_id=SimpleNamespace(channel_id=None, user_id=42, chat_id=None),
        ),
    )
    assert extract_forward_source(message) is None


def test_forward_source_peer_id_fallback():
    message = SimpleNamespace(
        forward=None,
        fwd_from=SimpleNamespace(
            from_name=None,
            from_id=SimpleNamespace(channel_id=777, user_id=None, chat_id=None),
        ),
    )
    assert extract_forward_source(message) == "channel:777"


def test_mentions_ignore_invite_links():
    message = SimpleNamespace(
        message="private https://t.me/+SecretHash and https://t.me/joinchat/AAAA public https://t.me/OpenChan",
        fwd_from=None,
        forward=None,
        entities=[],
    )
    assert extract_mentioned_channels(message) == ["OpenChan"]


def test_entity_text_url_is_collected():
    message = SimpleNamespace(
        message="click here",
        fwd_from=None,
        forward=None,
        entities=[SimpleNamespace(url="https://t.me/LinkedChan/4", user=None)],
    )
    assert extract_mentioned_channels(message) == ["LinkedChan"]


def test_posts_last_7d_boundary():
    now = datetime(2024, 6, 10, 12, tzinfo=UTC)
    messages = [
        SimpleNamespace(
            date=now - timedelta(days=7, seconds=1),
            views=1,
            message="",
            fwd_from=None,
            forward=None,
            entities=[],
        ),
        SimpleNamespace(
            date=now - timedelta(days=7),
            views=1,
            message="",
            fwd_from=None,
            forward=None,
            entities=[],
        ),
    ]
    stats = compute_channel_stats(messages, now=now)
    assert stats.posts_last_7d == 1
