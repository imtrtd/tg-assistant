"""Стирание данных пользователя и пароль для него. Удаление необратимо."""

import hashlib
import hmac
import secrets

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    ArchivedMessage,
    MessageEdit,
    Note,
    Reminder,
    ResearchSeenPost,
    ResearchWatch,
)

MIN_PASSWORD_LENGTH = 6
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        scheme, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), **_SCRYPT)
        return hmac.compare_digest(digest, bytes.fromhex(digest_hex))
    except ValueError:
        return False


async def wipe_archive(session: AsyncSession, owner_id: int) -> int:
    """Стереть архив чатов (сообщения собеседников, правки). Возвращает число сообщений."""
    own = select(ArchivedMessage.id).where(ArchivedMessage.owner_id == owner_id)
    await session.execute(delete(MessageEdit).where(MessageEdit.message_id.in_(own)))
    result = await session.execute(
        delete(ArchivedMessage).where(ArchivedMessage.owner_id == owner_id)
    )
    await session.commit()
    return result.rowcount or 0


async def wipe_everything(session: AsyncSession, user_id: int) -> dict[str, int]:
    """Стереть архив, заметки, напоминания и наблюдения. Пользователь и пароль остаются."""
    archive = await wipe_archive(session, user_id)
    watches = select(ResearchWatch.id).where(ResearchWatch.user_id == user_id)
    await session.execute(delete(ResearchSeenPost).where(ResearchSeenPost.watch_id.in_(watches)))
    counts = {"архив": archive}
    for label, model in (
        ("заметки", Note),
        ("напоминания", Reminder),
        ("наблюдения", ResearchWatch),
    ):
        result = await session.execute(delete(model).where(model.user_id == user_id))
        counts[label] = result.rowcount or 0
    await session.commit()
    return counts
