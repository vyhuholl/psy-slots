from __future__ import annotations

from unittest.mock import MagicMock

from aiogram import Bot, Dispatcher

from app.bot import create_bot, create_dispatcher
from app.bot.handlers.client import handle_start
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


def _message_callbacks(dispatcher: Dispatcher) -> list[object]:
    return [
        handler.callback
        for router in dispatcher.sub_routers
        for handler in router.message.handlers
    ]


def test_dispatcher_registers_client_start_handler(env: None) -> None:
    dispatcher = create_dispatcher()

    assert isinstance(dispatcher, Dispatcher)
    assert handle_start in _message_callbacks(dispatcher)


def test_create_dispatcher_returns_independent_instances(env: None) -> None:
    # Общий роутер нельзя привязать дважды; фабрика даёт свежий роутер.
    first = create_dispatcher()
    second = create_dispatcher()

    assert first is not second


def test_create_dispatcher_injects_services_as_workflow_data(
    env: None,
) -> None:
    config = load_config()
    client_service = MagicMock()
    slot_service = MagicMock()
    booking_service = MagicMock()

    dispatcher = create_dispatcher(
        config=config,
        client_service=client_service,
        slot_service=slot_service,
        booking_service=booking_service,
    )

    assert dispatcher.workflow_data["config"] is config
    assert dispatcher.workflow_data["client_service"] is client_service
    assert dispatcher.workflow_data["slot_service"] is slot_service
    assert dispatcher.workflow_data["booking_service"] is booking_service
