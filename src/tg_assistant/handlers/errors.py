import html
import logging
import time
import traceback

from aiogram import Bot
from aiogram.types import ErrorEvent

from ..config import Settings

logger = logging.getLogger(__name__)

ERROR_TEXT = "Что-то пошло не так. Попробуйте ещё раз чуть позже."
ALERT_INTERVAL = 60.0  # не чаще раза в минуту, чтобы при сбое не завалить чат админа
TRACE_LIMIT = 2500  # после экранирования; плюс заголовок — с запасом меньше 4096

# None — оповещений ещё не было. Не 0.0: monotonic() считает от загрузки системы,
# и сразу после перезагрузки сервера первое оповещение было бы ошибочно подавлено.
_last_alert: float | None = None


def format_alert(event: ErrorEvent) -> str:
    exc = event.exception
    raw = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    trace = html.escape(raw)
    # Обрезаем исходный текст (не экранированный — так не разорвём сущность вроде &lt;),
    # пока после экранирования он не влезет. Конец трассировки полезнее начала.
    if len(trace) > TRACE_LIMIT:
        raw = raw[-TRACE_LIMIT:]
        while len(html.escape(raw)) > TRACE_LIMIT:
            raw = raw[len(raw) // 10 :]
        trace = "…" + html.escape(raw)
    return (
        f"⚠️ <b>Ошибка в боте</b> (update {event.update.update_id})\n"
        f"<code>{html.escape(type(exc).__name__)}: {html.escape(str(exc)[:200])}</code>\n\n"
        f"<pre>{trace}</pre>"
    )


async def notify_admins(bot: Bot, admin_ids, event: ErrorEvent) -> None:
    global _last_alert
    now = time.monotonic()
    if not admin_ids or (_last_alert is not None and now - _last_alert < ALERT_INTERVAL):
        return
    _last_alert = now
    text = format_alert(event)
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML")
        except Exception:
            logger.exception("Failed to notify admin %s about error", admin_id)


async def on_error(
    event: ErrorEvent, bot: Bot | None = None, settings: Settings | None = None
) -> bool:
    """Логирует необработанное исключение, сообщает пользователю и администраторам."""
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
    if bot is not None and settings is not None:
        await notify_admins(bot, settings.admin_ids, event)
    return True
