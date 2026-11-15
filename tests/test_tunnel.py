import asyncio

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from tg_assistant.web.tunnel import fetch_tunnel_url, wait_for_tunnel_url, watch_tunnel


@pytest.fixture
async def metrics():
    """Фиктивный сервер метрик cloudflared: /quicktunnel отдаёт текущий hostname."""
    state = {"hostname": "", "status": 200}

    async def quicktunnel(request):
        if state["status"] != 200:
            return web.Response(status=state["status"])
        return web.json_response({"hostname": state["hostname"]})

    app = web.Application()
    app.router.add_get("/quicktunnel", quicktunnel)
    server = TestServer(app)
    await server.start_server()
    state["url"] = str(server.make_url("")).rstrip("/")
    yield state
    await server.close()


async def test_fetch_returns_https_url(metrics):
    metrics["hostname"] = "Calm-Fox-12.trycloudflare.com"
    assert await fetch_tunnel_url(metrics["url"]) == "https://calm-fox-12.trycloudflare.com"


@pytest.mark.parametrize("hostname", ["", "not a host", "evil.com/path", "x" * 0])
async def test_fetch_rejects_empty_or_bad_hostname(metrics, hostname):
    metrics["hostname"] = hostname
    assert await fetch_tunnel_url(metrics["url"]) is None


async def test_fetch_handles_errors(metrics):
    metrics["status"] = 500
    assert await fetch_tunnel_url(metrics["url"]) is None
    assert await fetch_tunnel_url("http://127.0.0.1:9") is None  # никто не слушает


async def test_wait_until_tunnel_is_ready(metrics):
    async def later():
        await asyncio.sleep(0.15)
        metrics["hostname"] = "ready.trycloudflare.com"

    task = asyncio.create_task(later())
    url = await wait_for_tunnel_url(metrics["url"], wait_seconds=3, interval=0.05)
    await task
    assert url == "https://ready.trycloudflare.com"


async def test_wait_gives_up(metrics):
    assert await wait_for_tunnel_url(metrics["url"], wait_seconds=0.1, interval=0.03) is None


async def test_watch_reports_changed_address(metrics):
    metrics["hostname"] = "one.trycloudflare.com"
    current = {"url": "https://one.trycloudflare.com"}
    changed = asyncio.Event()

    async def on_change(url):
        current["url"] = url
        changed.set()

    task = asyncio.create_task(
        watch_tunnel(metrics["url"], lambda: current["url"], on_change, interval=0.05)
    )
    await asyncio.sleep(0.15)
    assert not changed.is_set()  # адрес тот же — ничего не делаем
    metrics["hostname"] = "two.trycloudflare.com"
    await asyncio.wait_for(changed.wait(), 2)
    task.cancel()
    assert current["url"] == "https://two.trycloudflare.com"
