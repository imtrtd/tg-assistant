from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from telethon import TelegramClient
from telethon.tl.functions.messages import SearchGlobalRequest, SearchRequest
from telethon.tl.types import InputMessagesFilterEmpty, InputPeerEmpty, Message

from .config import ResearchConfig
from .flood import call_with_flood_wait
from .parse import SearchQuery, public_post_url, snippet

logger = logging.getLogger(__name__)


def _unix(value: datetime | None) -> int:
    if value is None:
        return 0
    return int(value.timestamp())


def _peer_id(message: Message) -> int:
    peer = getattr(message, "peer_id", None)
    if peer is None:
        return int(getattr(message, "chat_id", 0) or 0)
    for attr in ("channel_id", "chat_id", "user_id"):
        value = getattr(peer, attr, None)
        if value:
            return int(value)
    return int(getattr(message, "chat_id", 0) or 0)


def _chat_username(chat: Any) -> str | None:
    username = getattr(chat, "username", None)
    return str(username) if username else None


def _chat_title(chat: Any) -> str | None:
    return getattr(chat, "title", None) or getattr(chat, "first_name", None)


def message_to_hit(message: Message, chat: Any, term: str | None = None) -> dict | None:
    username = _chat_username(chat)
    # Only return results that can be linked as a public post.
    if not username:
        return None
    msg_id = int(message.id)
    url = public_post_url(username, msg_id)
    if not url:
        return None
    return {
        "peer_id": _peer_id(message),
        "message_id": msg_id,
        "username": username,
        "title": _chat_title(chat) or username,
        "date": message.date,
        "url": url,
        "snippet": snippet(getattr(message, "message", None) or "", term),
        "views": getattr(message, "views", None),
    }


def _chats_by_id(messages: Any) -> dict[int, Any]:
    mapping: dict[int, Any] = {}
    for chat in getattr(messages, "chats", None) or []:
        chat_id = getattr(chat, "id", None)
        if chat_id is not None:
            mapping[int(chat_id)] = chat
    return mapping


def _iter_result_messages(result: Any) -> Iterable[Message]:
    for item in getattr(result, "messages", None) or []:
        if isinstance(item, Message):
            yield item


async def search_global(
    client: TelegramClient,
    query: SearchQuery,
    config: ResearchConfig,
) -> tuple[list[Message], Any]:
    async def _call() -> Any:
        return await client(
            SearchGlobalRequest(
                q=query.text,
                filter=InputMessagesFilterEmpty(),
                min_date=_unix(query.date_range.start),
                max_date=_unix(query.date_range.end),
                offset_rate=0,
                offset_peer=InputPeerEmpty(),
                offset_id=0,
                limit=config.search_limit,
            )
        )

    result = await call_with_flood_wait(
        _call,
        retries=config.flood_retries,
        max_wait=config.flood_max_wait_seconds,
        label="search_global",
    )
    return list(_iter_result_messages(result)), result


async def search_in_channel(
    client: TelegramClient,
    query: SearchQuery,
    channel: Any,
    config: ResearchConfig,
) -> tuple[list[Message], Any]:
    async def _call() -> Any:
        return await client(
            SearchRequest(
                peer=channel,
                q=query.text,
                filter=InputMessagesFilterEmpty(),
                min_date=_unix(query.date_range.start),
                max_date=_unix(query.date_range.end),
                offset_id=0,
                add_offset=0,
                limit=config.search_limit,
                max_id=0,
                min_id=0,
                hash=0,
            )
        )

    result = await call_with_flood_wait(
        _call,
        retries=config.flood_retries,
        max_wait=config.flood_max_wait_seconds,
        label=f"search_channel:{getattr(channel, 'username', channel)}",
    )
    return list(_iter_result_messages(result)), result


def _merge_hits(hits: list[dict], limit: int) -> list[dict]:
    seen: set[tuple[int, int]] = set()
    merged: list[dict] = []
    for hit in hits:
        key = (int(hit["peer_id"]), int(hit["message_id"]))
        if key in seen:
            continue
        seen.add(key)
        merged.append(hit)
        if len(merged) >= limit:
            break
    return merged


async def search_posts(
    client: TelegramClient,
    query: SearchQuery,
    config: ResearchConfig,
) -> list[dict]:
    hits: list[dict] = []

    if not query.channels:
        messages, result = await search_global(client, query, config)
        chats = _chats_by_id(result)
        for message in messages:
            chat = chats.get(_peer_id(message)) or await _safe_get_chat(client, message)
            hit = message_to_hit(message, chat, query.text)
            if hit and query.date_range.contains(hit.get("date")):
                hits.append(hit)
        return _merge_hits(hits, config.search_limit)

    for username in query.channels:
        entity = await resolve_public_chat(client, username, config)
        messages, result = await search_in_channel(client, query, entity, config)
        chats = _chats_by_id(result)
        fallback = entity
        for message in messages:
            chat = chats.get(_peer_id(message)) or fallback
            hit = message_to_hit(message, chat, query.text)
            if hit and query.date_range.contains(hit.get("date")):
                hits.append(hit)
    return _merge_hits(hits, config.search_limit)


async def _safe_get_chat(client: TelegramClient, message: Message) -> Any | None:
    try:
        return await message.get_chat()
    except Exception as exc:  # noqa: BLE001 — best-effort enrichment
        logger.debug("Could not resolve chat for message %s: %s", message.id, exc)
        return None


async def resolve_public_chat(client: TelegramClient, username: str, config: ResearchConfig) -> Any:
    async def _call() -> Any:
        return await client.get_entity(username)

    entity = await call_with_flood_wait(
        _call,
        retries=config.flood_retries,
        max_wait=config.flood_max_wait_seconds,
        label=f"get_entity:{username}",
    )
    if not getattr(entity, "username", None):
        raise ValueError("Это не публичный канал или группа с username.")
    is_channel = (
        type(entity).__name__ in {"Channel", "Chat"}
        or getattr(entity, "broadcast", False)
        or getattr(entity, "megagroup", False)
    )
    # Reject personal user accounts: this bot researches public channels/chats only.
    if type(entity).__name__ == "User":
        raise ValueError("Укажите публичный канал или группу, не личный аккаунт.")
    if not is_channel and type(entity).__name__ not in {"Channel", "Chat"}:
        raise ValueError("Укажите публичный канал или группу.")
    return entity
