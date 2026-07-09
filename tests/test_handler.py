from __future__ import annotations

import base64
import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

import app.handler as handler_module
from app.handler import handler
from tests.conftest import TEST_WEBHOOK_SECRET

SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"


def _start_update(update_id: int = 100) -> dict[str, Any]:
    return {
        "update_id": update_id,
        "message": {
            "message_id": 1,
            "date": 1700000000,
            "chat": {"id": 42, "type": "private"},
            "from": {"id": 42, "is_bot": False, "first_name": "T"},
            "text": "/start",
            "entities": [{"type": "bot_command", "offset": 0, "length": 6}],
        },
    }


def _event(
    body: str,
    secret: str | None = TEST_WEBHOOK_SECRET,
    base64_encoded: bool = False,
) -> dict[str, Any]:
    headers: dict[str, str] = {}
    if secret is not None:
        headers[SECRET_HEADER] = secret
    if base64_encoded:
        body = base64.b64encode(body.encode("utf-8")).decode("ascii")
    return {
        "httpMethod": "POST",
        "headers": headers,
        "body": body,
        "isBase64Encoded": base64_encoded,
    }


@pytest.fixture
def fake_dispatch(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Подменить тёплые синглтоны бота/диспетчера фейками."""
    dispatcher = AsyncMock(name="Dispatcher")
    monkeypatch.setattr(handler_module, "_dispatcher", dispatcher)
    monkeypatch.setattr(handler_module, "_bot", object())
    feed_update: AsyncMock = dispatcher.feed_update
    return feed_update


def test_valid_update_is_dispatched_and_returns_200(
    env: None, fake_dispatch: AsyncMock
) -> None:
    event = _event(json.dumps(_start_update(update_id=100)))

    response = handler(event, None)

    assert response["statusCode"] == 200
    fake_dispatch.assert_awaited_once()
    assert fake_dispatch.await_args is not None
    _, update = fake_dispatch.await_args.args
    assert update.update_id == 100


def test_base64_encoded_body_is_decoded_and_dispatched(
    env: None, fake_dispatch: AsyncMock
) -> None:
    event = _event(json.dumps(_start_update(update_id=7)), base64_encoded=True)

    response = handler(event, None)

    assert response["statusCode"] == 200
    assert fake_dispatch.await_args is not None
    _, update = fake_dispatch.await_args.args
    assert update.update_id == 7


@pytest.mark.parametrize("secret", ["wrong-secret", None])
def test_bad_or_missing_secret_is_rejected(
    env: None, fake_dispatch: AsyncMock, secret: str | None
) -> None:
    event = _event(json.dumps(_start_update()), secret=secret)

    response = handler(event, None)

    assert response["statusCode"] == 403
    fake_dispatch.assert_not_awaited()


def test_secret_check_is_case_insensitive_header(
    env: None, fake_dispatch: AsyncMock
) -> None:
    event = _event(json.dumps(_start_update()))
    event["headers"] = {"x-telegram-bot-api-secret-token": TEST_WEBHOOK_SECRET}

    response = handler(event, None)

    assert response["statusCode"] == 200
    fake_dispatch.assert_awaited_once()


def test_malformed_body_does_not_raise_and_skips_dispatch(
    env: None, fake_dispatch: AsyncMock
) -> None:
    event = _event("not-a-valid-json{")

    response = handler(event, None)

    assert response["statusCode"] == 200
    fake_dispatch.assert_not_awaited()


def test_valid_json_but_not_an_update_skips_dispatch(
    env: None, fake_dispatch: AsyncMock
) -> None:
    event = _event(json.dumps({"unexpected": "shape"}))

    response = handler(event, None)

    assert response["statusCode"] == 200
    fake_dispatch.assert_not_awaited()


def test_duplicate_update_id_has_no_persistent_effect(
    env: None,
    monkeypatch: pytest.MonkeyPatch,
    fake_dispatch: AsyncMock,
) -> None:
    # Идемпотентность держится тем, что /start не пишет в хранилище.
    import app.ydb_client as ydb_client

    get_pool_spy = AsyncMock(name="get_pool")
    monkeypatch.setattr(ydb_client, "get_pool", get_pool_spy)

    event = _event(json.dumps(_start_update(update_id=555)))

    first = handler(event, None)
    second = handler(event, None)

    assert first["statusCode"] == 200
    assert second["statusCode"] == 200
    # Обработка вебхука не обращается к хранилищу вовсе.
    get_pool_spy.assert_not_called()
