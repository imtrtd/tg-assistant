"""Постоянные темы в личном чате с ботом.

Если у бота в @BotFather включён режим тем (Threaded Mode), Telegram заводит новую тему
на каждое сообщение, отправленное вне тем. Чтобы чат не зарастал темами, бот один раз
создаёт постоянные темы — «Главное», «Заметки», «Напоминания», «Архив», «Удалённые»,
«Приложение» — и:

- ответы на команды и уведомления отправляет в подходящую тему;
- если сообщение пришло в «случайную» тему (созданную Telegram на лету), отвечает в
  постоянную, а случайную тему удаляет.

Куда отправить, решает request-middleware бота по контекстной переменной `TOPIC_KIND`:
обработчики и рассылки ничего не знают о темах, кроме `with topic_kind("..."):`.
"""

import contextlib
import contextvars
import html
import logging
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.methods import TelegramMethod
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    TelegramObject,
    Update,
    WebAppInfo,
)
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import Settings
from .db import UserTopic

logger = logging.getLogger(__name__)

HOME, NOTES, REMINDERS, ARCHIVE, DELETED, APP = (
    "home",
    "notes",
    "reminders",
    "archive",
    "deleted",
    "app",
)


@dataclass(frozen=True)
class TopicSpec:
    kind: str
    name: str
    icon_color: int  # один из цветов, которые Telegram разрешает для иконок тем
    intro: str


TOPICS: tuple[TopicSpec, ...] = (
    TopicSpec(
        HOME,
        "🏠 Главное",
        0x6FB9F0,
        "🏠 <b>Главное</b>\n\nМеню, справка и настройки. "
        "Команды можно писать в любой теме — ответ придёт туда, где ему место.",
    ),
    TopicSpec(
        NOTES,
        "📝 Заметки",
        0xFFD67E,
        "📝 <b>Заметки</b>\n\nПишите сюда что угодно — бот предложит сохранить. "
        "Команды: /notes, /find, /edit, /del, /export.",
    ),
    TopicSpec(
        REMINDERS,
        "⏰ Напоминания",
        0x8EEE98,
        "⏰ <b>Напоминания</b>\n\nЗдесь будут срабатывать напоминания и утренняя сводка. "
        "Например: «завтра в 9 позвонить маме». Команды: /remind, /reminders, /digest.",
    ),
    TopicSpec(
        ARCHIVE,
        "🗄 Архив",
        0xCB86DB,
        "🗄 <b>Архив чатов</b>\n\nСюда приходят изменённые собеседниками сообщения. "
        "Команды: /archive, /chats.",
    ),
    TopicSpec(
        DELETED,
        "🗑 Удалённые",
        0xFB6F5F,
        "🗑 <b>Удалённые</b>\n\nСюда приходят сообщения, которые собеседники удалили, "
        "вместе с фото и голосовыми. Команда: /deleted.",
    ),
    TopicSpec(APP, "📱 Приложение", 0xFF93B2, ""),
)
SPECS = {spec.kind: spec for spec in TOPICS}

# Куда по смыслу отправлять ответ на команду, если она пришла вне постоянных тем.
COMMAND_KINDS = {
    "note": NOTES,
    "notes": NOTES,
    "find": NOTES,
    "edit": NOTES,
    "del": NOTES,
    "export": NOTES,
    "remind": REMINDERS,
    "reminders": REMINDERS,
    "digest": REMINDERS,
    "archive": ARCHIVE,
    "chats": ARCHIVE,
    "deleted": DELETED,
    "app": APP,
    "web": APP,
}

TOPIC_KIND: contextvars.ContextVar[str | None] = contextvars.ContextVar("topic_kind", default=None)
# Случайная тема текущего апдейта: (chat_id, thread_id). Ответы в неё уводим в постоянную.
STRAY: contextvars.ContextVar[tuple[int, int] | None] = contextvars.ContextVar(
    "stray_topic", default=None
)


@contextlib.contextmanager
def topic_kind(kind: str) -> Iterator[None]:
    """Отправленное внутри блока в личку уйдёт в тему `kind` (если темы включены)."""
    token = TOPIC_KIND.set(kind)
    try:
        yield
    finally:
        TOPIC_KIND.reset(token)


def app_markup(settings: Settings) -> InlineKeyboardMarkup | None:
    if not settings.mini_app_enabled:
        return None
    button = InlineKeyboardButton(
        text="📱 Открыть приложение", web_app=WebAppInfo(url=settings.app_url())
    )
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


def app_text(settings: Settings) -> str:
    if settings.mini_app_enabled:
        return (
            "📱 <b>Приложение</b>\n\nЗаметки, напоминания и архив чатов в одном окне — "
            "кнопка ниже или «Открыть» слева от поля ввода."
        )
    return (
        "📱 <b>Приложение</b>\n\nМини-приложению нужен HTTPS-адрес. Как включить: "
        "docs/mini-app.md. Пока доступен вход в браузере: /web"
    )


class TopicRegistry:
    """Темы пользователей: хранение, создание, кэш."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        self.enabled = False  # включается при старте, если у бота включён режим тем
        self._cache: dict[int, dict[str, int]] = {}

    async def threads(self, user_id: int) -> dict[str, int]:
        if user_id not in self._cache:
            async with self.session_factory() as session:
                rows = await session.scalars(select(UserTopic).where(UserTopic.user_id == user_id))
                self._cache[user_id] = {row.kind: row.thread_id for row in rows}
        return self._cache[user_id]

    async def thread_for(self, user_id: int, kind: str) -> int | None:
        return (await self.threads(user_id)).get(kind)

    async def is_known(self, user_id: int, thread_id: int) -> bool:
        return thread_id in (await self.threads(user_id)).values()

    async def forget(self, user_id: int, kind: str | None = None) -> None:
        async with self.session_factory() as session:
            stmt = delete(UserTopic).where(UserTopic.user_id == user_id)
            if kind is not None:
                stmt = stmt.where(UserTopic.kind == kind)
            await session.execute(stmt)
            await session.commit()
        if kind is None:
            self._cache.pop(user_id, None)
        else:
            self._cache.get(user_id, {}).pop(kind, None)

    async def ensure(self, bot: Bot, user_id: int, settings: Settings) -> dict[str, int]:
        """Создать недостающие темы (одна попытка на тему, ошибки — в лог)."""
        threads = await self.threads(user_id)
        missing = [spec for spec in TOPICS if spec.kind not in threads]
        if not missing:
            return threads
        async with self.session_factory() as session:
            for spec in missing:
                try:
                    topic = await bot.create_forum_topic(
                        chat_id=user_id, name=spec.name, icon_color=spec.icon_color
                    )
                    thread_id = topic.message_thread_id
                    text = app_text(settings) if spec.kind == APP else spec.intro
                    with topic_kind(spec.kind):
                        intro = await bot.send_message(
                            user_id,
                            text,
                            parse_mode="HTML",
                            message_thread_id=thread_id,
                            reply_markup=app_markup(settings) if spec.kind == APP else None,
                        )
                    message_id = intro.message_id if isinstance(intro, Message) else None
                    if message_id is not None:
                        with contextlib.suppress(TelegramAPIError):
                            await bot.pin_chat_message(
                                user_id, message_id, disable_notification=True
                            )
                except TelegramAPIError:
                    logger.exception("Could not create topic %s for user %s", spec.kind, user_id)
                    continue
                session.add(
                    UserTopic(
                        user_id=user_id, kind=spec.kind, thread_id=thread_id, message_id=message_id
                    )
                )
                threads[spec.kind] = thread_id
            await session.commit()
        return threads

    async def verify(self, bot: Bot, user_id: int) -> list[str]:
        """Забыть темы, которые пользователь удалил. Возвращает их виды."""
        gone = []
        for kind, thread_id in list((await self.threads(user_id)).items()):
            try:
                await bot.send_chat_action(user_id, "typing", message_thread_id=thread_id)
            except TelegramBadRequest as exc:
                if "thread not found" in str(exc).lower():
                    gone.append(kind)
            except TelegramAPIError:
                continue
        for kind in gone:
            await self.forget(user_id, kind)
        return gone

    async def refresh_app_messages(self, bot: Bot, settings: Settings) -> None:
        """Обновить кнопку в закреплённом сообщении «Приложения» (адрес туннеля мог смениться)."""
        if not self.enabled:
            return
        async with self.session_factory() as session:
            rows = list(
                await session.scalars(
                    select(UserTopic).where(
                        UserTopic.kind == APP, UserTopic.message_id.is_not(None)
                    )
                )
            )
        for row in rows:
            try:
                await bot.edit_message_text(
                    text=app_text(settings),
                    chat_id=row.user_id,
                    message_id=row.message_id,
                    parse_mode="HTML",
                    reply_markup=app_markup(settings),
                )
            except TelegramBadRequest as exc:
                if "message is not modified" not in str(exc):
                    logger.warning("Could not refresh app message for %s: %s", row.user_id, exc)
            except TelegramAPIError:
                logger.exception("Could not refresh app message for %s", row.user_id)


def kind_for_message(message: Message, reply_kinds: dict[str, str]) -> str:
    text = (message.text or "").strip()
    if text.startswith("/"):
        command = text[1:].split(maxsplit=1)[0].split("@", 1)[0].lower()
        return COMMAND_KINDS.get(command, HOME)
    if text in reply_kinds:
        return reply_kinds[text]
    return NOTES  # обычный текст и пересланное — быстрое сохранение в заметки


class TopicsMiddleware(BaseMiddleware):
    """Для апдейтов из лички: создать темы при первом обращении и выбрать тему ответа."""

    def __init__(self, registry: TopicRegistry, reply_kinds: dict[str, str]) -> None:
        self.registry = registry
        self.reply_kinds = reply_kinds

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not self.registry.enabled or not isinstance(event, Update) or "user" not in data:
            return await handler(event, data)
        message = event.message
        query = event.callback_query
        chat = message.chat if message else None
        if message is None and query is not None and isinstance(query.message, Message):
            chat = query.message.chat
        if chat is None or chat.type != "private":
            return await handler(event, data)

        bot: Bot = data["bot"]
        user_id = chat.id
        await self.registry.ensure(bot, user_id, data["settings"])

        if message is None:  # кнопки: ответ остаётся в теме сообщения с кнопкой
            with topic_kind(HOME):
                return await handler(event, data)

        thread_id = message.message_thread_id
        stray = thread_id is not None and not await self.registry.is_known(user_id, thread_id)
        kind = kind_for_message(message, self.reply_kinds)
        token = STRAY.set((user_id, thread_id) if stray else None)
        try:
            with topic_kind(kind):
                result = await handler(event, data)
        finally:
            STRAY.reset(token)
        if stray:
            # Тему создал Telegram под это сообщение; ответ уже ушёл в постоянную тему.
            try:
                await bot.delete_forum_topic(chat_id=user_id, message_thread_id=thread_id)
            except TelegramAPIError:
                logger.info("Could not delete stray topic %s for %s", thread_id, user_id)
        return result


class TopicsRequestMiddleware(BaseRequestMiddleware):
    """Подставляет message_thread_id в исходящие сообщения в личку."""

    def __init__(self, registry: TopicRegistry) -> None:
        self.registry = registry

    async def __call__(self, make_request, bot: Bot, method: TelegramMethod):
        target = await self._target(method)
        if target is None:
            return await make_request(bot, method)
        user_id, kind, thread_id = target
        update: dict[str, Any] = {"message_thread_id": thread_id}
        if getattr(method, "reply_parameters", None) is not None and STRAY.get():
            update["reply_parameters"] = None  # ответ на сообщение из удаляемой темы
        routed = method.model_copy(update=update)
        try:
            return await make_request(bot, routed)
        except TelegramBadRequest as exc:
            if "thread not found" not in str(exc).lower():
                raise
            # Пользователь удалил тему: забудем её (пересоздастся при следующем обращении)
            # и отправим без темы.
            await self.registry.forget(user_id, kind)
            return await make_request(bot, method.model_copy(update={"message_thread_id": None}))

    async def _target(self, method: TelegramMethod) -> tuple[int, str, int] | None:
        if not self.registry.enabled or "message_thread_id" not in type(method).model_fields:
            return None
        if getattr(method, "business_connection_id", None):
            return None  # в бизнес-чаты бот не пишет, но на всякий случай не трогаем
        chat_id = getattr(method, "chat_id", None)
        kind = TOPIC_KIND.get()
        if not isinstance(chat_id, int) or chat_id <= 0 or kind is None:
            return None
        stray = STRAY.get()
        current = method.message_thread_id
        if current is not None and not (stray and stray == (chat_id, current)):
            return None  # ответ в уже выбранную постоянную тему
        thread_id = await self.registry.thread_for(chat_id, kind)
        return (chat_id, kind, thread_id) if thread_id is not None else None


def topic_names() -> str:
    return ", ".join(html.escape(spec.name) for spec in TOPICS)
