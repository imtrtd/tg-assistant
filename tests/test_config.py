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
