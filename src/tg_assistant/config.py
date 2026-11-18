import socket
from typing import Annotated, Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///data/bot.db"


class DatabaseSettings(BaseSettings):
    """Настройки, нужные только для работы с БД (в т.ч. из CLI alembic)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = DEFAULT_DATABASE_URL


class Settings(DatabaseSettings):
    """Настройки приложения из переменных окружения и файла .env."""

    telegram_bot_token: SecretStr
    allowed_user_ids: Annotated[frozenset[int], NoDecode] = frozenset()
    # Кому присылать сообщения о необработанных ошибках. Пусто — никому.
    admin_ids: Annotated[frozenset[int], NoDecode] = frozenset()
    default_timezone: str = "Europe/Moscow"
    log_level: str = "INFO"
    # Сколько дней хранить архив чатов (Telegram Business). 0 — бессрочно.
    archive_retention_days: int = 0
    # Публичный адрес веб-интерфейса. Пусто — веб-интерфейс выключен.
    # https://... — работает и мини-приложение в Telegram; http://localhost:8080 — только браузер.
    web_app_url: str = ""
    # Адрес метрик cloudflared (например http://cloudflared:2000). Если задан, бот сам узнаёт
    # публичный HTTPS-адрес быстрого туннеля Cloudflare и подставляет его в WEB_APP_URL.
    web_tunnel_metrics_url: str = ""
    # Имя бота без @ — для кнопки «Войти через Telegram». Пусто — бот узнаёт его сам при старте.
    bot_username: str = ""
    web_host: str = "0.0.0.0"
    # PORT — так порт передают хостинги (Railway, Render, Fly.io).
    web_port: int = Field(8080, validation_alias=AliasChoices("WEB_PORT", "PORT", "web_port"))
    # Домен, который Railway выдаёт сервису. Если WEB_APP_URL не задан, адрес берётся отсюда.
    railway_public_domain: str = ""
    # Несколько экземпляров на одну базу Postgres (ПК + облако): работает один — лидер.
    # NODE_PRIORITY: у кого больше, тот главный (ПК — 10, облако — 0). См. docs/failover.md.
    node_name: str = Field(default_factory=socket.gethostname)
    node_priority: int = 0
    leader_interval: float = 10.0

    @model_validator(mode="after")
    def _railway_url(self) -> "Settings":
        if not self.web_app_url and self.railway_public_domain:
            self.web_app_url = f"https://{self.railway_public_domain.strip().rstrip('/')}"
        return self

    @field_validator("web_app_url")
    @classmethod
    def _check_web_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("WEB_APP_URL must start with http:// or https://")
        return value

    @property
    def web_enabled(self) -> bool:
        """Есть ли публичный адрес веб-интерфейса (с туннелем — после того как он получен)."""
        return bool(self.web_app_url)

    @property
    def web_server_enabled(self) -> bool:
        """Запускать ли веб-сервер: адрес задан или будет получен от туннеля."""
        return bool(self.web_app_url or self.web_tunnel_metrics_url)

    def app_url(self, **params: str | int) -> str:
        """Адрес мини-приложения, например app_url(open="archive", chat=123)."""
        if not params:
            return self.web_app_url
        query = urlencode({key: str(value) for key, value in params.items()})
        return f"{self.web_app_url}/?{query}"

    @property
    def mini_app_enabled(self) -> bool:
        """Telegram открывает мини-приложения только по HTTPS."""
        return self.web_app_url.startswith("https://")

    @field_validator("allowed_user_ids", "admin_ids", mode="before")
    @classmethod
    def _parse_ids(cls, value: Any) -> Any:
        if isinstance(value, str):
            return frozenset(int(part) for part in value.split(",") if part.strip())
        return value

    @field_validator("default_timezone")
    @classmethod
    def _check_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown timezone: {value}") from exc
        return value
