from aiogram import Router
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
    WebAppInfo,
)

from ..config import Settings
from ..db import User
from ..texts import APP_INTRO, APP_NEEDS_HTTPS, WEB_NOT_CONFIGURED, WEB_PRIVATE_ONLY, web_link
from ..web.auth import LOGIN_TOKEN_TTL, LoginTokens


async def cmd_app(message: Message, settings: Settings):
    if not settings.web_enabled:
        await message.answer(WEB_NOT_CONFIGURED, parse_mode="HTML")
        return
    if not settings.mini_app_enabled:
        await message.answer(APP_NEEDS_HTTPS, parse_mode="HTML")
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Открыть приложение", web_app=WebAppInfo(url=settings.web_app_url)
                )
            ]
        ]
    )
    await message.answer(APP_INTRO, reply_markup=keyboard, parse_mode="HTML")


async def cmd_web(message: Message, settings: Settings, login_tokens: LoginTokens, user: User):
    if not settings.web_enabled:
        await message.answer(WEB_NOT_CONFIGURED, parse_mode="HTML")
        return
    if message.chat.type != "private":
        await message.answer(WEB_PRIVATE_ONLY, parse_mode="HTML")
        return
    # Токен в части после # не уходит на сервер при открытии и не попадает в логи прокси.
    url = f"{settings.web_app_url}/#login={login_tokens.issue(user.id)}"
    await message.answer(
        web_link(url, LOGIN_TOKEN_TTL // 60, settings.web_app_url),
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


def create_router() -> Router:
    router = Router(name="web")
    router.message.register(cmd_app, Command("app"))
    router.message.register(cmd_web, Command("web"))
    return router
