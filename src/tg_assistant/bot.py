import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import Settings
from .handlers import BOT_COMMANDS, build_router, on_error
from .middlewares import AccessMiddleware, DbMiddleware
from .reminders.scheduler import run_scheduler

logger = logging.getLogger(__name__)


def create_dispatcher(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> Dispatcher:
    dp = Dispatcher(session_factory=session_factory)
    dp.update.outer_middleware(AccessMiddleware(settings.allowed_user_ids))
    dp.update.outer_middleware(DbMiddleware(session_factory, settings.default_timezone))
    dp.errors.register(on_error)
    dp.include_router(build_router())
    dp.startup.register(_on_startup)
    dp.shutdown.register(_on_shutdown)
    return dp


async def _on_startup(
    bot: Bot, dispatcher: Dispatcher, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await bot.set_my_commands(BOT_COMMANDS)
    me = await bot.get_me()
    logger.info("Bot @%s started", me.username)
    dispatcher["scheduler_task"] = asyncio.create_task(run_scheduler(bot, session_factory))


async def _on_shutdown(dispatcher: Dispatcher) -> None:
    task: asyncio.Task | None = dispatcher.workflow_data.pop("scheduler_task", None)
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
