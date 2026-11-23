"""Интерактивная выдача строки сессии Telethon.

Запускается отдельно, бот её сам не вызывает:

    python -m tg_assistant.research.login

Скрипт спрашивает телефон, код из Telegram и пароль 2FA, если он включён,
и печатает StringSession. Её кладут в TELEGRAM_SESSION. Файл .session не создаётся.
"""

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _credentials() -> tuple[int, str]:
    load_dotenv()
    api_id = os.getenv("API_ID", "").strip() or input("API_ID: ").strip()
    api_hash = os.getenv("API_HASH", "").strip() or input("API_HASH: ").strip()
    if not api_id or not api_hash:
        raise RuntimeError("Нужны API_ID и API_HASH с https://my.telegram.org")
    return int(api_id), api_hash


async def _login(api_id: int, api_hash: str) -> str:
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.start()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError("Сессия так и не была авторизована.")
        me = await client.get_me()
        label = getattr(me, "username", None) or me.id
        saved = client.session.save()
    finally:
        await client.disconnect()
    print(f"Вход выполнен как {label}.")
    return saved


def main() -> None:
    print("Строка сессии Telethon для публичного поиска.")
    print("Нужен отдельный аккаунт: телефон, код из Telegram и пароль 2FA, если он включён.")
    print("Строку сессии никому не пересылайте и не коммитьте.")
    try:
        api_id, api_hash = _credentials()
        saved = asyncio.run(_login(api_id, api_hash))
    except Exception as exc:
        logger.error("%s", exc)
        sys.exit(1)
    print()
    print("Готово. Впишите значение ниже в TELEGRAM_SESSION (или SESSION_STRING):")
    print(saved)


if __name__ == "__main__":
    main()
