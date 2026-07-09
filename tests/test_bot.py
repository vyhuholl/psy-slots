from __future__ import annotations

from unittest.mock import AsyncMock

from aiogram import Bot, Dispatcher

from app.bot import (
    WELCOME_MESSAGE,
    create_bot,
    create_dispatcher,
    handle_start,
)
from app.config import load_config


def test_create_bot_uses_token_from_config(env: None) -> None:
    config = load_config()

    bot = create_bot(config)

    assert isinstance(bot, Bot)
    assert bot.token == config.bot_token


def test_create_bot_loads_config_when_omitted(env: None) -> None:
    bot = create_bot()

    assert isinstance(bot, Bot)
    assert bot.token == load_config().bot_token


def test_dispatcher_registers_start_handler(env: None) -> None:
    dispatcher = create_dispatcher()

    assert isinstance(dispatcher, Dispatcher)
    assert any(
        handler.callback is handle_start
        for handler in dispatcher.message.handlers
    )


def test_create_dispatcher_returns_independent_instances(env: None) -> None:
    # Общий роутер нельзя привязать дважды; фабрика это исключает.
    first = create_dispatcher()
    second = create_dispatcher()

    assert first is not second


async def test_start_handler_replies_welcome() -> None:
    message = AsyncMock()

    await handle_start(message)

    message.answer.assert_awaited_once_with(WELCOME_MESSAGE)
