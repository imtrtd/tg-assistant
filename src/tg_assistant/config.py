import socket
from typing import Annotated, Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///data/bot.db"
DEFAULT_HEARTBEAT_FILE = "data/heartbeat"


class DatabaseSettings(BaseSettings):
    """Настройки, нужные только для работы с БД (в т.ч. из CLI alembic)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = DEFAULT_DATABASE_URL


class Settings(DatabaseSettings):
    """Настройки приложения из переменных окружения и файла .env."""

    telegram_bot_token: SecretStr = Field(
        validation_alias=AliasChoices("TELEGRAM_BOT_TOKEN", "BOT_TOKEN")
    )
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
    # auto — в Docker без своего HTTPS бот сам запускает cloudflared (мини-приложение в Telegram).
    # on — то же вне Docker, если cloudflared есть в PATH. off — не запускать.
    web_tunnel: str = "auto"
    # Имя бота без @ — для кнопки «Войти через Telegram». Пусто — бот узнаёт его сам при старте.
    bot_username: str = ""
    # Бот сам ставит себе настройки при старте (setMySettings): темы в личке без
    # создания новых пользователем, список тем сбоку, Business и inline mode.
    # false — не трогать, всё настраивается вручную в @BotFather.
    bot_settings_sync: bool = True
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
    # Живучесть (tg_assistant.ops): файл heartbeat для HEALTHCHECK Docker, адрес проверки
    # healthchecks.io (пингует только работающий узел) и бэкап базы админам в Telegram.
    heartbeat_file: str = DEFAULT_HEARTBEAT_FILE
    healthcheck_ping_url: str = ""
    backup_interval_hours: float = 24.0
    # Публичный поиск (Telethon). Пустые API_ID / API_HASH / TELEGRAM_SESSION — команды выключены.
    telegram_api_id: int | None = Field(
        default=None, validation_alias=AliasChoices("API_ID", "TELEGRAM_API_ID")
    )
    telegram_api_hash: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("API_HASH", "TELEGRAM_API_HASH")
    )
    telegram_session: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("TELEGRAM_SESSION", "SESSION_STRING")
    )
    research_watch_interval_seconds: int = Field(
        300,
        validation_alias=AliasChoices("RESEARCH_WATCH_INTERVAL_SECONDS", "WATCH_INTERVAL_SECONDS"),
    )
    research_search_limit: int = Field(
        20, validation_alias=AliasChoices("RESEARCH_SEARCH_LIMIT", "SEARCH_LIMIT")
    )
    research_find_limit: int = Field(
        20, validation_alias=AliasChoices("RESEARCH_FIND_LIMIT", "FIND_LIMIT")
    )
    research_channel_history_limit: int = Field(
        100,
        validation_alias=AliasChoices("RESEARCH_CHANNEL_HISTORY_LIMIT", "CHANNEL_HISTORY_LIMIT"),
    )
    research_flood_max_wait_seconds: int = Field(
        120,
        validation_alias=AliasChoices("RESEARCH_FLOOD_MAX_WAIT_SECONDS", "FLOOD_MAX_WAIT_SECONDS"),
    )
    research_flood_retries: int = Field(
        5, validation_alias=AliasChoices("RESEARCH_FLOOD_RETRIES", "FLOOD_RETRIES")
    )
    research_rate_limit_commands: int = Field(
        8, validation_alias=AliasChoices("RESEARCH_RATE_LIMIT_COMMANDS", "RATE_LIMIT_COMMANDS")
    )
    research_rate_limit_window_seconds: int = Field(
        60,
        validation_alias=AliasChoices(
            "RESEARCH_RATE_LIMIT_WINDOW_SECONDS", "RATE_LIMIT_WINDOW_SECONDS"
        ),
    )

    @model_validator(mode="after")
    def _railway_url(self) -> "Settings":
        if not self.web_app_url and self.railway_public_domain:
            self.web_app_url = f"https://{self.railway_public_domain.strip().rstrip('/')}"
        return self

    @field_validator("web_tunnel")
    @classmethod
    def _check_tunnel_mode(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in {"auto", "on", "off"}:
            raise ValueError("WEB_TUNNEL must be auto, on, or off")
        return value

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

    @property
    def research_enabled(self) -> bool:
        """Есть ли учётные данные пользовательской сессии для публичного поиска."""
        return bool(self.telegram_api_id and self.telegram_api_hash and self.telegram_session)

    @field_validator("telegram_api_id", mode="before")
    @classmethod
    def _empty_api_id(cls, value: Any) -> Any:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return value

    @field_validator("telegram_api_hash", "telegram_session", mode="before")
    @classmethod
    def _empty_secret(cls, value: Any) -> Any:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return value

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
