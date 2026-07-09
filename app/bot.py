"""Сборка aiogram ``Bot``/``Dispatcher`` и скелетный хендлер ``/start``.

Хендлеры тонкие: доменной логики здесь нет (она появится в доменных
changes и будет вызываться через сервисный слой). Токен бота берётся из
окружения через :mod:`app.config`.
"""

from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.config import Config, load_config

WELCOME_MESSAGE = (
    "Здравствуйте! Это бот записи к психологу. "
    "Скоро здесь появится выбор специалиста и времени."
)


async def handle_start(message: Message) -> None:
    """Ответить приветствием на команду ``/start``."""
    await message.answer(WELCOME_MESSAGE)


def create_bot(config: Config | None = None) -> Bot:
    """Собрать ``Bot`` с токеном из конфигурации."""
    resolved = config if config is not None else load_config()
    return Bot(token=resolved.bot_token)


def create_dispatcher() -> Dispatcher:
    """Собрать ``Dispatcher`` с зарегистрированными хендлерами.

    Хендлеры регистрируются прямо на диспетчере, чтобы каждый вызов давал
    независимый экземпляр (общий роутер нельзя привязать дважды).
    """
    dispatcher = Dispatcher()
    dispatcher.message.register(handle_start, CommandStart())
    return dispatcher
