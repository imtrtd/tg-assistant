from aiogram.types import User as TgUser

from tg_assistant.db import User
from tg_assistant.db.users import get_or_create_user


def tg(username="anya", first_name="Аня"):
    return TgUser(id=100, is_bot=False, first_name=first_name, username=username)


async def test_creates_user_with_default_timezone(session):
    user = await get_or_create_user(session, tg(), "Europe/Moscow")

    assert user.id == 100
    assert user.timezone == "Europe/Moscow"
    assert await session.get(User, 100) is not None


async def test_updates_changed_name_and_keeps_timezone(session_factory):
    async with session_factory() as session:
        user = await get_or_create_user(session, tg(), "Europe/Moscow")
        user.timezone = "Asia/Tokyo"
        await session.commit()

    async with session_factory() as session:
        user = await get_or_create_user(session, tg(username="new", first_name="Анна"), "UTC")

    assert (user.username, user.first_name, user.timezone) == ("new", "Анна", "Asia/Tokyo")
