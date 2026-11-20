from __future__ import annotations

import logging
from typing import Any

from telethon import TelegramClient
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import Channel, Chat, Message

from .config import ResearchConfig
from .flood import call_with_flood_wait
from .search_posts import resolve_public_chat
from .stats import ChannelStats, compute_channel_stats

logger = logging.getLogger(__name__)


def _kind_of(entity: Any) -> str:
    if getattr(entity, "broadcast", False):
        return "канал"
    if getattr(entity, "megagroup", False) or getattr(entity, "gigagroup", False):
        return "супергруппа"
    if isinstance(entity, Chat):
        return "группа"
    return "канал"


async def fetch_channel_summary(
    client: TelegramClient,
    username: str,
    config: ResearchConfig,
) -> tuple[dict, ChannelStats]:
    entity = await resolve_public_chat(client, username, config)

    full = None
    about = None
    participants = getattr(entity, "participants_count", None)
    linked_username = None

    if isinstance(entity, Channel):

        async def full_call() -> Any:
            return await client(GetFullChannelRequest(entity))

        try:
            full = await call_with_flood_wait(
                full_call,
                retries=config.flood_retries,
                max_wait=config.flood_max_wait_seconds,
                label=f"full_channel:{username}",
            )
        except Exception:
            logger.exception("GetFullChannel failed for %s", username)
            full = None

        if full is not None:
            full_chat = getattr(full, "full_chat", None)
            about = getattr(full_chat, "about", None) or about
            participants = getattr(full_chat, "participants_count", None) or participants
            linked_id = getattr(full_chat, "linked_chat_id", None)
            if linked_id:
                for chat in getattr(full, "chats", None) or []:
                    if getattr(chat, "id", None) == linked_id and getattr(chat, "username", None):
                        linked_username = str(chat.username)
                        break

    messages: list[Message] = []

    async def history() -> list[Message]:
        collected: list[Message] = []
        async for message in client.iter_messages(entity, limit=config.channel_history_limit):
            if isinstance(message, Message):
                collected.append(message)
        return collected

    try:
        messages = await call_with_flood_wait(
            history,
            retries=config.flood_retries,
            max_wait=config.flood_max_wait_seconds,
            label=f"history:{username}",
        )
    except Exception:
        logger.exception("History fetch failed for %s", username)
        messages = []

    stats = compute_channel_stats(messages)
    info = {
        "id": int(entity.id),
        "username": getattr(entity, "username", None),
        "title": getattr(entity, "title", None) or getattr(entity, "username", None),
        "kind": _kind_of(entity),
        "about": about,
        "participants": participants,
        "created_at": getattr(entity, "date", None),
        "linked_username": linked_username,
    }
    return info, stats
