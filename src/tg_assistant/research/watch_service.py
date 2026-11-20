"""Периодический поиск упоминаний и отбор только новых публичных постов."""

import logging
from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession
from telethon import TelegramClient

from .config import ResearchConfig
from .dedupe import PostRef, filter_new_posts
from .parse import SearchQuery
from .search_posts import search_posts
from .store import Watch, mark_seen, seen_keys

logger = logging.getLogger(__name__)


def apply_watch_hits(
    watch: Watch,
    hits: list[dict],
    already_seen: set[tuple[int, int]],
    *,
    baseline: bool,
) -> tuple[list[dict], list[tuple[int, int]]]:
    """Вернуть (алерты, ключи для записи).

    Первый проход (baseline) только запоминает уже существующие совпадения и ничего
    не рассылает. Дальше алерт уходит по постам, которых ещё не было.
    """
    refs = [PostRef(peer_id=int(hit["peer_id"]), message_id=int(hit["message_id"])) for hit in hits]
    fresh_refs = filter_new_posts(already_seen, refs)
    keys = [(item.peer_id, item.message_id) for item in fresh_refs]
    if baseline:
        return [], keys
    fresh_keys = set(keys)
    alerts = [hit for hit in hits if (int(hit["peer_id"]), int(hit["message_id"])) in fresh_keys]
    return alerts, keys


async def collect_new_hits(
    client: TelegramClient,
    session: AsyncSession,
    watches: list[Watch],
    config: ResearchConfig,
) -> list[tuple[Watch, dict]]:
    """Один поиск на уникальное выражение, затем новые посты каждому наблюдению."""
    if not watches:
        return []

    by_term: dict[str, list[Watch]] = defaultdict(list)
    for watch in watches:
        by_term[watch.term.casefold()].append(watch)

    alerts: list[tuple[Watch, dict]] = []
    for group in by_term.values():
        term = group[0].term
        try:
            hits = await search_posts(client, SearchQuery(text=term), config)
        except Exception:
            logger.exception("Watch search failed for term %r", term)
            continue
        for watch in group:
            already = await seen_keys(session, watch.id)
            to_alert, to_mark = apply_watch_hits(watch, hits, already, baseline=len(already) == 0)
            for peer_id, message_id in to_mark:
                await mark_seen(session, watch.id, peer_id, message_id)
            alerts.extend((watch, hit) for hit in to_alert)
    return alerts
