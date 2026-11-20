from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from telethon.errors import FloodWaitError, SlowModeWaitError

logger = logging.getLogger(__name__)

T = TypeVar("T")


class FloodLimitExceeded(RuntimeError):
    def __init__(self, seconds: int):
        self.seconds = seconds
        super().__init__(f"Telegram FloodWait: {seconds}s exceeds configured maximum")


async def call_with_flood_wait(
    factory: Callable[[], Awaitable[T]],
    *,
    retries: int = 5,
    max_wait: int = 120,
    label: str = "telegram",
) -> T:
    """Call an async factory, sleeping on FloodWait up to max_wait seconds."""
    last_error: Exception | None = None
    attempts = max(1, retries)
    for attempt in range(1, attempts + 1):
        try:
            return await factory()
        except (FloodWaitError, SlowModeWaitError) as exc:
            last_error = exc
            wait = int(getattr(exc, "seconds", 0)) + 1
            if wait > max_wait:
                logger.warning("%s: FloodWait %ss exceeds max %ss", label, wait, max_wait)
                raise FloodLimitExceeded(wait) from exc
            logger.info(
                "%s: FloodWait %ss, sleeping (attempt %s/%s)", label, wait, attempt, attempts
            )
            await asyncio.sleep(wait)
    assert last_error is not None
    raise last_error
