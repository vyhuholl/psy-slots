from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from app.bot.naming import resolve_client_name

CLIENT_ID = 123456


def _bot(chat: Any = None, *, raises: bool = False) -> Any:
    bot = SimpleNamespace()
    if raises:
        bot.get_chat = AsyncMock(side_effect=RuntimeError("chat unavailable"))
    else:
        bot.get_chat = AsyncMock(return_value=chat)
    return bot


async def test_name_with_first_last_and_username() -> None:
    chat = SimpleNamespace(
        first_name="Иван", last_name="Иванов", username="ivanov"
    )

    name = await resolve_client_name(_bot(chat), CLIENT_ID)

    assert name == "Иван Иванов (@ivanov)"


async def test_name_with_first_only_and_username() -> None:
    chat = SimpleNamespace(
        first_name="Иван", last_name=None, username="ivanov"
    )

    name = await resolve_client_name(_bot(chat), CLIENT_ID)

    assert name == "Иван (@ivanov)"


async def test_name_username_only_when_no_first_name() -> None:
    chat = SimpleNamespace(first_name=None, last_name=None, username="ivanov")

    name = await resolve_client_name(_bot(chat), CLIENT_ID)

    assert name == "@ivanov"


async def test_name_falls_back_to_id_without_username() -> None:
    chat = SimpleNamespace(first_name="Иван", last_name=None, username=None)

    name = await resolve_client_name(_bot(chat), CLIENT_ID)

    assert name == str(CLIENT_ID)


async def test_name_falls_back_to_id_on_get_chat_error() -> None:
    name = await resolve_client_name(_bot(raises=True), CLIENT_ID)

    assert name == str(CLIENT_ID)
