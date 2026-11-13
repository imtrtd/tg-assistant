import logging

from aiogram import Bot, Dispatcher
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import Settings
from .handlers import BOT_COMMANDS, build_router, on_error
from .middlewares import AccessMiddleware, DbMiddleware

logger = logging.getLogger(__name__)


def create_dispatcher(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> Dispatcher:
    dp = Dispatcher()
    dp.update.outer_middleware(AccessMiddleware(settings.allowed_user_ids))
    dp.update.outer_middleware(DbMiddleware(session_factory, settings.default_timezone))
    dp.errors.register(on_error)
    dp.include_router(build_router())
    dp.startup.register(_on_startup)
    return dp


async def _on_startup(bot: Bot) -> None:
    await bot.set_my_commands(BOT_COMMANDS)
    me = await bot.get_me()
    logger.info("Bot @%s started", me.username)
