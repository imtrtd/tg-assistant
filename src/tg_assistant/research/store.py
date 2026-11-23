"""Наблюдения и уже виденные публичные посты в общей базе (SQLite или Postgres)."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import ResearchSeenPost, ResearchWatch


@dataclass(frozen=True)
class Watch:
    id: int
    chat_id: int
    user_id: int
    term: str
    created_at: datetime


def _watch(row: ResearchWatch) -> Watch:
    return Watch(
        id=row.id,
        chat_id=row.chat_id,
        user_id=row.user_id,
        term=row.term,
        created_at=row.created_at,
    )


async def add_watch(
    session: AsyncSession, chat_id: int, user_id: int, term: str
) -> tuple[Watch, bool]:
    key = term.casefold()
    existing = await session.scalar(
        select(ResearchWatch).where(ResearchWatch.chat_id == chat_id, ResearchWatch.term_key == key)
    )
    if existing is not None:
        return _watch(existing), False
    row = ResearchWatch(
        chat_id=chat_id,
        user_id=user_id,
        term=term,
        term_key=key,
        created_at=datetime.now(UTC),
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await session.scalar(
            select(ResearchWatch).where(
                ResearchWatch.chat_id == chat_id, ResearchWatch.term_key == key
            )
        )
        if existing is None:
            raise
        return _watch(existing), False
    return _watch(row), True


async def remove_watch(session: AsyncSession, chat_id: int, term: str) -> bool:
    row = await session.scalar(
        select(ResearchWatch).where(
            ResearchWatch.chat_id == chat_id, ResearchWatch.term_key == term.casefold()
        )
    )
    if row is None:
        return False
    await session.execute(delete(ResearchSeenPost).where(ResearchSeenPost.watch_id == row.id))
    await session.delete(row)
    await session.commit()
    return True


async def list_watches(session: AsyncSession, chat_id: int) -> list[Watch]:
    rows = await session.scalars(
        select(ResearchWatch)
        .where(ResearchWatch.chat_id == chat_id)
        .order_by(ResearchWatch.created_at, ResearchWatch.id)
    )
    return [_watch(row) for row in rows]


async def all_watches(session: AsyncSession) -> list[Watch]:
    rows = await session.scalars(select(ResearchWatch).order_by(ResearchWatch.id))
    return [_watch(row) for row in rows]


async def mark_seen(session: AsyncSession, watch_id: int, peer_id: int, message_id: int) -> bool:
    """Запомнить пост. True, если эта пара (канал, сообщение) для наблюдения ещё не встречалась."""
    session.add(
        ResearchSeenPost(
            watch_id=watch_id,
            peer_id=peer_id,
            message_id=message_id,
            found_at=datetime.now(UTC),
        )
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return False
    return True


async def is_seen(session: AsyncSession, watch_id: int, peer_id: int, message_id: int) -> bool:
    row = await session.scalar(
        select(ResearchSeenPost.id).where(
            ResearchSeenPost.watch_id == watch_id,
            ResearchSeenPost.peer_id == peer_id,
            ResearchSeenPost.message_id == message_id,
        )
    )
    return row is not None


async def seen_keys(session: AsyncSession, watch_id: int) -> set[tuple[int, int]]:
    rows = await session.execute(
        select(ResearchSeenPost.peer_id, ResearchSeenPost.message_id).where(
            ResearchSeenPost.watch_id == watch_id
        )
    )
    return {(int(peer_id), int(message_id)) for peer_id, message_id in rows}
