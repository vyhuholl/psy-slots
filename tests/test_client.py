from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.domain.client import Client, InvalidTimezone

NOW = datetime(2026, 7, 9, 6, 0, tzinfo=UTC)


def test_client_accepts_valid_iana_timezone() -> None:
    client = Client(telegram_id=42, timezone="Europe/Moscow", created_at=NOW)

    assert client.telegram_id == 42
    assert client.timezone == "Europe/Moscow"
    assert client.zoneinfo == ZoneInfo("Europe/Moscow")


def test_client_rejects_invalid_timezone() -> None:
    with pytest.raises(InvalidTimezone):
        Client(telegram_id=42, timezone="Mars/Phobos", created_at=NOW)


def test_client_rejects_empty_timezone() -> None:
    with pytest.raises(InvalidTimezone):
        Client(telegram_id=42, timezone="", created_at=NOW)


def test_client_is_immutable() -> None:
    client = Client(telegram_id=42, timezone="Europe/Moscow", created_at=NOW)
    try:
        client.timezone = "UTC"  # type: ignore[misc]
    except AttributeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("Client должен быть неизменяемым")
