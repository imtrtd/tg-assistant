"""Быстрый туннель Cloudflare: публичный HTTPS-адрес без своего домена.

cloudflared (`cloudflared tunnel --url http://127.0.0.1:8080 --metrics 127.0.0.1:2000`)
выдаёт случайный адрес вида https://xxx.trycloudflare.com и сообщает его по
`<metrics>/quicktunnel`. Бот читает этот адрес при старте и следит, не сменился ли он
(после перезапуска cloudflared адрес новый), — и обновляет кнопку мини-приложения.

В Docker, если свой HTTPS-адрес не задан, бот запускает cloudflared сам.
"""

import asyncio
import contextlib
import logging
import re
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path

import aiohttp

from ..config import Settings

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


def in_docker() -> bool:
    return Path("/.dockerenv").is_file()


def cloudflared_available(binary: str = "cloudflared") -> bool:
    return shutil.which(binary) is not None


def should_start_embedded_tunnel(
    settings: Settings, *, binary_present: bool, in_docker: bool
) -> bool:
    """Поднять cloudflared в этом процессе, а не ходить к уже запущенному.

    auto — только в Docker и только когда публичный HTTPS ещё не задан.
    on — то же самое и вне Docker, если бинарник есть в PATH.
    Свой WEB_APP_URL, домен Railway или чужой WEB_TUNNEL_METRICS_URL туннель не дублируют.
    """
    mode = settings.web_tunnel
    if mode == "off" or not binary_present or settings.web_port < 1:
        return False
    if settings.web_app_url or settings.web_tunnel_metrics_url:
        return False
    if mode == "on":
        return True
    return in_docker


class QuickTunnel:
    """Процесс cloudflared, который перезапускается, если сам завершился."""

    def __init__(self, origin_port: int, metrics_port: int = 2000, binary: str = "cloudflared"):
        self.metrics_url = f"http://127.0.0.1:{metrics_port}"
        self._origin_port = origin_port
        self._metrics_port = metrics_port
        self._binary = binary
        self._proc: asyncio.subprocess.Process | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        started = asyncio.Event()
        self._error: OSError | None = None
        self._task = asyncio.create_task(self._supervise(started), name="cloudflared")
        try:
            await started.wait()
        except asyncio.CancelledError:
            await self.stop()
            raise
        if self._error is not None:
            raise self._error

    async def _supervise(self, started: asyncio.Event) -> None:
        first = True
        while True:
            try:
                proc = await asyncio.create_subprocess_exec(
                    self._binary,
                    "tunnel",
                    "--no-autoupdate",
                    "--url",
                    f"http://127.0.0.1:{self._origin_port}",
                    "--metrics",
                    f"127.0.0.1:{self._metrics_port}",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
            except OSError as exc:
                if first:
                    self._error = exc
                    started.set()
                    return
                logger.exception("cloudflared failed to start")
                await asyncio.sleep(3)
                continue
            self._proc = proc
            if first:
                started.set()
                first = False
            drain = asyncio.create_task(_drain_stderr(proc.stderr))
            try:
                code = await proc.wait()
            except asyncio.CancelledError:
                if proc.returncode is None:
                    proc.terminate()
                    try:
                        await asyncio.wait_for(proc.wait(), 5)
                    except TimeoutError:
                        proc.kill()
                        await proc.wait()
                with contextlib.suppress(asyncio.CancelledError):
                    await drain
                raise
            await drain
            logger.warning("cloudflared exited (%s), restarting in 3s", code)
            await asyncio.sleep(3)

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def _drain_stderr(stream: asyncio.StreamReader | None) -> None:
    if stream is None:
        return
    while True:
        line = await stream.readline()
        if not line:
            return
        text = line.decode(errors="replace").rstrip()
        if not text:
            continue
        lowered = text.lower()
        if "trycloudflare.com" in lowered or "error" in lowered or "failed" in lowered:
            logger.info("cloudflared: %s", text)
        else:
            logger.debug("cloudflared: %s", text)


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
