# tg-assistant

Telegram-ассистент: бот, который помогает автоматизировать рутинные задачи прямо в мессенджере.

## Возможности (план)

- Ответы на сообщения и команды пользователя
- Напоминания и заметки
- Интеграция с внешними сервисами и AI-моделями

## Быстрый старт

1. Создайте бота через [@BotFather](https://t.me/BotFather) и получите токен.
2. Клонируйте репозиторий и установите зависимости (нужен Python 3.11+):
   ```bash
   git clone https://github.com/imtrtd/tg-assistant.git
   cd tg-assistant
   python -m venv .venv && source .venv/bin/activate
   pip install -e ".[dev]"
   ```
3. Скопируйте `.env.example` в `.env` и укажите `TELEGRAM_BOT_TOKEN`.
4. Запустите бота:
   ```bash
   python -m tg_assistant
   ```
   При запуске автоматически создаётся база `data/bot.db` и применяются миграции.
5. Напишите боту `/start`: пока `ALLOWED_USER_IDS` пуст, он ответит «доступ закрыт»
   и покажет ваш Telegram id. Впишите его в `ALLOWED_USER_IDS` в `.env` и перезапустите бота.

## Разработка

```bash
ruff format .   # форматирование
ruff check .    # линтер
pytest          # тесты

alembic revision --autogenerate -m "описание"   # новая миграция после изменения моделей
```

Структура:

```
src/tg_assistant/
  __main__.py      # точка входа: миграции + запуск polling
  bot.py           # сборка диспетчера
  config.py        # настройки из окружения / .env
  db/              # модели SQLAlchemy, движок, работа с пользователями
  middlewares/     # доступ по белому списку, сессия БД и текущий пользователь
  handlers/        # обработчики команд и ошибок
  migrations/      # миграции Alembic
tests/             # тесты
```

## Статус

Проект на начальной стадии разработки.

## Лицензия

MIT
