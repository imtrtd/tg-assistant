import pytest
from pydantic import ValidationError

from tg_assistant.config import Settings


def make(monkeypatch, **env):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


def test_allowed_ids_parsed_from_comma_list(monkeypatch):
    assert make(monkeypatch, ALLOWED_USER_IDS=" 1, 22 ,").allowed_user_ids == {1, 22}


def test_allowed_ids_empty_by_default(monkeypatch):
    assert make(monkeypatch).allowed_user_ids == frozenset()


def test_invalid_timezone_rejected(monkeypatch):
    with pytest.raises(ValidationError):
        make(monkeypatch, DEFAULT_TIMEZONE="Mars/Olympus")


def test_port_from_hosting_env(monkeypatch):
    monkeypatch.delenv("WEB_PORT", raising=False)
    assert make(monkeypatch, PORT="9000").web_port == 9000


def test_web_port_wins_over_port(monkeypatch):
    assert make(monkeypatch, PORT="9000", WEB_PORT="8081").web_port == 8081


def test_railway_domain_becomes_web_app_url(monkeypatch):
    monkeypatch.delenv("WEB_APP_URL", raising=False)
    settings = make(monkeypatch, RAILWAY_PUBLIC_DOMAIN="bot.up.railway.app")
    assert settings.web_app_url == "https://bot.up.railway.app"
    assert settings.mini_app_enabled


def test_explicit_web_app_url_wins_over_railway(monkeypatch):
    settings = make(
        monkeypatch, RAILWAY_PUBLIC_DOMAIN="bot.up.railway.app", WEB_APP_URL="https://my.example"
    )
    assert settings.web_app_url == "https://my.example"
