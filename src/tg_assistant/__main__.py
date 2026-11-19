import asyncio
import contextlib
import logging
import signal

from aiogram import Bot

from .bot import create_dispatcher
from .config import Settings
from .db import create_engine, create_session_factory, run_migrations
from .leader import create_lock_engine, run_with_leadership, uses_leader_election
from .ops import Heartbeat, cancel

logger = logging.getLogger(__name__)


async def run(settings: Settings) -> None:
    engine = create_engine(settings.database_url)
    bot = Bot(token=settings.telegram_bot_token.get_secret_value())
    dp = create_dispatcher(settings, create_session_factory(engine))

    async def run_bot(stop: asyncio.Event) -> None:
        polling = asyncio.create_task(
            dp.start_polling(bot, handle_signals=False, close_bot_session=False)
        )
        stopper = asyncio.create_task(stop.wait())
        await asyncio.wait({polling, stopper}, return_when=asyncio.FIRST_COMPLETED)
        stopper.cancel()
        if not polling.done():
            try:
                await dp.stop_polling()
            except RuntimeError:  # ещё не успел запуститься
                polling.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await polling

    heartbeat = Heartbeat(settings.heartbeat_file)
    heartbeat.beat()
    heartbeat.start_watchdog()
    heartbeat_task = asyncio.create_task(heartbeat.run())

    shutdown = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # Windows
            loop.add_signal_handler(sig, shutdown.set)
    try:
        if uses_leader_election(settings.database_url):
            lock_engine = create_lock_engine(settings.database_url)
            try:
                await run_with_leadership(
                    lock_engine,
                    run_bot,
                    shutdown,
                    name=settings.node_name,
                    priority=settings.node_priority,
                    interval=settings.leader_interval,
                    ttl=settings.leader_interval * 3,
                )
            finally:
                await lock_engine.dispose()
        else:
            await run_bot(shutdown)
    finally:
        await cancel(heartbeat_task)
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
