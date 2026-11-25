"""/wipe — стереть данные кнопкой, только по паролю. /wipe set — задать или сменить пароль.

Три отдельные кнопки: архив чатов, всё в базе бота, сообщения бота в личном чате Telegram.
Пароль набирается обычным сообщением, которое бот сразу удаляет. В базе хранится только
хеш. После нескольких неверных паролей стирание блокируется на время.
"""

import asyncio
import logging
import time
from dataclasses import dataclass

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import User
from ..db import wipe as wipe_repo

logger = logging.getLogger(__name__)

ARCHIVE, EVERYTHING, CHAT = "archive", "all", "chat"
LABELS = {
    ARCHIVE: "🗄 Стереть архив чатов",
    EVERYTHING: "🧨 Стереть всё в базе",
    CHAT: "💬 Стереть сообщения в чате",
}
PASSWORD_TTL = 120.0  # сколько секунд ждём пароль после нажатия кнопки
MAX_ATTEMPTS = 5
LOCK_SECONDS = 15 * 60
CHAT_SCAN_LIMIT = 3000  # сколько последних номеров сообщений просматриваем в чате

NO_PASSWORD = (
    "Пароль для стирания не задан. Задайте: <code>/wipe set ваш_пароль</code> "
    f"(от {wipe_repo.MIN_PASSWORD_LENGTH} символов, без пробелов). Сообщение с паролем "
    "бот сразу удалит."
)
CHOOSE = (
    "<b>Стереть данные</b>\n\nУдаление необратимо. Выберите, что стереть, потом введите пароль.\n\n"
    "🗄 архив — сохранённые сообщения собеседников и их правки;\n"
    "🧨 всё в базе — архив, заметки, напоминания и наблюдения;\n"
    "💬 чат — бот удалит свои сообщения и ваши недавние в этом чате "
    "(Telegram разрешает только за последние 48 часов)."
)
ASK_PASSWORD = "Введите пароль одним сообщением ({seconds} с). Оно будет удалено."
LOCKED = "Слишком много неверных паролей. Попробуйте через {minutes} мин."
WRONG = "Неверный пароль. Осталось попыток: {left}."
DONE = {
    ARCHIVE: "🗄 Архив стёрт. Сообщений: {archive}.",
    EVERYTHING: (
        "🧨 Стёрто: архив — {архив}, заметки — {заметки}, напоминания — {напоминания}, "
        "наблюдения — {наблюдения}."
    ),
    CHAT: "💬 Сообщения в чате удалены (всё, что разрешил Telegram).",
}
PASS_SET = "Пароль задан. Сообщение с ним удалено."
PASS_CHANGED = "Пароль сменён. Сообщение с ним удалено."
PASS_USAGE = (
    "Задать пароль: <code>/wipe set новый_пароль</code>. Сменить: "
    "<code>/wipe set старый_пароль новый_пароль</code>. "
    f"От {wipe_repo.MIN_PASSWORD_LENGTH} символов, без пробелов."
)
PASS_SHORT = f"Пароль должен быть не короче {wipe_repo.MIN_PASSWORD_LENGTH} символов."
PASS_OLD_WRONG = "Старый пароль неверен."


class WipeCb(CallbackData, prefix="wipe"):
    action: str


@dataclass
class _Attempts:
    failures: int = 0
    locked_until: float = 0.0


class WipeState:
    """Ожидающие пароля и счётчики неверных попыток (в памяти процесса)."""

    def __init__(self) -> None:
        self.pending: dict[int, tuple[str, float]] = {}
        self.attempts: dict[int, _Attempts] = {}

    def lock_minutes(self, user_id: int) -> int | None:
        locked_until = self.attempts.get(user_id, _Attempts()).locked_until
        left = locked_until - time.monotonic()
        return max(1, int(left // 60) + 1) if left > 0 else None

    def fail(self, user_id: int) -> int:
        """Записать неверную попытку. Возвращает, сколько попыток осталось."""
        state = self.attempts.setdefault(user_id, _Attempts())
        state.failures += 1
        if state.failures >= MAX_ATTEMPTS:
            state.failures = 0
            state.locked_until = time.monotonic() + LOCK_SECONDS
            return 0
        return MAX_ATTEMPTS - state.failures

    def succeed(self, user_id: int) -> None:
        self.attempts.pop(user_id, None)

    def action_for(self, user_id: int) -> str | None:
        entry = self.pending.get(user_id)
        if entry is None:
            return None
        action, expires = entry
        if time.monotonic() > expires:
            self.pending.pop(user_id, None)
            return None
        return action


def keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for action, label in LABELS.items():
        builder.button(text=label, callback_data=WipeCb(action=action))
    builder.adjust(1)
    return builder.as_markup()


async def wipe_chat(bot: Bot, chat_id: int, top_message_id: int) -> None:
    """Удалить сообщения чата, начиная с top_message_id и вниз (что Telegram позволит)."""
    low = max(1, top_message_id - CHAT_SCAN_LIMIT)
    for end in range(top_message_id, low - 1, -100):
        ids = list(range(end, max(low, end - 99) - 1, -1))
        try:
            await bot.delete_messages(chat_id, ids)
        except TelegramAPIError as exc:
            logger.info("delete_messages %s..%s failed: %s", ids[-1], ids[0], exc)
        await asyncio.sleep(0.05)


def create_router() -> Router:
    router = Router(name="wipe")
    state = WipeState()

    async def set_password(message: Message, parts: list[str], user: User, session: AsyncSession):
        # Сообщение с паролем убираем из чата в любом случае.
        try:
            await message.delete()
        except TelegramAPIError:
            logger.info("Could not delete the password message for %s", user.id)
        if user.wipe_password_hash:
            if len(parts) != 2:
                await message.answer(PASS_USAGE, parse_mode="HTML")
                return
            if state.lock_minutes(user.id):
                await message.answer(LOCKED.format(minutes=state.lock_minutes(user.id)))
                return
            if not wipe_repo.check_password(parts[0], user.wipe_password_hash):
                left = state.fail(user.id)
                await message.answer(PASS_OLD_WRONG if left else LOCKED.format(minutes=15))
                return
            state.succeed(user.id)
            new = parts[1]
        else:
            if len(parts) != 1:
                await message.answer(PASS_USAGE, parse_mode="HTML")
                return
            new = parts[0]
        if len(new) < wipe_repo.MIN_PASSWORD_LENGTH:
            await message.answer(PASS_SHORT)
            return
        changed = bool(user.wipe_password_hash)
        user.wipe_password_hash = wipe_repo.hash_password(new)
        await session.commit()
        await message.answer(PASS_CHANGED if changed else PASS_SET)

    async def cmd_wipe(message: Message, command: CommandObject, user: User, session: AsyncSession):
        if message.chat.type != "private":
            return
        parts = (command.args or "").split()
        if parts and parts[0].lower() in ("set", "пароль"):
            await set_password(message, parts[1:], user, session)
            return
        if parts:  # на всякий случай: пароль, набранный сразу после команды, не оставляем
            try:
                await message.delete()
            except TelegramAPIError:
                logger.info("Could not delete the /wipe message for %s", user.id)
        if not user.wipe_password_hash:
            await message.answer(NO_PASSWORD, parse_mode="HTML")
            return
        await message.answer(CHOOSE, reply_markup=keyboard())

    async def on_button(query: CallbackQuery, callback_data: WipeCb, user: User):
        if callback_data.action not in LABELS or not isinstance(query.message, Message):
            await query.answer()
            return
        if not user.wipe_password_hash:
            await query.answer("Сначала задайте пароль: /wipe set", show_alert=True)
            return
        minutes = state.lock_minutes(user.id)
        if minutes:
            await query.answer(LOCKED.format(minutes=minutes), show_alert=True)
            return
        state.pending[user.id] = (callback_data.action, time.monotonic() + PASSWORD_TTL)
        await query.answer()
        await query.message.answer(ASK_PASSWORD.format(seconds=int(PASSWORD_TTL)))

    def waiting_for_password(message: Message) -> bool:
        text = message.text or ""
        user_id = message.from_user.id if message.from_user else 0
        return (
            message.chat.type == "private"
            and bool(text)
            and not text.startswith("/")
            and state.action_for(user_id) is not None
        )

    async def on_password(message: Message, bot: Bot, user: User, session: AsyncSession):
        action = state.action_for(user.id)
        try:
            await message.delete()
        except TelegramAPIError:
            logger.info("Could not delete the password message for %s", user.id)
        if action is None:
            return
        minutes = state.lock_minutes(user.id)
        if minutes:
            state.pending.pop(user.id, None)
            await message.answer(LOCKED.format(minutes=minutes))
            return
        if not wipe_repo.check_password((message.text or "").strip(), user.wipe_password_hash):
            left = state.fail(user.id)
            if left == 0:
                state.pending.pop(user.id, None)
                await message.answer(LOCKED.format(minutes=LOCK_SECONDS // 60))
            else:
                await message.answer(WRONG.format(left=left))
            return
        state.succeed(user.id)
        state.pending.pop(user.id, None)
        if action == ARCHIVE:
            counts = {"archive": await wipe_repo.wipe_archive(session, user.id)}
        elif action == EVERYTHING:
            counts = await wipe_repo.wipe_everything(session, user.id)
        else:
            await wipe_chat(bot, message.chat.id, message.message_id)
            counts = {}
        # Для стирания чата подтверждение придёт уже новым сообщением: оно останется.
        await message.answer(DONE[action].format(**counts))

    router.message.register(cmd_wipe, Command("wipe"))
    router.callback_query.register(on_button, WipeCb.filter())
    router.message.register(on_password, F.text, waiting_for_password)
    return router
