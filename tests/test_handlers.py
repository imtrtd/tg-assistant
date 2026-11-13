from unittest.mock import AsyncMock, MagicMock

from tg_assistant.db import User
from tg_assistant.handlers.common import HELP_TEXT, cmd_help, cmd_start


async def test_start_greets_user_by_name():
    message = MagicMock()
    message.answer = AsyncMock()
    user = User(id=1, first_name="Аня", timezone="UTC")

    await cmd_start(message, user)

    text = message.answer.await_args.args[0]
    assert "Аня" in text
    assert HELP_TEXT in text


async def test_help_lists_commands():
    message = MagicMock()
    message.answer = AsyncMock()

    await cmd_help(message)

    message.answer.assert_awaited_once_with(HELP_TEXT)
    assert "/start" in HELP_TEXT and "/help" in HELP_TEXT
