from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Reminder, User


async def add_reminder(
    session: AsyncSession, user_id: int, text: str, when: datetime, repeat: str | None = None
) -> Reminder:
    reminder = Reminder(user_id=user_id, text=text, remind_at=when, repeat=repeat, active=True)
    session.add(reminder)
    await session.commit()
    return reminder


async def get_reminder(session: AsyncSession, user_id: int, reminder_id: int) -> Reminder | None:
    reminder = await session.get(Reminder, reminder_id)
    return reminder if reminder is not None and reminder.user_id == user_id else None


async def list_active(session: AsyncSession, user_id: int, *, limit: int) -> list[Reminder]:
    result = await session.scalars(
        select(Reminder)
        .where(Reminder.user_id == user_id, Reminder.active.is_(True))
        .order_by(Reminder.remind_at, Reminder.id)
        .limit(limit)
    )
    return list(result)


async def delete_reminder(session: AsyncSession, user_id: int, reminder_id: int) -> bool:
    result = await session.execute(
        delete(Reminder).where(Reminder.id == reminder_id, Reminder.user_id == user_id)
    )
    await session.commit()
    return result.rowcount > 0


async def due_reminders(
    session: AsyncSession, now: datetime, *, limit: int = 100
) -> list[tuple[Reminder, str]]:
    """Активные напоминания, время которых наступило, вместе с часовым поясом владельца."""
    result = await session.execute(
        select(Reminder, User.timezone)
        .join(User, User.id == Reminder.user_id)
        .where(Reminder.active.is_(True), Reminder.remind_at <= now)
        .order_by(Reminder.remind_at, Reminder.id)
        .limit(limit)
    )
    return [(reminder, tz) for reminder, tz in result.all()]
