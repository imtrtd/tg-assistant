import itertools
from datetime import UTC, datetime, timedelta

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import (
    CreateForumTopic,
    DeleteForumTopic,
    EditMessageText,
    PinChatMessage,
    SendChatAction,
    SendMessage,
)
from aiogram.types import Chat, ForumTopic, Message, Update
from aiogram.types import User as TgUser

from tg_assistant.bot import create_dispatcher
from tg_assistant.config import Settings
from tg_assistant.db import User, UserTopic
from tg_assistant.db import reminders as reminders_repo
from tg_assistant.reminders.scheduler import fire_due
from tg_assistant.topics import (
    APP,
    ARCHIVE,
    DELETED,
    HOME,
    NOTES,
    REMINDERS,
    TOPICS,
    TopicsRequestMiddleware,
)

from .conftest import ALLOWED_ID

ME = TgUser(id=ALLOWED_ID, is_bot=False, first_name="Аня")
CHAT = Chat(id=ALLOWED_ID, type="private")


class FakeTelegram:
    """Отвечает на запросы как Telegram; запоминает их (уже после request-middleware)."""

    def __init__(self):
        self.calls = []
        self.thread_ids = itertools.count(1000)
        self.message_ids = itertools.count(1)
        self.deleted_threads: set[int] = set()

    async def __call__(self, bot, method, **kwargs):
        self.calls.append(method)
        thread = getattr(method, "message_thread_id", None)
        if thread in self.deleted_threads:
            raise TelegramBadRequest(method=method, message="Bad Request: message thread not found")
        if isinstance(method, CreateForumTopic):
            return ForumTopic(
                message_thread_id=next(self.thread_ids),
                name=method.name,
                icon_color=method.icon_color,
            )
        if isinstance(method, SendMessage):
            return Message(
                message_id=next(self.message_ids), date=datetime.now(), chat=CHAT, text=method.text
            )
        return True

    def of(self, kind):
        return [c for c in self.calls if isinstance(c, kind)]


@pytest.fixture
def tg():
    return FakeTelegram()


@pytest.fixture
def tbot(tg, monkeypatch):
    bot = Bot(token="42:TEST")
    monkeypatch.setattr(bot.session, "make_request", tg)
    return bot


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "42:TEST")
    monkeypatch.setenv("ALLOWED_USER_IDS", str(ALLOWED_ID))
    monkeypatch.setenv("WEB_APP_URL", "https://bot.example.com")
    return Settings(_env_file=None)


@pytest.fixture
def dp(settings, session_factory, tbot):
    dp = create_dispatcher(settings, session_factory)
    dp["topics"].enabled = True
    tbot.session.middleware(TopicsRequestMiddleware(dp["topics"]))
    return dp


def msg(text, thread=None, mid=500):
    message = Message(
        message_id=mid,
        date=datetime.now(),
        chat=CHAT,
        from_user=ME,
        text=text,
        message_thread_id=thread,
        is_topic_message=thread is not None or None,
    )
    return Update(update_id=mid, message=message)


async def threads(dp):
    return dict(await dp["topics"].threads(ALLOWED_ID))


async def test_first_message_creates_all_topics_once(dp, tbot, tg, session_factory):
    await dp.feed_update(tbot, msg("/start"))
    await dp.feed_update(tbot, msg("/help", mid=501))

    created = tg.of(CreateForumTopic)
    assert [c.name for c in created] == [spec.name for spec in TOPICS]
    known = await threads(dp)
    assert set(known) == {HOME, NOTES, REMINDERS, ARCHIVE, DELETED, APP}
    async with session_factory() as session:
        assert await session.get(UserTopic, (ALLOWED_ID, APP)) is not None
    # в каждую тему — закреплённое вступление; в «Приложении» — кнопка мини-приложения
    intros = [m for m in tg.of(SendMessage) if m.message_thread_id in known.values()][:6]
    app_intro = next(m for m in intros if m.message_thread_id == known[APP])
    assert app_intro.reply_markup.inline_keyboard[0][0].web_app.url == "https://bot.example.com"
    assert len(tg.of(PinChatMessage)) == 6


async def test_command_outside_topics_is_answered_in_its_topic_and_stray_removed(dp, tbot, tg):
    await dp.feed_update(tbot, msg("/start"))
    known = await threads(dp)
    tg.calls.clear()

    await dp.feed_update(tbot, msg("/notes", thread=9999, mid=600))  # Telegram завёл новую тему

    (answer,) = tg.of(SendMessage)
    assert answer.message_thread_id == known[NOTES]
    (deleted,) = tg.of(DeleteForumTopic)
    assert deleted.message_thread_id == 9999


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("/remind через 10 минут чай", REMINDERS),
        ("/deleted", DELETED),
        ("/archive", ARCHIVE),
        ("/help", HOME),
        ("просто мысль", NOTES),
    ],
)
async def test_routing_by_command(dp, tbot, tg, text, kind):
    await dp.feed_update(tbot, msg("/start"))
    known = await threads(dp)
    tg.calls.clear()
    await dp.feed_update(tbot, msg(text, thread=7777, mid=700))
    sent = tg.of(SendMessage)
    assert sent and all(m.message_thread_id == known[kind] for m in sent)
    # ответ на удаляемое сообщение не цепляем — его тема исчезнет
    assert all(m.reply_parameters is None for m in sent)


async def test_command_inside_permanent_topic_stays_there(dp, tbot, tg):
    await dp.feed_update(tbot, msg("/start"))
    known = await threads(dp)
    tg.calls.clear()
    await dp.feed_update(tbot, msg("/notes", thread=known[REMINDERS], mid=800))

    (answer,) = tg.of(SendMessage)
    assert answer.message_thread_id == known[REMINDERS]
    assert tg.of(DeleteForumTopic) == []


async def test_reminders_fire_into_reminders_topic(dp, tbot, tg, session_factory):
    await dp.feed_update(tbot, msg("/start"))
    known = await threads(dp)
    async with session_factory() as session:
        await reminders_repo.add_reminder(
            session, ALLOWED_ID, "чай", datetime.now(UTC) - timedelta(minutes=1)
        )
    tg.calls.clear()
    assert await fire_due(tbot, session_factory) == 1
    (sent,) = tg.of(SendMessage)
    assert sent.message_thread_id == known[REMINDERS]


async def test_deleted_topic_is_forgotten_and_message_still_delivered(
    dp, tbot, tg, session_factory
):
    await dp.feed_update(tbot, msg("/start"))
    known = await threads(dp)
    tg.deleted_threads.add(known[REMINDERS])
    async with session_factory() as session:
        await reminders_repo.add_reminder(
            session, ALLOWED_ID, "чай", datetime.now(UTC) - timedelta(minutes=1)
        )
    tg.calls.clear()
    assert await fire_due(tbot, session_factory) == 1
    first, retry = tg.of(SendMessage)
    assert first.message_thread_id == known[REMINDERS] and retry.message_thread_id is None
    assert REMINDERS not in await threads(dp)

    # при следующем сообщении тема создаётся заново
    tg.calls.clear()
    await dp.feed_update(tbot, msg("/help", thread=known[HOME], mid=900))
    assert [c.name for c in tg.of(CreateForumTopic)] == ["⏰ Напоминания"]


async def test_topics_command_recreates_deleted(dp, tbot, tg):
    await dp.feed_update(tbot, msg("/start"))
    known = await threads(dp)
    tg.deleted_threads.add(known[DELETED])
    tg.calls.clear()

    await dp.feed_update(tbot, msg("/topics", thread=known[HOME], mid=950))

    assert [c.name for c in tg.of(CreateForumTopic)] == ["🗑 Удалённые"]
    assert any(isinstance(c, SendChatAction) for c in tg.calls)
    assert "Создал темы: 1" in tg.of(SendMessage)[-1].text


async def test_app_message_is_refreshed_with_new_address(dp, tbot, tg, settings):
    await dp.feed_update(tbot, msg("/start"))
    tg.calls.clear()
    settings.web_app_url = "https://new.trycloudflare.com"
    await dp["topics"].refresh_app_messages(tbot, settings)
    (edit,) = tg.of(EditMessageText)
    assert edit.reply_markup.inline_keyboard[0][0].web_app.url == "https://new.trycloudflare.com"


async def test_topics_off_changes_nothing(settings, session_factory, tbot, tg):
    dp = create_dispatcher(settings, session_factory)  # enabled = False по умолчанию
    tbot.session.middleware(TopicsRequestMiddleware(dp["topics"]))
    await dp.feed_update(tbot, msg("/notes"))
    assert tg.of(CreateForumTopic) == []
    assert all(m.message_thread_id is None for m in tg.of(SendMessage))
    async with session_factory() as session:
        assert await session.get(User, ALLOWED_ID) is not None


async def test_topics_command_when_off_explains_botfather(settings, session_factory, tbot, tg):
    dp = create_dispatcher(settings, session_factory)
    await dp.feed_update(tbot, msg("/topics"))
    assert "Threaded Mode" in tg.of(SendMessage)[-1].text


async def test_concurrent_updates_create_topics_once(dp, tbot, tg):
    """Апдейты одного пользователя идут параллельно — набор тем всё равно один."""
    import asyncio

    original = tg.__call__

    async def slow(bot, method, **kwargs):
        if isinstance(method, CreateForumTopic):
            await asyncio.sleep(0.01)
        return await original(bot, method, **kwargs)

    # Пользователь уже есть в базе (иначе параллельные апдейты спотыкаются о его создание).
    dp["topics"].enabled = False
    await dp.feed_update(tbot, msg("/help", mid=599))
    dp["topics"].enabled = True
    tg.calls.clear()

    tbot.session.make_request = slow
    await asyncio.gather(*(dp.feed_update(tbot, msg("/help", mid=600 + i)) for i in range(5)))

    assert len(tg.of(CreateForumTopic)) == len(TOPICS)


async def test_flood_control_pauses_topic_creation(dp, tbot, tg):
    from aiogram.exceptions import TelegramRetryAfter

    original = tg.__call__
    created = 0

    async def flood(bot, method, **kwargs):
        nonlocal created
        if isinstance(method, CreateForumTopic):
            created += 1
            if created == 3:
                tg.calls.append(method)
                raise TelegramRetryAfter(method=method, message="Too Many Requests", retry_after=60)
        return await original(bot, method, **kwargs)

    tbot.session.make_request = flood
    await dp.feed_update(tbot, msg("/start"))
    assert len(await threads(dp)) == 2  # успешно созданные темы запомнены

    await dp.feed_update(tbot, msg("/help", mid=501))
    await dp.feed_update(tbot, msg("/notes", mid=502))
    assert len(tg.of(CreateForumTopic)) == 3  # пока действует пауза, новых попыток нет

    dp["topics"]._retry_at.clear()
    await dp.feed_update(tbot, msg("/help", mid=503))
    assert set(await threads(dp)) == {spec.kind for spec in TOPICS}


async def test_topic_is_remembered_when_intro_fails(dp, tbot, tg):
    """Тема создана, а вступление не ушло — тему не создаём повторно."""
    from aiogram.exceptions import TelegramRetryAfter

    original = tg.__call__
    failed = False

    async def intro_flood(bot, method, **kwargs):
        nonlocal failed
        if isinstance(method, SendMessage) and not failed:
            failed = True
            tg.calls.append(method)
            raise TelegramRetryAfter(method=method, message="Too Many Requests", retry_after=60)
        return await original(bot, method, **kwargs)

    tbot.session.make_request = intro_flood
    await dp.feed_update(tbot, msg("/start"))
    assert HOME in await threads(dp)
    dp["topics"]._retry_at.clear()
    await dp.feed_update(tbot, msg("/help", mid=501))
    names = [c.name for c in tg.of(CreateForumTopic)]
    assert len(names) == len(set(names)) == len(TOPICS)
