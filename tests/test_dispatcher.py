from tg_assistant.db import User

from .conftest import ALLOWED_ID, sent_texts, update_from


async def test_start_from_allowed_user_registers_and_greets(bot, dp, session_factory):
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/start"))

    assert "Привет, Аня" in sent_texts(bot)[0]
    async with session_factory() as session:
        assert await session.get(User, ALLOWED_ID) is not None


async def test_stranger_is_denied_and_not_registered(bot, dp, session_factory):
    await dp.feed_update(bot, update_from(7, "/start"))

    assert "Доступ к боту закрыт" in sent_texts(bot)[0]
    async with session_factory() as session:
        assert await session.get(User, 7) is None


async def test_handler_error_reported_to_user(bot, dp, monkeypatch):
    from tg_assistant.handlers import common

    monkeypatch.setattr(common, "HELP_TEXT", None)  # answer(None) -> validation error
    await dp.feed_update(bot, update_from(ALLOWED_ID, "/help"))

    assert sent_texts(bot) == ["Что-то пошло не так. Попробуйте ещё раз чуть позже."]


async def test_startup_starts_and_shutdown_stops_scheduler(bot, dp):
    data = {"dispatcher": dp, "bots": [bot], **dp.workflow_data}

    await dp.emit_startup(bot=bot, **data)
    task = dp.workflow_data["scheduler_task"]
    assert not task.done()

    await dp.emit_shutdown(bot=bot, **data)
    assert task.cancelled()
    assert "scheduler_task" not in dp.workflow_data
