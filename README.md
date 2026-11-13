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

## Разработка

```bash
ruff format .   # форматирование
ruff check .    # линтер
pytest          # тесты
```

Структура:

```
src/tg_assistant/
  __main__.py      # точка входа, запуск polling
  config.py        # настройки из окружения / .env
  handlers/        # обработчики команд (aiogram Router)
tests/             # тесты
```

## Статус

Проект на начальной стадии разработки.

## Лицензия

MIT
