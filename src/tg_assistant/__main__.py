import asyncio
import logging

from aiogram import Bot

from .bot import create_dispatcher
from .config import Settings
from .db import create_engine, create_session_factory, run_migrations

logger = logging.getLogger(__name__)


async def run(settings: Settings) -> None:
    engine = create_engine(settings.database_url)
    bot = Bot(token=settings.telegram_bot_token.get_secret_value())
    dp = create_dispatcher(settings, create_session_factory(engine))
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await engine.dispose()


def main() -> None:
    settings = Settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not settings.allowed_user_ids:
        logger.warning("ALLOWED_USER_IDS is empty: the bot will deny access to everyone")
    run_migrations(settings.database_url)
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
