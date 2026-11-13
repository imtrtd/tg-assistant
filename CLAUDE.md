# tg-assistant

Telegram-бот на Python 3.11+ и aiogram 3.

- Код: `src/tg_assistant/`, новые команды — отдельный модуль в `handlers/`, подключается в `handlers/__init__.py:build_router`.
- Настройки — только через `config.Settings` (pydantic-settings, `.env`). Секреты не коммитить.
- Перед коммитом: `ruff format . && ruff check . && pytest`.
