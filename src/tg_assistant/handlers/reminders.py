import html
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import Reminder, User
from ..db import reminders as repo
from ..db.digest import set_digest
from ..reminders.format import format_repeat, format_when, parse_timezone
from ..reminders.keyboards import RemCb
from ..reminders.timeparse import parse_reminder
from ..texts import (
    DONE_TOAST,
    REMIND_UNKNOWN,
    REMINDER_GONE,
    remind_help,
    remind_set,
    reminders_empty,
    reminders_header,
    removed_toast,
    snooze_toast,
    timezone_current,
    timezone_set,
    timezone_unknown,
)

LIST_LIMIT = 20


def _now(user: User) -> datetime:
    return datetime.now(ZoneInfo(user.timezone))


def _describe(reminder: Reminder, user: User, now: datetime) -> str:
    when = reminder.remind_at.astimezone(ZoneInfo(user.timezone))
    repeat = format_repeat(reminder.repeat, when)
    suffix = f" 🔁 {repeat}" if repeat else ""
    return f"<b>{format_when(when, now)}</b>{suffix}\n{html.escape(reminder.text)}"


async def cmd_remind(message: Message, command: CommandObject, session: AsyncSession, user: User):
    now = _now(user)
    parsed = parse_reminder(command.args or "", now)
    if parsed is None:
        prefix = REMIND_UNKNOWN if command.args else ""
        await message.answer(prefix + remind_help(), parse_mode="HTML")
        return
    reminder = await repo.add_reminder(session, user.id, parsed.text, parsed.when, parsed.repeat)
    await message.answer(remind_set(_describe(reminder, user, now)), parse_mode="HTML")


def _render_list(reminders: list[Reminder], user: User) -> tuple[str, InlineKeyboardMarkup | None]:
    if not reminders:
        return reminders_empty(), None
    now = _now(user)
    header = reminders_header(
        len(reminders), truncated=len(reminders) == LIST_LIMIT, limit=LIST_LIMIT
    )
    lines = [f"#{r.id} " + _describe(r, user, now) for r in reminders]
    kb = InlineKeyboardBuilder()
    for r in reminders:
        kb.button(text=f"🗑 #{r.id}", callback_data=RemCb(action="del", reminder_id=r.id))
    kb.adjust(5)
    return header + "\n\n" + "\n\n".join(lines), kb.as_markup()


async def cmd_reminders(message: Message, session: AsyncSession, user: User):
    reminders = await repo.list_active(session, user.id, limit=LIST_LIMIT)
    text, markup = _render_list(reminders, user)
    await message.answer(text, reply_markup=markup, parse_mode="HTML")


async def cmd_timezone(message: Message, command: CommandObject, session: AsyncSession, user: User):
    if not command.args:
        await message.answer(
            timezone_current(user.timezone, f"{_now(user):%H:%M}"), parse_mode="HTML"
        )
        return
    tz = parse_timezone(command.args)
    if tz is None:
        await message.answer(timezone_unknown(), parse_mode="HTML")
        return
    user.timezone = tz
    if user.digest_time:
        set_digest(user, user.digest_time)
    await session.commit()
    await message.answer(timezone_set(tz, f"{_now(user):%H:%M}"), parse_mode="HTML")


async def _drop_keyboard(query: CallbackQuery) -> None:
    if isinstance(query.message, Message):
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc):
                raise


async def on_done(query: CallbackQuery, callback_data: RemCb):
    await _drop_keyboard(query)
    await query.answer(DONE_TOAST)


async def on_snooze(query: CallbackQuery, callback_data: RemCb, session: AsyncSession, user: User):
    reminder = await repo.get_reminder(session, user.id, callback_data.reminder_id)
    if reminder is None:
        await query.answer(REMINDER_GONE, show_alert=True)
        return
    when = datetime.now(UTC) + timedelta(minutes=callback_data.minutes)
    if reminder.repeat is None:
        reminder.remind_at = when
        reminder.active = True
        await session.commit()
    else:  # повторяющееся не сдвигаем — откладываем разовую копию
        await repo.add_reminder(session, user.id, reminder.text, when)
    await _drop_keyboard(query)
    local = when.astimezone(ZoneInfo(user.timezone))
    await query.answer(snooze_toast(f"{local:%H:%M}"))


async def on_delete(query: CallbackQuery, callback_data: RemCb, session: AsyncSession, user: User):
    deleted = await repo.delete_reminder(session, user.id, callback_data.reminder_id)
    text, markup = _render_list(await repo.list_active(session, user.id, limit=LIST_LIMIT), user)
    if isinstance(query.message, Message):
        try:
            await query.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc):
                raise
    await query.answer(removed_toast(deleted))


def create_router() -> Router:
    router = Router(name="reminders")
    router.message.register(cmd_remind, Command("remind"))
    router.message.register(cmd_reminders, Command("reminders"))
    router.message.register(cmd_timezone, Command("timezone"))
    router.callback_query.register(on_done, RemCb.filter(F.action == "done"))
    router.callback_query.register(on_snooze, RemCb.filter(F.action == "snooze"))
    router.callback_query.register(on_delete, RemCb.filter(F.action == "del"))
    return router
