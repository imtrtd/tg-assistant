from aiogram import Router

from . import common, notes, reminders, web
from .common import BOT_COMMANDS
from .errors import on_error

__all__ = ["BOT_COMMANDS", "build_router", "on_error"]


def build_router() -> Router:
    router = Router()
    router.include_router(common.create_router())
    router.include_router(notes.create_router())
    router.include_router(reminders.create_router())
    router.include_router(web.create_router())
    return router
