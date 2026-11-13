from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Note


def _normalize(text: str) -> str:
    return text.casefold()


async def add_note(session: AsyncSession, user_id: int, text: str) -> Note:
    note = Note(user_id=user_id, text=text, search_text=_normalize(text))
    session.add(note)
    await session.commit()
    return note


async def get_note(session: AsyncSession, user_id: int, note_id: int) -> Note | None:
    note = await session.get(Note, note_id)
    return note if note is not None and note.user_id == user_id else None


async def list_notes(
    session: AsyncSession, user_id: int, *, offset: int, limit: int
) -> tuple[list[Note], int]:
    """Заметки пользователя, новые сверху, и их общее количество."""
    total = await session.scalar(select(func.count()).where(Note.user_id == user_id))
    result = await session.scalars(
        select(Note)
        .where(Note.user_id == user_id)
        .order_by(Note.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result), total or 0


async def search_notes(
    session: AsyncSession, user_id: int, query: str, *, limit: int
) -> list[Note]:
    """Заметки, содержащие все слова запроса (без учёта регистра)."""
    stmt = select(Note).where(Note.user_id == user_id)
    for word in _normalize(query).split():
        escaped = word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(Note.search_text.like(f"%{escaped}%", escape="\\"))
    result = await session.scalars(stmt.order_by(Note.id.desc()).limit(limit))
    return list(result)


async def update_note(session: AsyncSession, user_id: int, note_id: int, text: str) -> bool:
    note = await get_note(session, user_id, note_id)
    if note is None:
        return False
    note.text = text
    note.search_text = _normalize(text)
    note.updated_at = datetime.now(UTC)
    await session.commit()
    return True


async def delete_note(session: AsyncSession, user_id: int, note_id: int) -> bool:
    result = await session.execute(delete(Note).where(Note.id == note_id, Note.user_id == user_id))
    await session.commit()
    return result.rowcount > 0
