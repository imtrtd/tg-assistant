from aiogram.types import TelegramObject, Update


def is_business_chat_update(event: TelegramObject) -> bool:
    """Сообщение из личного чата владельца, пришедшее через Telegram Business.

    Отправитель такого апдейта — собеседник владельца (или сам владелец). Это не
    пользователь бота: ему нельзя отвечать и его не нужно регистрировать. Владельца
    находит обработчик по business_connection_id.
    """
    return isinstance(event, Update) and (
        event.business_message is not None
        or event.edited_business_message is not None
        or event.deleted_business_messages is not None
    )
