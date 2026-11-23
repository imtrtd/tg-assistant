import aiohttp
import pytest
from aiogram.methods import SendMessage, SetChatMenuButton
from aiogram.types import MenuButtonCommands, MenuButtonWebApp

from tg_assistant.bot import create_dispatcher
from tg_assistant.config import Settings

from .conftest import ALLOWED_ID, sent_methods, sent_texts, update_from


@pytest.fixture
def make_dp(session_factory, monkeypatch):
    def factory(web_app_url: str = "", port: int = 0):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "42:TEST")
        monkeypatch.setenv("ALLOWED_USER_IDS", str(ALLOWED_ID))
        settings = Settings(
            _env_file=None, web_app_url=web_app_url, web_host="127.0.0.1", web_port=port
        )
        return create_dispatcher(settings, session_factory)

    return factory


async def test_web_and_app_commands_explain_when_not_configured(bot, make_dp):
    dp = make_dp()
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/web"))
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/app"))

    assert all("WEB_APP_URL" in text for text in sent_texts(bot))


async def test_web_command_sends_one_time_link_without_preview(bot, make_dp):
    dp = make_dp("https://bot.example.com")
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/web"))

    (message,) = sent_methods(bot, SendMessage)
    assert message.link_preview_options.is_disabled
    token = message.text.split("https://bot.example.com/#login=")[1].split()[0]
    assert dp["login_tokens"].redeem(token) == ALLOWED_ID
    assert dp["login_tokens"].redeem(token) is None


async def test_app_command_sends_web_app_button_only_over_https(bot, make_dp):
    await make_dp("https://bot.example.com").feed_update(bot, update_from(ALLOWED_ID, "/app"))
    await make_dp("http://localhost:8080").feed_update(bot, update_from(ALLOWED_ID, "/app"))

    with_button, without = sent_methods(bot, SendMessage)
    button = with_button.reply_markup.inline_keyboard[0][0]
    assert button.web_app.url == "https://bot.example.com"
    assert without.reply_markup is None and "/web" in without.text


async def _startup(bot, dp):
    data = {"dispatcher": dp, "bots": [bot], **dp.workflow_data}
    await dp.emit_startup(bot=bot, **data)
    return data


async def test_startup_sets_mini_app_menu_button_and_serves_web(bot, make_dp):
    dp = make_dp("https://bot.example.com")
    data = await _startup(bot, dp)
    try:
        (menu,) = sent_methods(bot, SetChatMenuButton)
        assert isinstance(menu.menu_button, MenuButtonWebApp)
        assert menu.menu_button.web_app.url == "https://bot.example.com"

        port = dp["web_runner"].addresses[0][1]
        async with aiohttp.ClientSession() as http:
            async with http.get(f"http://127.0.0.1:{port}/") as page:
                assert page.status == 200
            async with http.get(f"http://127.0.0.1:{port}/api/me") as me:
                assert me.status == 401
    finally:
        await dp.emit_shutdown(bot=bot, **data)
    assert "web_runner" not in dp.workflow_data


async def test_startup_without_web_keeps_commands_menu_and_no_server(bot, make_dp):
    dp = make_dp()
    data = await _startup(bot, dp)
    try:
        (menu,) = sent_methods(bot, SetChatMenuButton)
        assert isinstance(menu.menu_button, MenuButtonCommands)
        assert "web_runner" not in dp.workflow_data
    finally:
        await dp.emit_shutdown(bot=bot, **data)


async def test_startup_takes_mini_app_address_from_tunnel(bot, session_factory, monkeypatch):
    from aiohttp import web
    from aiohttp.test_utils import TestServer

    async def quicktunnel(request):
        return web.json_response({"hostname": "calm-fox.trycloudflare.com"})

    metrics_app = web.Application()
    metrics_app.router.add_get("/quicktunnel", quicktunnel)
    metrics = TestServer(metrics_app)
    await metrics.start_server()

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "42:TEST")
    monkeypatch.setenv("ALLOWED_USER_IDS", str(ALLOWED_ID))
    settings = Settings(
        _env_file=None,
        web_tunnel_metrics_url=str(metrics.make_url("")),
        web_host="127.0.0.1",
        web_port=0,
    )
    assert not settings.web_enabled and settings.web_server_enabled
    dp = create_dispatcher(settings, session_factory)
    data = await _startup(bot, dp)
    try:
        assert settings.web_app_url == "https://calm-fox.trycloudflare.com"
        assert settings.mini_app_enabled
        (menu,) = sent_methods(bot, SetChatMenuButton)
        assert menu.menu_button.web_app.url == "https://calm-fox.trycloudflare.com"
        assert "web_runner" in dp.workflow_data and "tunnel_task" in dp.workflow_data
    finally:
        await dp.emit_shutdown(bot=bot, **data)
        await metrics.close()
    assert "tunnel_task" not in dp.workflow_data


async def test_startup_embeds_tunnel_when_docker_has_no_https(bot, session_factory, monkeypatch):
    from aiohttp import web
    from aiohttp.test_utils import TestServer

    async def quicktunnel(request):
        return web.json_response({"hostname": "embedded.trycloudflare.com"})

    metrics_app = web.Application()
    metrics_app.router.add_get("/quicktunnel", quicktunnel)
    metrics = TestServer(metrics_app)
    await metrics.start_server()
    metrics_url = str(metrics.make_url(""))

    class FakeTunnel:
        def __init__(self, port):
            self.port = port
            self.metrics_url = metrics_url
            self.stopped = False

        async def start(self):
            return None

        async def stop(self):
            self.stopped = True

    monkeypatch.setattr(
        "tg_assistant.bot.should_start_embedded_tunnel", lambda *args, **kwargs: True
    )
    monkeypatch.setattr("tg_assistant.bot.QuickTunnel", FakeTunnel)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "42:TEST")
    monkeypatch.setenv("ALLOWED_USER_IDS", str(ALLOWED_ID))
    settings = Settings(_env_file=None, web_host="127.0.0.1", web_port=0)
    dp = create_dispatcher(settings, session_factory)
    data = await _startup(bot, dp)
    tunnel = dp["quick_tunnel"]
    try:
        assert settings.web_app_url == "https://embedded.trycloudflare.com"
        assert isinstance(tunnel, FakeTunnel)
        assert tunnel.port == 0
        (menu,) = sent_methods(bot, SetChatMenuButton)
        assert menu.menu_button.web_app.url == "https://embedded.trycloudflare.com"
    finally:
        await dp.emit_shutdown(bot=bot, **data)
        await metrics.close()
    assert tunnel.stopped
    assert "quick_tunnel" not in dp.workflow_data


def test_app_url_builds_deep_links():
    settings = Settings(_env_file=None, telegram_bot_token="1:x", web_app_url="https://a.b/")
    assert settings.app_url() == "https://a.b"
    assert settings.app_url(open="archive", chat=-100) == "https://a.b/?open=archive&chat=-100"
