"""Утренняя сводка (/digest) и выгрузка заметок (/export)."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import Note, User
from ..db.digest import build_digest, parse_digest_time, set_digest
from ..texts import (
    digest_bad_time,
    digest_disabled,
    digest_enabled,
    digest_status,
    export_caption,
    export_empty,
)

OFF_WORDS = {"off", "выкл", "нет", "stop", "0"}


async def show_digest(message: Message, session: AsyncSession, user: User, arg: str) -> None:
    if not arg:
        state = f"включена, в {user.digest_time}" if user.digest_time else "выключена"
        example = await build_digest(session, user, datetime.now(UTC))
        await message.answer(digest_status(state, example), parse_mode="HTML")
        return
    if arg in OFF_WORDS:
        set_digest(user, None)
        await session.commit()
        await message.answer(digest_disabled(), parse_mode="HTML")
        return
    digest_time = parse_digest_time(arg)
    if digest_time is None:
        await message.answer(digest_bad_time(), parse_mode="HTML")
        return
    set_digest(user, digest_time)
    await session.commit()
    await message.answer(digest_enabled(digest_time, user.timezone), parse_mode="HTML")


async def cmd_digest(message: Message, command: CommandObject, session: AsyncSession, user: User):
    await show_digest(message, session, user, (command.args or "").strip().lower())


def render_export(notes: list[Note], tz_name: str) -> str:
    tz = ZoneInfo(tz_name)
    parts = []
    for note in notes:
        created = note.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        parts.append(f"#{note.id} · {created.astimezone(tz):%d.%m.%Y %H:%M}\n{note.text}")
    return "\n\n---\n\n".join(parts) + "\n"


async def cmd_export(message: Message, session: AsyncSession, user: User):
    notes = list(
        await session.scalars(select(Note).where(Note.user_id == user.id).order_by(Note.id))
    )
    if not notes:
        await message.answer(export_empty(), parse_mode="HTML")
        return
    data = render_export(notes, user.timezone).encode("utf-8")
    name = f"notes-{datetime.now(ZoneInfo(user.timezone)):%Y-%m-%d}.txt"
    await message.answer_document(
        BufferedInputFile(data, filename=name),
        caption=export_caption(len(notes)),
    )


def create_router() -> Router:
    router = Router(name="extras")
    router.message.register(cmd_digest, Command("digest"))
    router.message.register(cmd_export, Command("export"))
    return router
