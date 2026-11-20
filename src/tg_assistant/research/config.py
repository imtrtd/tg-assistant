"""Параметры публичного поиска, собранные из настроек приложения."""

from dataclasses import dataclass

from ..config import Settings


@dataclass(frozen=True)
class ResearchConfig:
    api_id: int
    api_hash: str
    session: str
    watch_interval_seconds: int
    search_limit: int
    find_limit: int
    channel_history_limit: int
    flood_max_wait_seconds: int
    flood_retries: int
    rate_limit_commands: int
    rate_limit_window_seconds: int


def research_config(settings: Settings) -> ResearchConfig | None:
    if not settings.research_enabled:
        return None
    assert settings.telegram_api_id is not None
    assert settings.telegram_api_hash is not None
    assert settings.telegram_session is not None
    return ResearchConfig(
        api_id=settings.telegram_api_id,
        api_hash=settings.telegram_api_hash.get_secret_value(),
        session=settings.telegram_session.get_secret_value(),
        watch_interval_seconds=settings.research_watch_interval_seconds,
        search_limit=settings.research_search_limit,
        find_limit=settings.research_find_limit,
        channel_history_limit=settings.research_channel_history_limit,
        flood_max_wait_seconds=settings.research_flood_max_wait_seconds,
        flood_retries=settings.research_flood_retries,
        rate_limit_commands=settings.research_rate_limit_commands,
        rate_limit_window_seconds=settings.research_rate_limit_window_seconds,
    )
