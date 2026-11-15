from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from ..config import Settings
from ..db import User
from ..texts import BOT_COMMANDS, GROUP_COMMANDS, REPLY_HINT, command_help
from .menu import create_router as create_menu_router
from .menu import reply_keyboard, send_screen

__all__ = ["BOT_COMMANDS", "GROUP_COMMANDS", "HELP_TEXT"]

HELP_TEXT = command_help(BOT_COMMANDS)


async def cmd_start(message: Message, user: User, settings: Settings) -> None:
    await send_screen(message, "home", user, settings)
    if message.chat.type == "private":
        await message.answer(REPLY_HINT, parse_mode="HTML", reply_markup=reply_keyboard())


async def cmd_help(message: Message, user: User, settings: Settings) -> None:
    await send_screen(message, "home", user, settings, extra=HELP_TEXT)
    if message.chat.type == "private":
        await message.answer(REPLY_HINT, parse_mode="HTML", reply_markup=reply_keyboard())


def create_router() -> Router:
    router = Router(name="common")
    router.include_router(create_menu_router())
    router.message.register(cmd_start, CommandStart())
    router.message.register(cmd_help, Command("help"))
    return router
