from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import BotCommand, Message

from ..db import User

BOT_COMMANDS = [
    BotCommand(command="start", description="Начать работу"),
    BotCommand(command="note", description="Сохранить заметку"),
    BotCommand(command="notes", description="Мои заметки"),
    BotCommand(command="find", description="Поиск по заметкам"),
    BotCommand(command="edit", description="Изменить заметку: /edit 12 текст"),
    BotCommand(command="del", description="Удалить заметку: /del 12"),
    BotCommand(command="remind", description="Напомнить: /remind завтра в 9 позвонить"),
    BotCommand(command="reminders", description="Мои напоминания"),
    BotCommand(command="timezone", description="Часовой пояс"),
    BotCommand(command="help", description="Список команд"),
]

HELP_TEXT = (
    "Доступные команды:\n"
    + "\n".join(
        f"/{c.command} — {c.description[0].lower()}{c.description[1:]}" for c in BOT_COMMANDS
    )
    + "\n\nТеги: добавьте #тег в текст заметки и ищите через /find #тег."
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
