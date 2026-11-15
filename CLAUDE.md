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
- Архив чатов (Telegram Business, `handlers/business.py`, `db/archive.py`): отправитель бизнес-апдейта — собеседник владельца, а не пользователь бота. Middleware такие апдейты пропускают без проверки и без `user` (`middlewares/business.py`); владельца находит `resolve_owner` по `business_connection_id`. В бизнес-чаты никогда ничего не отправлять — только владельцу в личку.
- Мини-приложение: адрес берётся из `settings.web_app_url` в момент вызова; при `WEB_TUNNEL_METRICS_URL` бот при старте получает адрес туннеля cloudflared (`web/tunnel.py`) и меняет его на лету. Ссылки внутрь приложения — `settings.app_url(open=..., chat=...)`. Архив во фронтенде — `web/static/archive.js` (грузится до `app.js`), API — `web/archive_api.py`; отправка из архива владельцу — `archive_delivery.py`.
