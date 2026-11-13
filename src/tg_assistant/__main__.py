import asyncio
import logging

from aiogram import Bot, Dispatcher

from .config import Settings
from .handlers import build_router


async def run() -> None:
    settings = Settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    bot = Bot(token=settings.telegram_bot_token.get_secret_value())
    dp = Dispatcher()
    dp.include_router(build_router())
    await dp.start_polling(bot)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
