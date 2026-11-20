"""Проверка, что команда пришла от пользователя из белого списка.

Сами апдейты отсекает AccessMiddleware. Функция остаётся для правил и тестов:
пустой список никого не пускает.
"""

from collections.abc import Container


def is_allowed(user_id: int | None, allowed_ids: Container[int]) -> bool:
    return user_id is not None and user_id in allowed_ids
