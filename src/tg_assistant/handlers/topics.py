"""/topics — пересоздать постоянные темы в личном чате с ботом."""

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from ..config import Settings
from ..db import User
from ..topics import TopicRegistry, topic_names

TOPICS_OFF = (
    "Темы выключены. Чтобы бот раскладывал всё по темам, включите режим тем в @BotFather: "
    "/mybots → бот → Bot Settings → Threaded Mode, и перезапустите бота."
)
USERS_CAN_CREATE = (
    "\n\n⚠️ Telegram всё ещё заводит новую тему на каждое сообщение вне тем. Выключите это в "
    "@BotFather: /mybots → бот → Bot Settings → Threaded Mode → запретить пользователям "
    "создавать темы, затем перезапустите бота."
)


async def cmd_topics(
    message: Message, bot: Bot, user: User, settings: Settings, topics: TopicRegistry
):
    if not topics.enabled:
        await message.answer(TOPICS_OFF)
        return
    gone = await topics.verify(bot, user.id)
    before = set(await topics.threads(user.id))
    await topics.ensure(bot, user.id, settings)
    created = set(await topics.threads(user.id)) - before
    warning = USERS_CAN_CREATE if topics.users_can_create is not False else ""
    if created:
        note = " (вместо удалённых)" if gone else ""
        await message.answer(
            f"Создал темы: {len(created)}{note}. Все темы: {topic_names()}.{warning}"
        )
    else:
        await message.answer(f"Все темы на месте: {topic_names()}.{warning}")


def create_router() -> Router:
    router = Router(name="topics")
    router.message.register(cmd_topics, Command("topics"))
    return router
