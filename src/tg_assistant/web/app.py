import logging
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..config import Settings
from ..db import User
from ..db.users import get_or_create_user
from . import api
from .auth import SESSION_COOKIE, LoginTokens, SessionSigner, parse_init_data
from .keys import DB, LOGIN_TOKENS, SESSION_FACTORY, SETTINGS, SIGNER, USER

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
MAX_BODY = 64 * 1024

CSP = (
    "default-src 'self'; script-src 'self' https://telegram.org; style-src 'self'; "
    "img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'; "
    "frame-ancestors https://web.telegram.org https://*.telegram.org"
)
PUBLIC_API = {"/api/login", "/api/logout"}


def json_error(status: int, message: str) -> web.Response:
    return web.json_response({"error": message}, status=status)


@web.middleware
async def security_headers(request: web.Request, handler):
    try:
        response = await handler(request)
    except web.HTTPException as exc:
        if not request.path.startswith("/api/"):
            raise
        response = json_error(exc.status, exc.reason or "Ошибка")
    response.headers.setdefault("Content-Security-Policy", CSP)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


def _same_origin(request: web.Request) -> bool:
    origin = request.headers.get("Origin")
    return origin is None or urlsplit(origin).netloc == request.host


@web.middleware
async def auth(request: web.Request, handler):
    """Для /api/*: определить пользователя и открыть сессию БД."""
    if not request.path.startswith("/api/"):
        return await handler(request)
    if request.method not in ("GET", "HEAD") and not _same_origin(request):
        return json_error(403, "Запрос с другого сайта отклонён")

    settings = request.app[SETTINGS]
    async with request.app[SESSION_FACTORY]() as session:
        request[DB] = session
        if request.path in PUBLIC_API:
            return await handler(request)

        user: User | None = None
        header = request.headers.get("Authorization", "")
        if header.startswith("tma "):
            tg_user = parse_init_data(settings.telegram_bot_token.get_secret_value(), header[4:])
            if tg_user is None:
                return json_error(401, "Данные входа Telegram недействительны")
            if tg_user.id not in settings.allowed_user_ids:
                return json_error(403, f"Доступ закрыт. Ваш Telegram id: {tg_user.id}")
            user = await get_or_create_user(session, tg_user, settings.default_timezone)
        else:
            user_id = request.app[SIGNER].loads(request.cookies.get(SESSION_COOKIE, ""))
            if user_id is None:
                return json_error(401, "Нужен вход")
            if user_id not in settings.allowed_user_ids:
                return json_error(403, "Доступ закрыт")
            user = await session.get(User, user_id)
            if user is None:
                return json_error(401, "Нужен вход")

        request[USER] = user
        return await handler(request)


async def index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


def create_web_app(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    login_tokens: LoginTokens,
) -> web.Application:
    app = web.Application(middlewares=[security_headers, auth], client_max_size=MAX_BODY)
    app[SETTINGS] = settings
    app[SESSION_FACTORY] = session_factory
    app[LOGIN_TOKENS] = login_tokens
    app[SIGNER] = SessionSigner.from_bot_token(settings.telegram_bot_token.get_secret_value())
    app.router.add_get("/", index)
    app.router.add_static("/static/", STATIC_DIR)
    api.setup_routes(app)
    return app


async def start_web_server(app: web.Application, host: str, port: int) -> web.AppRunner:
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info("Web interface listening on %s:%s", host, port)
    return runner
