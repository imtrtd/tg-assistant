from aiogram import Router

from . import archive, business, capture, common, extras, mention, notes, reminders, topics, web
from .common import BOT_COMMANDS
from .errors import on_error

__all__ = ["BOT_COMMANDS", "build_router", "on_error"]


def build_router() -> Router:
    router = Router()
    # До common: /start inline перехватывается раньше обычного /start.
    router.include_router(mention.create_router())
    router.include_router(common.create_router())
    router.include_router(notes.create_router())
    router.include_router(reminders.create_router())
    router.include_router(web.create_router())
    router.include_router(extras.create_router())
    router.include_router(archive.create_router())
    router.include_router(business.create_router())
    router.include_router(topics.create_router())
    # Последним: ловит всё, что не разобрали обработчики выше.
    router.include_router(capture.create_router())
    return router
