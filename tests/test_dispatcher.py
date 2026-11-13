from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, Update
from aiogram.types import User as TgUser

from tg_assistant.bot import create_dispatcher
from tg_assistant.config import Settings
from tg_assistant.db import User

ALLOWED_ID = 100


@pytest.fixture
def bot(monkeypatch):
    calls = AsyncMock()
    monkeypatch.setattr(Bot, "__call__", calls)
    bot = Bot(token="42:TEST")
    bot.calls = calls
    return bot


@pytest.fixture
def dp(session_factory, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "42:TEST")
    monkeypatch.setenv("ALLOWED_USER_IDS", str(ALLOWED_ID))
    return create_dispatcher(Settings(_env_file=None), session_factory)


def update_from(user_id: int, text: str) -> Update:
    user = TgUser(id=user_id, is_bot=False, first_name="Аня")
    message = Message(
        message_id=1,
        date=datetime.now(),
        chat=Chat(id=user_id, type="private"),
        from_user=user,
        text=text,
    )
    return Update(update_id=1, message=message)


def sent_texts(bot) -> list[str]:
    return [c.args[0].text for c in bot.calls.await_args_list if isinstance(c.args[0], SendMessage)]


async def test_start_from_allowed_user_registers_and_greets(bot, dp, session_factory):
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/start"))

    assert "Привет, Аня" in sent_texts(bot)[0]
    async with session_factory() as session:
        assert await session.get(User, ALLOWED_ID) is not None


async def test_stranger_is_denied_and_not_registered(bot, dp, session_factory):
    await dp.feed_update(bot, update_from(7, "/start"))

    assert "Доступ к боту закрыт" in sent_texts(bot)[0]
    async with session_factory() as session:
        assert await session.get(User, 7) is None


async def test_handler_error_reported_to_user(bot, dp, monkeypatch):
    from tg_assistant.handlers import common

    monkeypatch.setattr(common, "HELP_TEXT", None)  # answer(None) -> validation error
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/help"))

    assert sent_texts(bot) == ["Что-то пошло не так. Попробуйте ещё раз чуть позже."]
