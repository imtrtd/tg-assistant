from aiogram import Router

from . import common
from .common import BOT_COMMANDS
from .errors import on_error

__all__ = ["BOT_COMMANDS", "build_router", "on_error"]


def build_router() -> Router:
    router = Router()
    router.include_router(common.create_router())
    return router
