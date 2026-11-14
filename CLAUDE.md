# tg-assistant

Telegram-бот на Python 3.11+ и aiogram 3.

- Код: `src/tg_assistant/`. Новые команды — отдельный модуль в `handlers/` с функцией `create_router()` (не роутер на уровне модуля), подключается в `handlers/__init__.py:build_router`; команду добавить в `BOT_COMMANDS`.
- В хендлерах доступны `session` (AsyncSession) и `user` (db.User) — их кладёт `DbMiddleware`.
- Время в БД, по которому что-то срабатывает, — колонки `UTCDateTime` (aware UTC); в хендлерах переводить в `ZoneInfo(user.timezone)`.
- Схема БД меняется только через миграции: `alembic revision --autogenerate -m "..."`. При запуске бота миграции применяются автоматически.
- Настройки — только через `config.Settings` (pydantic-settings, `.env`). Секреты не коммитить.
- Перед коммитом: `ruff format . && ruff check . && pytest`.
- PR: после зелёного CI сразу мержить (squash), без ожидания ревью.
- Деплой: Docker (`Dockerfile`, `docker-compose.yml`), скрипты в `deploy/`, инструкция в `docs/deploy.md`. Контейнер работает от uid 1000, база — в томе `data/`.
- Веб-интерфейс (`web/`): сервер aiohttp в том же процессе, включается настройкой `WEB_APP_URL`. Вход — initData мини-приложения (`Authorization: tma ...`) или cookie после одноразовой ссылки из `/web`. Страница в `web/static/` без сборки; действует CSP: никаких inline-скриптов и стилей, пользовательский текст вставлять только через `textContent`.
