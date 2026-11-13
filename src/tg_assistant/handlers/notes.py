import html
import math

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import Note, User
from ..db import notes as repo

PAGE_SIZE = 5
PREVIEW_LEN = 200
SEARCH_LIMIT = 20


class NotesCb(CallbackData, prefix="notes"):
    action: str  # "page" | "del"
    page: int
    note_id: int = 0


def _preview(note: Note) -> str:
    text = note.text if len(note.text) <= PREVIEW_LEN else note.text[:PREVIEW_LEN] + "…"
    return f"<b>#{note.id}</b> {html.escape(text)}"


def render_page(
    notes: list[Note], total: int, page: int
) -> tuple[str, InlineKeyboardMarkup | None]:
    if total == 0:
        return "Заметок пока нет. Добавьте: /note текст", None

    pages = math.ceil(total / PAGE_SIZE)
    header = f"📝 Заметки ({total}), стр. {page + 1}/{pages}"
    text = header + "\n\n" + "\n\n".join(_preview(note) for note in notes)

    kb = InlineKeyboardBuilder()
    for note in notes:
        kb.button(
            text=f"🗑 #{note.id}",
            callback_data=NotesCb(action="del", page=page, note_id=note.id),
        )
    kb.adjust(PAGE_SIZE)
    nav = InlineKeyboardBuilder()
    if page > 0:
        nav.button(text="◀", callback_data=NotesCb(action="page", page=page - 1))
    if page < pages - 1:
        nav.button(text="▶", callback_data=NotesCb(action="page", page=page + 1))
    kb.attach(nav)
    return text, kb.as_markup()


async def _edit(query: CallbackQuery, text: str, markup: InlineKeyboardMarkup | None) -> None:
    if not isinstance(query.message, Message):
        return
    try:
        await query.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise


async def _page(session: AsyncSession, user: User, page: int):
    notes, total = await repo.list_notes(session, user.id, offset=page * PAGE_SIZE, limit=PAGE_SIZE)
    if not notes and page > 0:  # страница опустела после удаления
        last = max(math.ceil(total / PAGE_SIZE) - 1, 0)
        notes, total = await repo.list_notes(
            session, user.id, offset=last * PAGE_SIZE, limit=PAGE_SIZE
        )
        page = last
    return render_page(notes, total, page)


async def cmd_note(message: Message, command: CommandObject, session: AsyncSession, user: User):
    text = command.args
    if not text and message.reply_to_message is not None:
        replied = message.reply_to_message
        text = replied.text or replied.caption
    if not text:
        await message.answer(
            "Напишите текст заметки после команды: /note купить хлеб\n"
            "Или ответьте командой /note на сообщение, которое нужно сохранить."
        )
        return
    note = await repo.add_note(session, user.id, text.strip())
    await message.answer(f"Сохранено как <b>#{note.id}</b>", parse_mode="HTML")


async def cmd_notes(message: Message, session: AsyncSession, user: User):
    text, markup = await _page(session, user, 0)
    await message.answer(text, reply_markup=markup, parse_mode="HTML")


async def cmd_find(message: Message, command: CommandObject, session: AsyncSession, user: User):
    if not command.args:
        await message.answer("Что искать? Например: /find молоко или /find #работа")
        return
    found = await repo.search_notes(session, user.id, command.args, limit=SEARCH_LIMIT)
    if not found:
        await message.answer("Ничего не найдено.")
        return
    header = f"🔎 Найдено: {len(found)}"
    if len(found) == SEARCH_LIMIT:
        header += f" (показаны первые {SEARCH_LIMIT})"
    await message.answer(header + "\n\n" + "\n\n".join(map(_preview, found)), parse_mode="HTML")


def _parse_id(raw: str | None) -> int | None:
    raw = (raw or "").strip().lstrip("#")
    return int(raw) if raw.isdigit() else None


async def cmd_del(message: Message, command: CommandObject, session: AsyncSession, user: User):
    note_id = _parse_id(command.args)
    if note_id is None:
        await message.answer("Укажите номер заметки: /del 12")
        return
    if await repo.delete_note(session, user.id, note_id):
        await message.answer(f"Заметка #{note_id} удалена.")
    else:
        await message.answer(f"Заметки #{note_id} нет.")


async def cmd_edit(message: Message, command: CommandObject, session: AsyncSession, user: User):
    raw_id, _, text = (command.args or "").partition(" ")
    note_id = _parse_id(raw_id)
    if note_id is None or not text.strip():
        await message.answer("Формат: /edit 12 новый текст")
        return
    if await repo.update_note(session, user.id, note_id, text.strip()):
        await message.answer(f"Заметка #{note_id} обновлена.")
    else:
        await message.answer(f"Заметки #{note_id} нет.")


async def on_page(query: CallbackQuery, callback_data: NotesCb, session: AsyncSession, user: User):
    await _edit(query, *await _page(session, user, callback_data.page))
    await query.answer()


async def on_delete(
    query: CallbackQuery, callback_data: NotesCb, session: AsyncSession, user: User
):
    deleted = await repo.delete_note(session, user.id, callback_data.note_id)
    await _edit(query, *await _page(session, user, callback_data.page))
    await query.answer(f"Заметка #{callback_data.note_id} удалена" if deleted else "Уже удалена")


def create_router() -> Router:
    router = Router(name="notes")
    router.message.register(cmd_note, Command("note"))
    router.message.register(cmd_notes, Command("notes"))
    router.message.register(cmd_find, Command("find"))
    router.message.register(cmd_del, Command("del"))
    router.message.register(cmd_edit, Command("edit"))
    router.callback_query.register(on_page, NotesCb.filter(F.action == "page"))
    router.callback_query.register(on_delete, NotesCb.filter(F.action == "del"))
    return router
