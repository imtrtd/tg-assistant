from unittest.mock import AsyncMock, MagicMock

from tg_assistant.db import User
from tg_assistant.handlers.common import HELP_TEXT, cmd_help, cmd_start


def _settings():
    settings = MagicMock()
    settings.mini_app_enabled = False
    settings.web_enabled = False
    return settings


def _message():
    message = MagicMock()
    message.answer_photo = AsyncMock()
    message.answer = AsyncMock()
    message.chat.type = "private"
    return message


async def test_start_greets_user_by_name():
    message = _message()
    user = User(id=1, first_name="Аня", timezone="UTC")

    await cmd_start(message, user, _settings())

    caption = message.answer_photo.await_args.kwargs["caption"]
    assert "Аня" in caption
    assert message.answer.await_args.kwargs["parse_mode"] == "HTML"


async def test_help_lists_commands():
    message = _message()
    user = User(id=1, first_name="Аня", timezone="UTC")

    await cmd_help(message, user, _settings())

    caption = message.answer_photo.await_args.kwargs["caption"]
    assert HELP_TEXT in caption
    assert "/start" in HELP_TEXT and "/help" in HELP_TEXT
    assert "Аня" in caption
