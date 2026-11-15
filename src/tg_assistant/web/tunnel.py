"""Быстрый туннель Cloudflare: публичный HTTPS-адрес без своего домена.

cloudflared (`cloudflared tunnel --url http://bot:8080 --metrics 0.0.0.0:2000`) выдаёт
случайный адрес вида https://xxx.trycloudflare.com и сообщает его по
`<metrics>/quicktunnel`. Бот читает этот адрес при старте и следит, не сменился ли он
(после перезапуска cloudflared адрес новый), — и обновляет кнопку мини-приложения.
"""

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable

import aiohttp

logger = logging.getLogger(__name__)

HOSTNAME = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=5)


async def fetch_tunnel_url(metrics_url: str) -> str | None:
    """Текущий адрес туннеля или None, если cloudflared ещё не готов."""
    url = metrics_url.rstrip("/") + "/quicktunnel"
    try:
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as http:
            async with http.get(url) as response:
                if response.status != 200:
                    return None
                data = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError):
        return None
    hostname = data.get("hostname") if isinstance(data, dict) else None
    if not isinstance(hostname, str) or not HOSTNAME.match(hostname.strip().lower()):
        return None
    return f"https://{hostname.strip().lower()}"


async def wait_for_tunnel_url(
    metrics_url: str, *, wait_seconds: float = 90.0, interval: float = 2.0
) -> str | None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_seconds
    while True:
        url = await fetch_tunnel_url(metrics_url)
        if url or loop.time() >= deadline:
            return url
        await asyncio.sleep(interval)


async def watch_tunnel(
    metrics_url: str,
    current: Callable[[], str],
    on_change: Callable[[str], Awaitable[None]],
    *,
    interval: float = 120.0,
) -> None:
    """Периодически сверять адрес туннеля и вызывать on_change при смене."""
    while True:
        await asyncio.sleep(interval)
        try:
            url = await fetch_tunnel_url(metrics_url)
            if url and url != current():
                logger.info("Tunnel address changed: %s", url)
                await on_change(url)
        except Exception:
            logger.exception("Tunnel watcher iteration failed")
