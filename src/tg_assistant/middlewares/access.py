import logging
from collections.abc import Awaitable, Callable, Collection
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update
from aiogram.types import User as TgUser

logger = logging.getLogger(__name__)


class AccessMiddleware(BaseMiddleware):
    """Пропускает только апдейты от пользователей из белого списка."""

    def __init__(self, allowed_user_ids: Collection[int]) -> None:
        self.allowed_user_ids = allowed_user_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: TgUser | None = data.get("event_from_user")
        if user is not None and user.id in self.allowed_user_ids:
            return await handler(event, data)

        if user is not None:
            logger.warning("Access denied for user %s (@%s)", user.id, user.username)
        if isinstance(event, Update):
            if event.message is not None:
                user_id = user.id if user else "?"
                await event.message.answer(
                    f"Доступ к боту закрыт.\nВаш Telegram id: <code>{user_id}</code>",
                    parse_mode="HTML",
                )
            elif event.callback_query is not None:
                await event.callback_query.answer("Доступ закрыт", show_alert=True)
        return None
