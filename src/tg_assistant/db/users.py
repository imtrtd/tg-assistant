from aiogram.types import User as TgUser
from sqlalchemy.ext.asyncio import AsyncSession

from .models import User


async def get_or_create_user(session: AsyncSession, tg_user: TgUser, default_tz: str) -> User:
    """Найти пользователя по Telegram id или создать; обновить имя, если оно изменилось."""
    user = await session.get(User, tg_user.id)
    if user is None:
        user = User(
            id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            timezone=default_tz,
        )
        session.add(user)
        await session.commit()
    elif (user.username, user.first_name) != (tg_user.username, tg_user.first_name):
        user.username = tg_user.username
        user.first_name = tg_user.first_name
        await session.commit()
    return user
