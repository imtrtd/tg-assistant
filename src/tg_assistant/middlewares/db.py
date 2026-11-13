from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from aiogram.types import User as TgUser
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..db.users import get_or_create_user


class DbMiddleware(BaseMiddleware):
    """Открывает сессию БД на апдейт и передаёт в хендлеры `session` и `user`."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], default_tz: str) -> None:
        self.session_factory = session_factory
        self.default_tz = default_tz

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self.session_factory() as session:
            data["session"] = session
            tg_user: TgUser | None = data.get("event_from_user")
            if tg_user is not None:
                data["user"] = await get_or_create_user(session, tg_user, self.default_tz)
            return await handler(event, data)
