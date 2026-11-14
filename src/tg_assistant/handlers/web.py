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
from ..web.auth import LOGIN_TOKEN_TTL, LoginTokens

NOT_CONFIGURED = "Веб-интерфейс не настроен: в .env не задан WEB_APP_URL."


async def cmd_app(message: Message, settings: Settings):
    if not settings.web_enabled:
        await message.answer(NOT_CONFIGURED)
        return
    if not settings.mini_app_enabled:
        await message.answer(
            "Мини-приложение в Telegram работает только по HTTPS.\n"
            "Сейчас доступен вход в браузере: /web"
        )
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
    await message.answer("Заметки и напоминания в одном окне:", reply_markup=keyboard)


async def cmd_web(message: Message, settings: Settings, login_tokens: LoginTokens, user: User):
    if not settings.web_enabled:
        await message.answer(NOT_CONFIGURED)
        return
    if message.chat.type != "private":
        await message.answer("Ссылку для входа пришлю только в личном чате.")
        return
    # Токен в части после # не уходит на сервер при открытии и не попадает в логи прокси.
    url = f"{settings.web_app_url}/#login={login_tokens.issue(user.id)}"
    await message.answer(
        f"Ссылка для входа в браузере:\n{url}\n\n"
        f"Действует {LOGIN_TOKEN_TTL // 60} минут и только один раз. Никому её не пересылайте.",
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


def create_router() -> Router:
    router = Router(name="web")
    router.message.register(cmd_app, Command("app"))
    router.message.register(cmd_web, Command("web"))
    return router
