import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .branding import setup_bot_profile, setup_menu_button
from .config import Settings
from .handlers import build_router, on_error
from .middlewares import AccessMiddleware, DbMiddleware
from .reminders.scheduler import run_scheduler
from .texts import REPLY_DIGEST, REPLY_MENU, REPLY_NOTES, REPLY_REMINDERS
from .topics import HOME, NOTES, REMINDERS, TopicRegistry, TopicsMiddleware, TopicsRequestMiddleware
from .web import LoginTokens, create_web_app, start_web_server
from .web.tunnel import wait_for_tunnel_url, watch_tunnel

logger = logging.getLogger(__name__)

REPLY_KINDS = {
    REPLY_NOTES: NOTES,
    REPLY_REMINDERS: REMINDERS,
    REPLY_DIGEST: REMINDERS,
    REPLY_MENU: HOME,
}


def create_dispatcher(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> Dispatcher:
    topics = TopicRegistry(session_factory)
    dp = Dispatcher(
        session_factory=session_factory,
        settings=settings,
        login_tokens=LoginTokens(),
        topics=topics,
    )
    dp.update.outer_middleware(AccessMiddleware(settings.allowed_user_ids))
    dp.update.outer_middleware(DbMiddleware(session_factory, settings.default_timezone))
    dp.update.outer_middleware(TopicsMiddleware(topics, REPLY_KINDS))
    dp.errors.register(on_error)
    dp.include_router(build_router())
    dp.startup.register(_on_startup)
    dp.shutdown.register(_on_shutdown)
    return dp


async def _on_startup(
    bot: Bot,
    dispatcher: Dispatcher,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    login_tokens: LoginTokens,
    topics: TopicRegistry,
) -> None:
    if settings.web_server_enabled:
        app = create_web_app(settings, session_factory, login_tokens, bot)
        dispatcher["web_runner"] = await start_web_server(app, settings.web_host, settings.web_port)
    if settings.web_tunnel_metrics_url:
        await _connect_tunnel(bot, dispatcher, settings)
    await setup_bot_profile(bot, settings)
    me = await bot.get_me()
    logger.info("Bot @%s started", me.username)
    # Режим тем в личке включается в @BotFather; тогда раскладываем всё по постоянным темам.
    topics.enabled = me.has_topics_enabled is True
    if topics.enabled:
        if not any(isinstance(m, TopicsRequestMiddleware) for m in bot.session.middleware):
            bot.session.middleware(TopicsRequestMiddleware(topics))
        await topics.refresh_app_messages(bot, settings)
        logger.info("Topics mode is on: replies go to permanent topics")
    dispatcher["scheduler_task"] = asyncio.create_task(
        run_scheduler(bot, session_factory, archive_retention_days=settings.archive_retention_days)
    )


async def _connect_tunnel(bot: Bot, dispatcher: Dispatcher, settings: Settings) -> None:
    """Получить адрес туннеля Cloudflare и следить за его сменой."""
    url = await wait_for_tunnel_url(settings.web_tunnel_metrics_url)
    if url:
        settings.web_app_url = url
        logger.info("Mini App is available at %s", url)
    else:
        logger.error(
            "Tunnel address not received from %s; Mini App stays off until it appears",
            settings.web_tunnel_metrics_url,
        )

    async def on_change(new_url: str) -> None:
        settings.web_app_url = new_url
        await setup_menu_button(bot, settings)
        await dispatcher["topics"].refresh_app_messages(bot, settings)

    dispatcher["tunnel_task"] = asyncio.create_task(
        watch_tunnel(settings.web_tunnel_metrics_url, lambda: settings.web_app_url, on_change)
    )


async def _on_shutdown(dispatcher: Dispatcher) -> None:
    tunnel_task: asyncio.Task | None = dispatcher.workflow_data.pop("tunnel_task", None)
    if tunnel_task is not None:
        tunnel_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await tunnel_task
    runner = dispatcher.workflow_data.pop("web_runner", None)
    if runner is not None:
        await runner.cleanup()
    task: asyncio.Task | None = dispatcher.workflow_data.pop("scheduler_task", None)
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
