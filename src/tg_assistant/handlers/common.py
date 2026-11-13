from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import BotCommand, Message

from ..db import User

BOT_COMMANDS = [
    BotCommand(command="start", description="Начать работу"),
    BotCommand(command="help", description="Список команд"),
]

HELP_TEXT = "Доступные команды:\n" + "\n".join(
    f"/{c.command} — {c.description.lower()}" for c in BOT_COMMANDS
)


async def cmd_start(message: Message, user: User) -> None:
    await message.answer(f"Привет, {user.first_name}! Я твой ассистент.\n\n{HELP_TEXT}")


async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


def create_router() -> Router:
    router = Router(name="common")
    router.message.register(cmd_start, CommandStart())
    router.message.register(cmd_help, Command("help"))
    return router
