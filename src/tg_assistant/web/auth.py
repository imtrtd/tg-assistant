"""Вход в веб-интерфейс.

Два способа:
- мини-приложение Telegram присылает подписанную строку initData в заголовке
  `Authorization: tma <initData>`;
- в обычном браузере — одноразовая ссылка от бота (команда /web), которая
  обменивается на подписанную cookie сессии.
"""

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

from aiogram.utils.web_app import WebAppUser, safe_parse_webapp_init_data

SESSION_COOKIE = "tga_session"
SESSION_TTL = 30 * 24 * 3600
LOGIN_TOKEN_TTL = 10 * 60
INIT_DATA_TTL = 24 * 3600


class LoginTokens:
    """Одноразовые токены входа. Живут в памяти процесса: бот и веб-сервер — один процесс."""

    def __init__(self, ttl: int = LOGIN_TOKEN_TTL) -> None:
        self._ttl = ttl
        self._tokens: dict[str, tuple[int, float]] = {}

    def issue(self, user_id: int) -> str:
        now = time.monotonic()
        self._tokens = {t: v for t, v in self._tokens.items() if v[1] > now}
        token = secrets.token_urlsafe(32)
        self._tokens[token] = (user_id, now + self._ttl)
        return token

    def redeem(self, token: str) -> int | None:
        entry = self._tokens.pop(token, None)
        if entry is None or entry[1] <= time.monotonic():
            return None
        return entry[0]


@dataclass(frozen=True)
class SessionSigner:
    """Подписывает cookie сессии ключом, производным от токена бота."""

    key: bytes

    @classmethod
    def from_bot_token(cls, bot_token: str) -> "SessionSigner":
        return cls(
            hmac.new(bot_token.encode(), b"tg-assistant-web-session", hashlib.sha256).digest()
        )

    def _sign(self, payload: str) -> str:
        return hmac.new(self.key, payload.encode(), hashlib.sha256).hexdigest()

    def dumps(self, user_id: int, now: float | None = None) -> str:
        expires = int((now or time.time()) + SESSION_TTL)
        payload = f"{user_id}.{expires}"
        return f"{payload}.{self._sign(payload)}"

    def loads(self, value: str, now: float | None = None) -> int | None:
        payload, _, signature = value.rpartition(".")
        if not payload or not hmac.compare_digest(self._sign(payload), signature):
            return None
        user_id, _, expires = payload.partition(".")
        if not (user_id.isdigit() and expires.isdigit()):
            return None
        if int(expires) < (now or time.time()):
            return None
        return int(user_id)


def parse_init_data(bot_token: str, init_data: str, now: float | None = None) -> WebAppUser | None:
    """Проверить подпись initData мини-приложения и вернуть пользователя."""
    try:
        data = safe_parse_webapp_init_data(bot_token, init_data)
    except ValueError:
        return None
    if data.user is None:
        return None
    if (now or time.time()) - data.auth_date.timestamp() > INIT_DATA_TTL:
        return None
    return data.user
