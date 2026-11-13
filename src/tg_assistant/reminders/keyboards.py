from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..db import Reminder

SNOOZE_OPTIONS = [(10, "⏰ 10 мин"), (60, "⏰ 1 час")]


class RemCb(CallbackData, prefix="rem"):
    action: str  # "done" | "snooze" | "del"
    reminder_id: int
    minutes: int = 0


def fired_keyboard(reminder: Reminder) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Готово", callback_data=RemCb(action="done", reminder_id=reminder.id))
    for minutes, label in SNOOZE_OPTIONS:
        kb.button(
            text=label,
            callback_data=RemCb(action="snooze", reminder_id=reminder.id, minutes=minutes),
        )
    return kb.as_markup()
