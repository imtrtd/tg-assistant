from unittest.mock import AsyncMock, MagicMock

from tg_assistant.handlers.common import HELP_TEXT, cmd_help, cmd_start


async def test_start_greets_user_by_name():
    message = MagicMock()
    message.from_user.first_name = "Аня"
    message.answer = AsyncMock()

    await cmd_start(message)

    text = message.answer.await_args.args[0]
    assert "Аня" in text
    assert HELP_TEXT in text


async def test_help_lists_commands():
    message = MagicMock()
    message.answer = AsyncMock()

    await cmd_help(message)

    message.answer.assert_awaited_once_with(HELP_TEXT)
