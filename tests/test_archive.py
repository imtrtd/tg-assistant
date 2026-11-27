from datetime import UTC, datetime, timedelta

import pytest
from aiogram.methods import (
    GetBusinessConnection,
    SendDocument,
    SendMessage,
    SendPhoto,
    SendVoice,
)
from aiogram.types import (
    BusinessBotRights,
    BusinessConnection,
    BusinessMessagesDeleted,
    Chat,
    Message,
    PhotoSize,
    Update,
    Voice,
)
from aiogram.types import User as TgUser
from sqlalchemy import func, select

from tg_assistant.db import ArchivedMessage, MessageEdit, User
from tg_assistant.db import archive as repo
from tg_assistant.handlers.archive import ArchCb

from .conftest import ALLOWED_ID, callback_from, sent_methods, sent_texts, update_from

CONN = "biz-1"
FRIEND = TgUser(id=555, is_bot=False, first_name="Пётр")
OWNER = TgUser(id=ALLOWED_ID, is_bot=False, first_name="Аня")
CHAT = Chat(id=FRIEND.id, type="private", first_name="Пётр")
T0 = datetime(2026, 11, 14, 10, 0, tzinfo=UTC)

_ids = iter(range(1000, 10**6))


def connection_update(*, enabled=True, user=OWNER) -> Update:
    conn = BusinessConnection(
        id=CONN,
        user=user,
        user_chat_id=user.id,
        date=T0,
        is_enabled=enabled,
        rights=BusinessBotRights(),
    )
    return Update(update_id=next(_ids), business_connection=conn)


def biz_message(
    message_id: int, text: str | None = None, *, sender=FRIEND, edited=False, **media
) -> Update:
    msg = Message(
        message_id=message_id,
        date=T0,
        chat=CHAT,
        from_user=sender,
        text=text,
        business_connection_id=CONN,
        edit_date=int((T0 + timedelta(minutes=5)).timestamp()) if edited else None,
        **media,
    )
    field = "edited_business_message" if edited else "business_message"
    return Update(update_id=next(_ids), **{field: msg})


def deleted(*ids: int) -> Update:
    event = BusinessMessagesDeleted(business_connection_id=CONN, chat=CHAT, message_ids=list(ids))
    return Update(update_id=next(_ids), deleted_business_messages=event)


@pytest.fixture
async def connected(bot, dp):
    await dp.feed_update(bot, connection_update())
    bot.calls.reset_mock()


async def _rows(session_factory) -> list[ArchivedMessage]:
    async with session_factory() as session:
        return list(await session.scalars(select(ArchivedMessage).order_by(ArchivedMessage.id)))


# --- подключение -----------------------------------------------------------


async def test_connection_is_saved_and_owner_notified(bot, dp, session_factory):
    await dp.feed_update(bot, connection_update())

    async with session_factory() as session:
        assert await repo.has_active_connection(session, ALLOWED_ID)
        assert await session.get(User, ALLOWED_ID) is not None
    (msg,) = sent_methods(bot, SendMessage)
    assert msg.chat_id == ALLOWED_ID and "Архив чатов подключён" in msg.text

    await dp.feed_update(bot, connection_update(enabled=False))
    async with session_factory() as session:
        assert not await repo.has_active_connection(session, ALLOWED_ID)
    assert "отключён" in sent_texts(bot)[-1]


async def test_connection_from_stranger_is_ignored(bot, dp, session_factory):
    stranger = TgUser(id=777, is_bot=False, first_name="Чужой")
    await dp.feed_update(bot, connection_update(user=stranger))

    assert sent_methods(bot, SendMessage) == []
    async with session_factory() as session:
        assert await repo.get_connection(session, CONN) is None


# --- сообщения -------------------------------------------------------------


async def test_incoming_message_is_archived_silently(bot, dp, session_factory, connected):
    await dp.feed_update(bot, biz_message(1, "привет"))

    (row,) = await _rows(session_factory)
    assert (row.owner_id, row.chat_id, row.sender_name, row.text, row.outgoing) == (
        ALLOWED_ID,
        FRIEND.id,
        "Пётр",
        "привет",
        False,
    )
    # Собеседнику ничего не отвечаем и пользователем бота его не считаем.
    assert bot.calls.await_count == 0
    async with session_factory() as session:
        assert await session.get(User, FRIEND.id) is None


async def test_owner_own_message_is_outgoing(bot, dp, session_factory, connected):
    await dp.feed_update(bot, biz_message(2, "ответ", sender=OWNER))
    (row,) = await _rows(session_factory)
    assert row.outgoing and row.sender_name == "Аня"


async def test_redelivery_does_not_duplicate(bot, dp, session_factory, connected):
    await dp.feed_update(bot, biz_message(3, "раз"))
    await dp.feed_update(bot, biz_message(3, "раз"))
    assert len(await _rows(session_factory)) == 1


async def test_media_file_id_is_kept(bot, dp, session_factory, connected):
    photo = [
        PhotoSize(file_id="small", file_unique_id="s", width=90, height=90),
        PhotoSize(file_id="big", file_unique_id="b", width=900, height=900),
    ]
    await dp.feed_update(bot, biz_message(4, None, photo=photo, caption="смотри"))
    (row,) = await _rows(session_factory)
    assert (row.media_type, row.file_id, row.text) == ("photo", "big", "смотри")


async def test_unknown_connection_is_looked_up_once(bot, dp, session_factory):
    conn = BusinessConnection(
        id=CONN,
        user=OWNER,
        user_chat_id=ALLOWED_ID,
        date=T0,
        is_enabled=True,
        rights=BusinessBotRights(),
    )

    async def answer(method, *args, **kwargs):
        return conn if isinstance(method, GetBusinessConnection) else None

    bot.calls.side_effect = answer
    await dp.feed_update(bot, biz_message(5, "до перезапуска"))
    await dp.feed_update(bot, biz_message(6, "после"))

    assert len(await _rows(session_factory)) == 2
    assert len(sent_methods(bot, GetBusinessConnection)) == 1


async def test_disabled_or_foreign_connection_stores_nothing(bot, dp, session_factory):
    await dp.feed_update(bot, connection_update(enabled=False))
    await dp.feed_update(bot, biz_message(7, "не сохранять"))
    assert await _rows(session_factory) == []


# --- правки ----------------------------------------------------------------


async def test_edit_by_friend_notifies_owner_with_both_versions(
    bot, dp, session_factory, connected
):
    await dp.feed_update(bot, biz_message(10, "встречаемся в <8>"))
    await dp.feed_update(bot, biz_message(10, "встречаемся в 9", edited=True))

    (msg,) = sent_methods(bot, SendMessage)
    assert msg.chat_id == ALLOWED_ID
    assert "Сообщение изменено" in msg.text and "Пётр" in msg.text
    assert "в &lt;8&gt;" in msg.text and "встречаемся в 9" in msg.text
    (row,) = await _rows(session_factory)
    assert row.text == "встречаемся в 9" and row.edited_at is not None
    async with session_factory() as session:
        (edit,) = await repo.edits_of(session, row.id)
    assert edit.text == "встречаемся в <8>"


async def test_edit_without_text_change_is_ignored(bot, dp, session_factory, connected):
    await dp.feed_update(bot, biz_message(11, "то же"))
    await dp.feed_update(bot, biz_message(11, "то же", edited=True))
    assert sent_methods(bot, SendMessage) == []


async def test_owner_edits_are_stored_but_not_reported(bot, dp, session_factory, connected):
    await dp.feed_update(bot, biz_message(12, "опечатка", sender=OWNER))
    await dp.feed_update(bot, biz_message(12, "исправлено", sender=OWNER, edited=True))

    assert sent_methods(bot, SendMessage) == []
    assert (await _rows(session_factory))[0].text == "исправлено"


async def test_edit_of_message_from_before_connection_is_saved(bot, dp, session_factory, connected):
    await dp.feed_update(bot, biz_message(13, "новая версия", edited=True))
    (row,) = await _rows(session_factory)
    assert row.text == "новая версия" and row.edited_at is not None
    assert sent_methods(bot, SendMessage) == []


async def test_edit_notifications_can_be_turned_off(bot, dp, session_factory, connected):
    async with session_factory() as session:
        (await session.get(User, ALLOWED_ID)).notify_edits = False
        await session.commit()
    await dp.feed_update(bot, biz_message(14, "a"))
    await dp.feed_update(bot, biz_message(14, "b", edited=True))
    assert sent_methods(bot, SendMessage) == []


# --- удаления --------------------------------------------------------------


async def test_deleted_messages_are_reported_with_content(bot, dp, session_factory, connected):
    voice = Voice(file_id="voice-1", file_unique_id="v", duration=3)
    await dp.feed_update(bot, biz_message(20, "секретный <план>"))
    await dp.feed_update(bot, biz_message(21, None, voice=voice))
    await dp.feed_update(bot, biz_message(22, "моё", sender=OWNER))
    await dp.feed_update(bot, deleted(20, 21, 22, 99))

    (msg,) = sent_methods(bot, SendMessage)
    assert msg.chat_id == ALLOWED_ID
    assert "Удалено сообщений: 3" in msg.text  # 2 от Петра + 1 неизвестное; своё не считаем
    assert "секретный &lt;план&gt;" in msg.text and "[голосовое]" in msg.text
    assert "моё" not in msg.text
    assert "Текст 1 из них неизвестен" in msg.text
    (resent,) = sent_methods(bot, SendVoice)
    assert resent.voice == "voice-1" and resent.chat_id == ALLOWED_ID

    rows = {row.message_id: row for row in await _rows(session_factory)}
    assert all(rows[i].deleted_at is not None for i in (20, 21, 22))


async def test_deleted_photo_is_resent(bot, dp, connected):
    photo = [PhotoSize(file_id="p1", file_unique_id="p", width=10, height=10)]
    await dp.feed_update(bot, biz_message(30, None, photo=photo))
    await dp.feed_update(bot, deleted(30))
    (sent,) = sent_methods(bot, SendPhoto)
    assert sent.photo == "p1" and "Удалено" in sent.caption


async def test_delete_notifications_can_be_turned_off(bot, dp, session_factory, connected):
    async with session_factory() as session:
        (await session.get(User, ALLOWED_ID)).notify_deletes = False
        await session.commit()
    await dp.feed_update(bot, biz_message(31, "x"))
    await dp.feed_update(bot, deleted(31))
    assert sent_methods(bot, SendMessage) == []
    assert (await _rows(session_factory))[0].deleted_at is not None


# --- команды ---------------------------------------------------------------


async def test_archive_status_and_toggles(bot, dp, session_factory, connected):
    await dp.feed_update(bot, biz_message(40, "a"))
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/archive"))
    text = sent_texts(bot)[-1]
    assert "подключён ✅" in text and "Чатов: 1 · сообщений: 1" in text

    await dp.feed_update(bot, callback_from(ALLOWED_ID, ArchCb(action="deletes").pack()))
    async with session_factory() as session:
        user = await session.get(User, ALLOWED_ID)
        assert user.notify_edits and not user.notify_deletes


async def test_archive_without_connection_explains_setup(bot, dp):
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/archive"))
    text = sent_texts(bot)[-1]
    assert "не подключён" in text and "Business Mode" in text and "Telegram Business" in text


async def test_chats_list_and_export_file(bot, dp, connected):
    await dp.feed_update(bot, biz_message(50, "первое"))
    await dp.feed_update(bot, biz_message(51, "было", sender=OWNER))
    await dp.feed_update(bot, biz_message(51, "стало", sender=OWNER, edited=True))
    await dp.feed_update(bot, deleted(50))

    await dp.feed_update(bot, callback_from(ALLOWED_ID, ArchCb(action="chats").pack()))
    assert "Пётр" in sent_texts(bot)[-1] and "удалено 1" in sent_texts(bot)[-1]

    data = ArchCb(action="export", chat_id=FRIEND.id).pack()
    await dp.feed_update(bot, callback_from(ALLOWED_ID, data))
    (doc,) = sent_methods(bot, SendDocument)
    content = doc.document.data.decode()
    assert "Пётр: первое  (удалено" in content
    assert "Аня: стало  (изменено)" in content and "было до" in content and ": было" in content


async def test_export_of_other_owners_chat_is_empty(bot, dp, session_factory, connected):
    async with session_factory() as session:
        session.add(
            ArchivedMessage(
                owner_id=999,
                chat_id=1,
                chat_title="чужой",
                message_id=1,
                sender_id=1,
                sender_name="x",
                outgoing=False,
                text="секрет",
                sent_at=T0,
            )
        )
        await session.commit()
    await dp.feed_update(bot, callback_from(ALLOWED_ID, ArchCb(action="export", chat_id=1).pack()))
    assert sent_methods(bot, SendDocument) == []


async def test_deleted_command(bot, dp, connected):
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/deleted"))
    assert "нет" in sent_texts(bot)[-1]
    await dp.feed_update(bot, biz_message(60, "исчезнет"))
    await dp.feed_update(bot, deleted(60))
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/deleted"))
    assert "исчезнет" in sent_texts(bot)[-1]


# --- хранение --------------------------------------------------------------


async def test_purge_removes_old_messages_and_their_edits(session_factory):
    async with session_factory() as session:
        for message_id, sent in ((1, T0 - timedelta(days=40)), (2, T0)):
            session.add(
                ArchivedMessage(
                    owner_id=ALLOWED_ID,
                    chat_id=1,
                    chat_title="c",
                    message_id=message_id,
                    sender_id=1,
                    sender_name="x",
                    outgoing=False,
                    text="t",
                    sent_at=sent,
                )
            )
        await session.commit()
        old = await repo.find(session, ALLOWED_ID, 1, 1)
        session.add(MessageEdit(message_id=old.id, text="v0", replaced_at=T0))
        await session.commit()

        assert await repo.purge_older_than(session, 30, now=T0) == 1
        assert [r.message_id for r in await session.scalars(select(ArchivedMessage))] == [2]
        assert await session.scalar(select(func.count()).select_from(MessageEdit)) == 0


# --- кнопки мини-приложения -------------------------------------------------


@pytest.fixture
def dp_app(session_factory, monkeypatch):
    from tg_assistant.bot import create_dispatcher
    from tg_assistant.config import Settings

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "42:TEST")
    monkeypatch.setenv("ALLOWED_USER_IDS", str(ALLOWED_ID))
    monkeypatch.setenv("WEB_APP_URL", "https://bot.example.com")
    return create_dispatcher(Settings(_env_file=None), session_factory)


async def test_notifications_open_the_chat_in_mini_app(bot, dp_app):
    await dp_app.feed_update(bot, connection_update())
    bot.calls.reset_mock()
    await dp_app.feed_update(bot, biz_message(70, "было"))
    await dp_app.feed_update(bot, biz_message(70, "стало", edited=True))
    await dp_app.feed_update(bot, deleted(70))

    edit_msg, delete_msg = sent_methods(bot, SendMessage)
    for msg in (edit_msg, delete_msg):
        button = msg.reply_markup.inline_keyboard[0][0]
        assert button.web_app.url == f"https://bot.example.com/?open=archive&chat={FRIEND.id}"


async def test_notifications_without_https_have_no_app_button(bot, dp, connected):
    await dp.feed_update(bot, biz_message(71, "было"))
    await dp.feed_update(bot, biz_message(71, "стало", edited=True))
    (msg,) = sent_methods(bot, SendMessage)
    assert msg.reply_markup is None


async def test_archive_command_offers_mini_app(bot, dp_app):
    await dp_app.feed_update(bot, update_from(ALLOWED_ID, "/archive"))
    (msg,) = sent_methods(bot, SendMessage)
    first = msg.reply_markup.inline_keyboard[0][0]
    assert first.web_app.url == "https://bot.example.com/?open=archive"


async def test_concurrent_connection_save_does_not_fail(session_factory, monkeypatch):
    """Два апдейта одновременно сохраняют одно и то же новое подключение."""
    from tg_assistant.db import BusinessConnection

    async with session_factory() as first:
        await repo.save_connection(first, "conn-race", ALLOWED_ID, True)

    async with session_factory() as second:
        real_get = second.get
        calls = 0

        async def stale_get(*args, **kwargs):
            # Первое чтение «не видит» запись соседа — как при гонке.
            nonlocal calls
            calls += 1
            return None if calls == 1 else await real_get(*args, **kwargs)

        monkeypatch.setattr(second, "get", stale_get)
        row = await repo.save_connection(second, "conn-race", ALLOWED_ID, False)

    assert row.is_enabled is False
    async with session_factory() as check:
        total = await check.scalar(select(func.count()).select_from(BusinessConnection))
        assert total == 1
        assert (await check.get(BusinessConnection, "conn-race")).is_enabled is False


async def test_concurrent_store_returns_existing(session_factory, monkeypatch):
    message = Message(
        message_id=77,
        date=datetime.now(UTC),
        chat=Chat(id=555, type="private", first_name="Друг"),
        from_user=TgUser(id=555, is_bot=False, first_name="Друг"),
        text="привет",
    )
    async with session_factory() as first:
        original = await repo.store(first, ALLOWED_ID, message)
        original_id = original.id

    async with session_factory() as second:
        real_find = repo.find
        calls = 0

        async def stale_find(*args, **kwargs):
            nonlocal calls
            calls += 1
            return None if calls == 1 else await real_find(*args, **kwargs)

        monkeypatch.setattr(repo, "find", stale_find)
        row = await repo.store(second, ALLOWED_ID, message)

    assert row.id == original_id


async def test_admin_sees_any_account_archive(bot, dp, session_factory, connected):
    settings = dp.workflow_data["settings"]
    dp.workflow_data["settings"] = settings.model_copy(
        update={"admin_ids": frozenset({ALLOWED_ID})}
    )
    async with session_factory() as session:
        session.add(
            ArchivedMessage(
                owner_id=999,
                chat_id=1,
                chat_title="чужой",
                message_id=1,
                sender_id=1,
                sender_name="x",
                outgoing=False,
                text="секрет",
                sent_at=T0,
                deleted_at=T0,
            )
        )
        await session.commit()
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/archive"))
    assert "999" in sent_texts(bot)[-1]
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/deleted 999"))
    assert "секрет" in sent_texts(bot)[-1]
