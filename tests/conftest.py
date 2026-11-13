from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot
from aiogram.methods import EditMessageText, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update
from aiogram.types import User as TgUser
from sqlalchemy.ext.asyncio import create_async_engine

from tg_assistant.bot import create_dispatcher
from tg_assistant.config import Settings
from tg_assistant.db import Base, create_session_factory


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield create_session_factory(engine)
    await engine.dispose()


@pytest.fixture
async def session(session_factory):
    async with session_factory() as session:
        yield session


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
    return [m.text for m in sent_methods(bot, SendMessage)]


def callback_from(user_id: int, data: str) -> Update:
    user = TgUser(id=user_id, is_bot=False, first_name="Аня")
    message = Message(
        message_id=10, date=datetime.now(), chat=Chat(id=user_id, type="private"), text="..."
    )
    query = CallbackQuery(id="1", from_user=user, chat_instance="ci", message=message, data=data)
    return Update(update_id=2, callback_query=query)


def sent_methods(bot, method_type):
    return [c.args[0] for c in bot.calls.await_args_list if isinstance(c.args[0], method_type)]


def edited_texts(bot) -> list[str]:
    return [m.text for m in sent_methods(bot, EditMessageText)]
