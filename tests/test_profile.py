import re
import struct
from pathlib import Path

from aiogram.methods import (
    EditMessageText,
    SendPhoto,
    SetChatMenuButton,
    SetMyCommands,
    SetMyDescription,
    SetMyShortDescription,
)
from aiogram.types import (
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    MenuButtonCommands,
)

from tg_assistant.texts import (
    BOT_COMMANDS,
    DESCRIPTION_EN,
    DESCRIPTION_RU,
    GROUP_COMMANDS,
    PRIVATE_ONLY,
    SHORT_EN,
    SHORT_RU,
    command_help,
    welcome,
    with_extra,
)

from .conftest import ALLOWED_ID, edited_texts, sent_methods, sent_texts, update_from

ROOT = Path(__file__).resolve().parents[1]
HANDLERS = ROOT / "src" / "tg_assistant" / "handlers"
ASSETS = ROOT / "src" / "tg_assistant" / "assets"


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    return struct.unpack(">II", data[16:24])


def test_commands_match_real_handlers():
    found = set()
    for path in HANDLERS.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        found.update(re.findall(r'Command\("([a-z]+)"\)', text))
        if "CommandStart()" in text:
            found.add("start")
    assert found == {command.command for command in BOT_COMMANDS}


def test_group_menu_drops_private_only_commands():
    assert PRIVATE_ONLY <= {command.command for command in BOT_COMMANDS}
    assert {command.command for command in GROUP_COMMANDS} == {
        command.command for command in BOT_COMMANDS
    } - PRIVATE_ONLY


def test_profile_texts_fit_telegram_limits():
    assert len(DESCRIPTION_RU) <= 512 and len(DESCRIPTION_EN) <= 512
    assert len(SHORT_RU) <= 120 and len(SHORT_EN) <= 120
    assert all(1 <= len(command.description) <= 256 for command in BOT_COMMANDS)
    caption = with_extra(welcome("А" * 64), command_help())
    assert len(caption) <= 1024
    assert "/archive" in caption and "Привет" in caption


def test_asset_dimensions():
    assert _png_size(ASSETS / "avatar.png") == (640, 640)
    assert _png_size(ASSETS / "description.png") == (640, 360)
    for name in ("home", "notes", "reminders", "archive", "digest", "settings", "app"):
        assert _png_size(ASSETS / "banners" / f"{name}.png") == (1280, 640)
    static = ROOT / "src" / "tg_assistant" / "web" / "static"
    assert _png_size(static / "icon-180.png") == (180, 180)
    assert _png_size(static / "icon-192.png") == (192, 192)
    assert _png_size(static / "icon-512.png") == (512, 512)


async def test_startup_registers_commands_and_descriptions(bot, dp):
    data = {"dispatcher": dp, "bots": [bot], **dp.workflow_data}
    await dp.emit_startup(bot=bot, **data)
    try:
        commands = sent_methods(bot, SetMyCommands)
        private = next(m for m in commands if isinstance(m.scope, BotCommandScopeAllPrivateChats))
        groups = next(m for m in commands if isinstance(m.scope, BotCommandScopeAllGroupChats))
        private_names = {item.command for item in private.commands}
        group_names = {item.command for item in groups.commands}
        assert {
            "note",
            "remind",
            "archive",
            "digest",
            "export",
            "app",
            "web",
            "timezone",
        } <= private_names
        assert "web" not in group_names and "archive" not in group_names
        assert "note" in group_names

        descriptions = sent_methods(bot, SetMyDescription)
        assert any(m.description == DESCRIPTION_RU and not m.language_code for m in descriptions)
        assert any(
            m.language_code == "en" and m.description == DESCRIPTION_EN for m in descriptions
        )
        shorts = sent_methods(bot, SetMyShortDescription)
        assert any(m.short_description == SHORT_RU and not m.language_code for m in shorts)
        assert any(m.language_code == "en" and m.short_description == SHORT_EN for m in shorts)

        (menu,) = sent_methods(bot, SetChatMenuButton)
        assert isinstance(menu.menu_button, MenuButtonCommands)
    finally:
        await dp.emit_shutdown(bot=bot, **data)


async def test_start_menu_navigates_back(bot, dp):
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/start"))
    photo = sent_methods(bot, SendPhoto)[0]
    labels = [button.text for row in photo.reply_markup.inline_keyboard for button in row]
    assert labels[:5] == [
        "📝 Заметки",
        "⏰ Напоминания",
        "🗄 Архив чатов",
        "☀️ Сводка",
        "⚙️ Настройки",
    ]
    assert labels[5] == "📱 Мини-приложение"
    assert "Привет, Аня" in photo.caption

    notes = next(
        button
        for row in photo.reply_markup.inline_keyboard
        for button in row
        if "Заметки" in button.text
    )
    await dp.feed_update(bot, _callback(notes.callback_data))
    screen = sent_methods(bot, EditMessageText)[-1]
    assert "Заметки" in screen.text
    back = next(
        button
        for row in screen.reply_markup.inline_keyboard
        for button in row
        if "Назад" in button.text
    )
    await dp.feed_update(bot, _callback(back.callback_data))
    assert "Привет, Аня" in edited_texts(bot)[-1]


async def test_reply_keyboard_opens_notes(bot, dp):
    await dp.feed_update(bot, update_from(ALLOWED_ID, "📝 Заметки"))
    assert "Заметок пока нет" in sent_texts(bot)[-1]


def _callback(data: str):
    from .conftest import callback_from

    return callback_from(ALLOWED_ID, data)
