from datetime import datetime

from aiogram.types import Chat, Message, Update
from aiogram.types import User as TgUser

from tg_assistant.db import notes as repo
from tg_assistant.handlers.notes import NotesCb

from .conftest import ALLOWED_ID, callback_from, edited_texts, sent_texts, update_from


async def _notes(session_factory):
    async with session_factory() as session:
        notes, _ = await repo.list_notes(session, ALLOWED_ID, offset=0, limit=100)
        return [n.text for n in notes]


async def test_note_command_saves_text(bot, dp, session_factory):
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/note купить <хлеб>"))

    assert await _notes(session_factory) == ["купить <хлеб>"]
    assert "Сохранено как" in sent_texts(bot)[-1]


async def test_note_as_reply_saves_replied_message(bot, dp, session_factory):
    user = TgUser(id=ALLOWED_ID, is_bot=False, first_name="Аня")
    chat = Chat(id=ALLOWED_ID, type="private")
    original = Message(message_id=1, date=datetime.now(), chat=chat, text="важная мысль")
    reply = Message(
        message_id=2,
        date=datetime.now(),
        chat=chat,
        from_user=user,
        text="/note",
        reply_to_message=original,
    )

    await dp.feed_update(bot, Update(update_id=5, message=reply))

    assert await _notes(session_factory) == ["важная мысль"]


async def test_note_without_text_explains_usage(bot, dp, session_factory):
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/note"))

    assert await _notes(session_factory) == []
    assert "/note купить хлеб" in sent_texts(bot)[-1]


async def test_notes_lists_escaped_text_with_pagination(bot, dp):
    for i in range(6):
        await dp.feed_update(bot, update_from(ALLOWED_ID, f"/note <b>{i}</b>"))

    await dp.feed_update(bot, update_from(ALLOWED_ID, "/notes"))

    text = sent_texts(bot)[-1]
    assert "Заметки (6), стр. 1/2" in text
    assert "&lt;b&gt;5&lt;/b&gt;" in text and "&lt;b&gt;0" not in text


async def test_delete_button_removes_note_and_rerenders(bot, dp, session_factory):
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/note первая"))
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/note вторая"))
    async with session_factory() as session:
        (newest, _), _ = await repo.list_notes(session, ALLOWED_ID, offset=0, limit=5)

    data = NotesCb(action="del", page=0, note_id=newest.id).pack()
    await dp.feed_update(bot, callback_from(ALLOWED_ID, data))

    assert await _notes(session_factory) == ["первая"]
    assert "Заметки (1)" in edited_texts(bot)[-1]


async def test_delete_button_cannot_delete_foreign_note(bot, dp, session_factory):
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/note моя"))
    async with session_factory() as session:
        (note,), _ = await repo.list_notes(session, ALLOWED_ID, offset=0, limit=5)
        note.user_id = 999  # имитируем чужую заметку
        await session.commit()

    await dp.feed_update(
        bot, callback_from(ALLOWED_ID, NotesCb(action="del", page=0, note_id=note.id).pack())
    )

    async with session_factory() as session:
        assert await repo.get_note(session, 999, note.id) is not None


async def test_find_edit_del_commands(bot, dp, session_factory):
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/note Позвонить маме #дом"))
    async with session_factory() as session:
        (note,), _ = await repo.list_notes(session, ALLOWED_ID, offset=0, limit=5)

    await dp.feed_update(bot, update_from(ALLOWED_ID, "/find #ДОМ"))
    assert "Найдено: 1" in sent_texts(bot)[-1]

    await dp.feed_update(bot, update_from(ALLOWED_ID, f"/edit #{note.id} Позвонить папе"))
    assert await _notes(session_factory) == ["Позвонить папе"]

    await dp.feed_update(bot, update_from(ALLOWED_ID, f"/del {note.id}"))
    assert await _notes(session_factory) == []
    await dp.feed_update(bot, update_from(ALLOWED_ID, f"/del {note.id}"))
    assert f"Заметки #{note.id} нет" in sent_texts(bot)[-1]
