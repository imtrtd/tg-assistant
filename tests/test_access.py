from unittest.mock import AsyncMock, MagicMock

from aiogram.types import Update

from tg_assistant.middlewares import AccessMiddleware


def tg_user(user_id):
    user = MagicMock()
    user.id = user_id
    return user


async def test_allowed_user_passes():
    handler = AsyncMock(return_value="ok")
    middleware = AccessMiddleware({42})

    result = await middleware(handler, MagicMock(), {"event_from_user": tg_user(42)})

    assert result == "ok"
    handler.assert_awaited_once()


async def test_denied_user_gets_own_id_and_handler_skipped():
    handler = AsyncMock()
    update = MagicMock()
    update.__class__ = Update
    update.callback_query = None
    update.message.answer = AsyncMock()
    middleware = AccessMiddleware({42})

    await middleware(handler, update, {"event_from_user": tg_user(7)})

    handler.assert_not_awaited()
    assert "7" in update.message.answer.await_args.args[0]


async def test_update_without_user_is_dropped():
    handler = AsyncMock()

    await AccessMiddleware({42})(handler, MagicMock(), {})

    handler.assert_not_awaited()
