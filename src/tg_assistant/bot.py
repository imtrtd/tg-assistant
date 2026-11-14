import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import MenuButtonCommands, MenuButtonWebApp, WebAppInfo
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import Settings
from .handlers import BOT_COMMANDS, build_router, on_error
from .middlewares import AccessMiddleware, DbMiddleware
from .reminders.scheduler import run_scheduler
from .web import LoginTokens, create_web_app, start_web_server

logger = logging.getLogger(__name__)


def create_dispatcher(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> Dispatcher:
    dp = Dispatcher(session_factory=session_factory, settings=settings, login_tokens=LoginTokens())
    dp.update.outer_middleware(AccessMiddleware(settings.allowed_user_ids))
    dp.update.outer_middleware(DbMiddleware(session_factory, settings.default_timezone))
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
) -> None:
    await bot.set_my_commands(BOT_COMMANDS)
    # Кнопка меню слева от поля ввода: мини-приложение, если оно настроено, иначе список команд.
    if settings.mini_app_enabled:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Открыть", web_app=WebAppInfo(url=settings.web_app_url)
            )
        )
    else:
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    me = await bot.get_me()
    logger.info("Bot @%s started", me.username)
    dispatcher["scheduler_task"] = asyncio.create_task(run_scheduler(bot, session_factory))
    if settings.web_enabled:
        app = create_web_app(settings, session_factory, login_tokens)
        dispatcher["web_runner"] = await start_web_server(app, settings.web_host, settings.web_port)


async def _on_shutdown(dispatcher: Dispatcher) -> None:
    runner = dispatcher.workflow_data.pop("web_runner", None)
    if runner is not None:
        await runner.cleanup()
    task: asyncio.Task | None = dispatcher.workflow_data.pop("scheduler_task", None)
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
