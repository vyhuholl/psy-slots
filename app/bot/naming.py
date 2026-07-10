"""Человекочитаемое имя клиента из данных Telegram.

Имена нигде не хранятся (профиля клиента нет) — берутся вживую через
``bot.get_chat``. Формат по приоритету: ``Имя Фамилия (@username)`` →
``@username`` (если нет имени) → ``telegram_id`` (если нет username). Любой сбой
``get_chat`` деградирует до ``telegram_id`` без ошибки в потоке.
"""

from __future__ import annotations

from aiogram import Bot


async def resolve_client_name(bot: Bot, client_id: int) -> str:
    """Вернуть человекочитаемое имя клиента (fallback — ``telegram_id``)."""
    try:
        chat = await bot.get_chat(client_id)
    except Exception:
        return str(client_id)

    username = getattr(chat, "username", None)
    if username:
        first = getattr(chat, "first_name", None)
        last = getattr(chat, "last_name", None)
        full = " ".join(part for part in (first, last) if part)
        return f"{full} (@{username})" if full else f"@{username}"
    return str(client_id)
