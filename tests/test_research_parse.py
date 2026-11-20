from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tg_assistant.research.parse import (
    ParseError,
    extract_message_link,
    extract_tme_usernames,
    normalize_username,
    normalize_watch_term,
    parse_channel_ref,
    parse_search_query,
    public_post_url,
    snippet,
)


def test_parse_keywords_only():
    query = parse_search_query("  imtrtd shell  ")
    assert query.text == "imtrtd shell"
    assert query.date_range.is_empty()
    assert query.channels == ()


def test_parse_from_to_range():
    query = parse_search_query("brand from:2024-01-01 to:2024-01-31")
    assert query.text == "brand"
    assert query.date_range.start == datetime(2024, 1, 1, tzinfo=UTC)
    assert query.date_range.end == datetime(2024, 1, 31, 23, 59, 59, tzinfo=UTC)
    assert query.date_range.contains(datetime(2024, 1, 15, tzinfo=UTC))
    assert not query.date_range.contains(datetime(2023, 12, 31, tzinfo=UTC))
    assert not query.date_range.contains(datetime(2024, 2, 1, tzinfo=UTC))


def test_parse_since_until_aliases():
    query = parse_search_query("osint since:2024-05-01 until:2024-05-02")
    assert query.text == "osint"
    assert query.date_range.start.day == 1
    assert query.date_range.end.day == 2


def test_parse_last_window():
    now = datetime(2024, 6, 10, 12, 0, tzinfo=UTC)
    query = parse_search_query("mention last:7d", now=now)
    assert query.text == "mention"
    assert query.date_range.start == datetime(2024, 6, 3, 12, 0, tzinfo=UTC)
    assert query.date_range.end == now


def test_parse_last_hours_and_weeks():
    now = datetime(2024, 1, 8, tzinfo=UTC)
    hours = parse_search_query("xx last:24h", now=now)
    weeks = parse_search_query("xx last:2w", now=now)
    assert (now - hours.date_range.start).total_seconds() == 24 * 3600
    assert (now - weeks.date_range.start).days == 14


def test_parse_in_channel_and_link():
    query = parse_search_query("news in:@OpenNews in:https://t.me/durov")
    assert query.text == "news"
    assert query.channels == ("OpenNews", "durov")


def test_parse_rejects_mixed_date_filters():
    with pytest.raises(ParseError, match="Не смешивайте"):
        parse_search_query("x last:7d from:2024-01-01")


def test_parse_rejects_inverted_range():
    with pytest.raises(ParseError, match="не может быть позже"):
        parse_search_query("x from:2024-06-02 to:2024-06-01")


def test_parse_rejects_short_or_empty():
    with pytest.raises(ParseError):
        parse_search_query("")
    with pytest.raises(ParseError, match="короткий"):
        parse_search_query("from:2024-01-01")
    with pytest.raises(ParseError, match="короткий"):
        parse_search_query("a last:1d")


def test_parse_rejects_invite_in_filter():
    with pytest.raises(ParseError, match="публичный"):
        parse_search_query("news in:https://t.me/+AbCdEf")


def test_normalize_username_variants():
    assert normalize_username("@OpenNews") == "OpenNews"
    assert normalize_username("https://t.me/OpenNews") == "OpenNews"
    assert normalize_username("https://t.me/s/OpenNews/15") == "OpenNews"
    assert normalize_username("https://telegram.me/OpenNews") == "OpenNews"
    assert normalize_username("https://t.me/+secret") is None
    assert normalize_username("https://t.me/joinchat/AAAA") is None
    assert normalize_username("https://t.me/c/1234567890/1") is None
    assert normalize_username("ab") is None
    assert normalize_username("1channel") is None


def test_parse_channel_ref():
    assert parse_channel_ref("https://t.me/s/PublicChat") == "PublicChat"
    with pytest.raises(ParseError, match="инвайт"):
        parse_channel_ref("https://t.me/joinchat/abc")
    with pytest.raises(ParseError):
        parse_channel_ref("")


def test_extract_tme_usernames_unique_order():
    text = "See https://t.me/Alpha/10 and @BetaOS plus t.me/alpha again and @Alpha"
    assert extract_tme_usernames(text) == ["Alpha", "BetaOS"]


def test_extract_message_link_and_public_url():
    assert extract_message_link("https://t.me/OpenNews/42") == ("OpenNews", 42)
    assert extract_message_link("https://t.me/OpenNews") is None
    assert public_post_url("OpenNews", 42) == "https://t.me/OpenNews/42"
    assert public_post_url("https://t.me/+x", 1) is None


def test_watch_term_normalization():
    assert normalize_watch_term("  brand   name  ") == "brand name"
    with pytest.raises(ParseError):
        normalize_watch_term("x")


def test_snippet_centers_on_term():
    text = "AAAA " + ("word " * 40) + "NEEDLE in the haystack " + ("tail " * 20)
    result = snippet(text, "needle", limit=80)
    assert "NEEDLE" in result
    assert result.startswith("…")
    assert len(result) <= 80
