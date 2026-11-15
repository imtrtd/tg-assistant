from aiogram import Bot
from aiohttp import web
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..config import Settings
from ..db import User
from .auth import LoginTokens, SessionSigner

SETTINGS = web.AppKey("settings", Settings)
SESSION_FACTORY = web.AppKey("session_factory", async_sessionmaker)
LOGIN_TOKENS = web.AppKey("login_tokens", LoginTokens)
SIGNER = web.AppKey("signer", SessionSigner)
# Бот нужен архиву: скачать картинку по file_id и переслать сообщение владельцу.
BOT = web.AppKey("bot", Bot)

# Данные одного запроса: их кладёт middleware `auth`.
DB = web.RequestKey("db", AsyncSession)
USER = web.RequestKey("user", User)
