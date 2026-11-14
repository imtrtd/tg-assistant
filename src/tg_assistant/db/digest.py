"""Утренняя сводка: расписание и текст."""

import html
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..reminders.format import format_repeat
from .models import Note, Reminder, User


def parse_digest_time(value: str) -> str | None:
    """«8», «8:00», «08.30» → «08:00» / «08:30»; иначе None."""
    value = value.strip().replace(".", ":")
    hour, _, minute = value.partition(":")
    if not hour.isdigit() or (minute and not minute.isdigit()):
        return None
    h, m = int(hour), int(minute or 0)
    if not (0 <= h < 24 and 0 <= m < 60) or len(hour) > 2 or len(minute) > 2:
        return None
    return f"{h:02d}:{m:02d}"


def next_digest_at(digest_time: str, tz_name: str, after: datetime) -> datetime:
    """Ближайший момент строго позже `after`, когда по местному времени будет `digest_time`."""
    tz = ZoneInfo(tz_name)
    local = after.astimezone(tz)
    at = time.fromisoformat(digest_time)
    candidate = datetime.combine(local.date(), at, tzinfo=tz)
    if candidate <= local:
        candidate = datetime.combine(local.date() + timedelta(days=1), at, tzinfo=tz)
    return candidate.astimezone(UTC)


def set_digest(user: User, digest_time: str | None, now: datetime | None = None) -> None:
    user.digest_time = digest_time
    user.digest_next_at = (
        next_digest_at(digest_time, user.timezone, now or datetime.now(UTC))
        if digest_time
        else None
    )


async def due_digests(session: AsyncSession, now: datetime, *, limit: int = 100) -> list[User]:
    result = await session.scalars(
        select(User)
        .where(User.digest_next_at.is_not(None), User.digest_next_at <= now)
        .order_by(User.digest_next_at)
        .limit(limit)
    )
    return list(result)


async def build_digest(session: AsyncSession, user: User, now: datetime) -> str:
    tz = ZoneInfo(user.timezone)
    today: date = now.astimezone(tz).date()
    start = datetime.combine(today, time.min, tzinfo=tz)
    end = start + timedelta(days=1)
    reminders = list(
        await session.scalars(
            select(Reminder)
            .where(
                Reminder.user_id == user.id,
                Reminder.active.is_(True),
                Reminder.remind_at >= start,
                Reminder.remind_at < end,
            )
            .order_by(Reminder.remind_at)
        )
    )
    notes = await session.scalar(select(func.count()).where(Note.user_id == user.id)) or 0

    lines = [f"☀️ <b>Доброе утро, {html.escape(user.first_name)}!</b>", ""]
    if reminders:
        lines.append(f"Сегодня напоминаний: {len(reminders)}")
        for r in reminders:
            local = r.remind_at.astimezone(tz)
            repeat = format_repeat(r.repeat, local)
            suffix = f" 🔁 {repeat}" if repeat else ""
            lines.append(f"• <b>{local:%H:%M}</b> {html.escape(r.text)}{suffix}")
    else:
        lines.append("На сегодня напоминаний нет.")
    lines += ["", f"Заметок всего: {notes}. Отключить сводку: /digest off"]
    return "\n".join(lines)
