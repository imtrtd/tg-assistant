from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import SecretStr, field_validator
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
    default_timezone: str = "Europe/Moscow"
    log_level: str = "INFO"
    # Публичный адрес веб-интерфейса. Пусто — веб-интерфейс выключен.
    # https://... — работает и мини-приложение в Telegram; http://localhost:8080 — только браузер.
    web_app_url: str = ""
    web_host: str = "0.0.0.0"
    web_port: int = 8080

    @field_validator("web_app_url")
    @classmethod
    def _check_web_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("WEB_APP_URL must start with http:// or https://")
        return value

    @property
    def web_enabled(self) -> bool:
        return bool(self.web_app_url)

    @property
    def mini_app_enabled(self) -> bool:
        """Telegram открывает мини-приложения только по HTTPS."""
        return self.web_app_url.startswith("https://")

    @field_validator("allowed_user_ids", mode="before")
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
