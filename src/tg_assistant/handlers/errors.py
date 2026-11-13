import logging

from aiogram.types import ErrorEvent

logger = logging.getLogger(__name__)

ERROR_TEXT = "Что-то пошло не так. Попробуйте ещё раз чуть позже."


async def on_error(event: ErrorEvent) -> bool:
    """Логирует необработанное исключение и сообщает пользователю об ошибке."""
    logger.exception(
        "Unhandled error in update %s", event.update.update_id, exc_info=event.exception
    )
    update = event.update
    try:
        if update.message is not None:
            await update.message.answer(ERROR_TEXT)
        elif update.callback_query is not None:
            await update.callback_query.answer(ERROR_TEXT, show_alert=True)
    except Exception:
        logger.exception("Failed to notify user about error")
    return True
