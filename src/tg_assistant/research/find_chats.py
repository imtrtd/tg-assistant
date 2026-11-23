from __future__ import annotations

from typing import Any

from telethon import TelegramClient
from telethon.tl.functions.contacts import SearchRequest as ContactsSearchRequest
from telethon.tl.functions.messages import SearchGlobalRequest
from telethon.tl.types import InputMessagesFilterEmpty, InputPeerEmpty, Message

from .config import ResearchConfig
from .flood import call_with_flood_wait
from .parse import SearchQuery


def _kind_of(chat: Any) -> str | None:
    if getattr(chat, "broadcast", False):
        return "канал"
    if getattr(chat, "megagroup", False) or getattr(chat, "gigagroup", False):
        return "супергруппа"
    name = type(chat).__name__
    if name == "Chat":
        return "группа"
    if name == "Channel":
        return "канал"
    return None


def _chat_card(chat: Any) -> dict | None:
    username = getattr(chat, "username", None)
    if not username:
        return None
    kind = _kind_of(chat)
    if kind is None:
        return None
    participants = getattr(chat, "participants_count", None) or getattr(
        chat, "subscribers_count", None
    )
    return {
        "id": int(chat.id),
        "username": str(username),
        "title": getattr(chat, "title", None) or str(username),
        "kind": kind,
        "participants": participants,
        "about": None,
    }


def _merge_chats(cards: list[dict], limit: int) -> list[dict]:
    seen: set[str] = set()
    merged: list[dict] = []
    for card in cards:
        key = card["username"].lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(card)
        if len(merged) >= limit:
            break
    return merged


async def find_chats(
    client: TelegramClient,
    topic: str,
    config: ResearchConfig,
) -> list[dict]:
    query = topic.strip()

    async def contacts_call() -> Any:
        return await client(ContactsSearchRequest(q=query, limit=config.find_limit))

    contacts = await call_with_flood_wait(
        contacts_call,
        retries=config.flood_retries,
        max_wait=config.flood_max_wait_seconds,
        label="contacts.search",
    )

    cards: list[dict] = []
    for chat in getattr(contacts, "chats", None) or []:
        card = _chat_card(chat)
        if card:
            cards.append(card)

    search_query = SearchQuery(text=query)

    async def global_call() -> Any:
        return await client(
            SearchGlobalRequest(
                q=search_query.text,
                filter=InputMessagesFilterEmpty(),
                min_date=0,
                max_date=0,
                offset_rate=0,
                offset_peer=InputPeerEmpty(),
                offset_id=0,
                limit=config.find_limit,
            )
        )

    global_result = await call_with_flood_wait(
        global_call,
        retries=config.flood_retries,
        max_wait=config.flood_max_wait_seconds,
        label="find_global",
    )
    for chat in getattr(global_result, "chats", None) or []:
        card = _chat_card(chat)
        if card:
            cards.append(card)

    # Also pick up channels that only appear as the peer of a matching public post.
    chats_by_id = {
        int(chat.id): chat
        for chat in getattr(global_result, "chats", None) or []
        if getattr(chat, "id", None) is not None
    }
    for message in getattr(global_result, "messages", None) or []:
        if not isinstance(message, Message):
            continue
        peer = getattr(message, "peer_id", None)
        channel_id = getattr(peer, "channel_id", None) if peer is not None else None
        if channel_id and int(channel_id) in chats_by_id:
            card = _chat_card(chats_by_id[int(channel_id)])
            if card:
                cards.append(card)

    return _merge_chats(cards, config.find_limit)
