"""Пользовательская сессия Telethon из строки StringSession, без файла .session."""

import logging

from telethon import TelegramClient
from telethon.sessions import StringSession

from .config import ResearchConfig

logger = logging.getLogger(__name__)


def build_user_client(config: ResearchConfig) -> TelegramClient:
    # Короткие FloodWait Telethon пережидает сам, длинные — flood.call_with_flood_wait.
    threshold = min(24, max(0, config.flood_max_wait_seconds))
    return TelegramClient(
        StringSession(config.session),
        config.api_id,
        config.api_hash,
        flood_sleep_threshold=threshold,
        device_model="tg-assistant",
        system_version="1.0",
        app_version="0.1.0",
    )


async def assert_authorized(client: TelegramClient) -> None:
    if not await client.is_user_authorized():
        raise RuntimeError(
            "Telethon-сессия не авторизована. Сначала выполните: "
            "python -m tg_assistant.research.login"
        )
    me = await client.get_me()
    username = getattr(me, "username", None) or me.id
    logger.info("User session authorized as %s", username)


async def connect_research(config: ResearchConfig) -> TelegramClient | None:
    """Подключить сессию. При ошибке поиск остаётся выключенным, остальной бот работает."""
    client = build_user_client(config)
    try:
        await client.connect()
        await assert_authorized(client)
    except Exception:
        logger.exception("Public research session is unavailable")
        if client.is_connected():
            await client.disconnect()
        return None
    return client
