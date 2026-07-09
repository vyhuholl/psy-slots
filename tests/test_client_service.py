from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from app.domain.client import InvalidTimezone
from app.services.client_service import ClientService

NOW = datetime(2026, 7, 9, 6, 0, tzinfo=UTC)
OLD = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)


class _FakeResultSet:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows


def _is_write(query: str) -> bool:
    return "UPSERT" in query.upper() or "UPDATE" in query.upper()


class _FakeTx:
    def __init__(self, select_rows: list[dict[str, Any]]) -> None:
        self._select_rows = select_rows
        self.queries: list[tuple[str, dict[str, Any]]] = []

    def execute(
        self, query: str, parameters: dict[str, Any] | None = None
    ) -> list[_FakeResultSet]:
        self.queries.append((query, parameters or {}))
        if _is_write(query):
            return [_FakeResultSet([])]
        return [_FakeResultSet(list(self._select_rows))]


class _FakePool:
    def __init__(
        self,
        *,
        select_rows: list[dict[str, Any]] | None = None,
        read_rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self.tx = _FakeTx(select_rows or [])
        self._read_rows = read_rows or []
        self.read_queries: list[tuple[str, dict[str, Any]]] = []

    def retry_tx_sync(
        self,
        callee: Callable[[_FakeTx], Any],
        tx_mode: Any = None,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        return callee(self.tx)

    def execute_with_retries(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> list[_FakeResultSet]:
        self.read_queries.append((query, parameters or {}))
        return [_FakeResultSet(list(self._read_rows))]


def _client_row(
    *,
    telegram_id: int = 42,
    timezone: str = "Europe/Moscow",
    created_at: datetime = OLD,
) -> dict[str, Any]:
    return {
        "telegram_id": telegram_id,
        "timezone": timezone,
        "created_at": created_at,
    }


def _writes(pool: _FakePool) -> list[tuple[str, dict[str, Any]]]:
    return [q for q in pool.tx.queries if _is_write(q[0])]


def test_set_timezone_upserts_and_returns_client() -> None:
    pool = _FakePool()
    service = ClientService(pool)

    client = service.set_timezone(42, "Europe/Moscow", now=NOW)

    assert client.telegram_id == 42
    assert client.timezone == "Europe/Moscow"
    writes = _writes(pool)
    assert writes, "ожидался UPSERT профиля"
    params = writes[0][1]
    assert params["$telegram_id"].value == 42
    assert params["$timezone"].value == "Europe/Moscow"


def test_set_timezone_rejects_invalid_without_writing() -> None:
    pool = _FakePool()
    service = ClientService(pool)

    with pytest.raises(InvalidTimezone):
        service.set_timezone(42, "Mars/Phobos", now=NOW)

    assert _writes(pool) == []


def test_set_timezone_preserves_existing_created_at() -> None:
    pool = _FakePool(select_rows=[_client_row(created_at=OLD)])
    service = ClientService(pool)

    client = service.set_timezone(42, "Asia/Omsk", now=NOW)

    # created_at не «сбрасывается» при смене таймзоны.
    assert client.created_at == OLD


def test_get_returns_stored_client() -> None:
    pool = _FakePool(read_rows=[_client_row()])
    service = ClientService(pool)

    client = service.get(42)

    assert client is not None
    assert client.timezone == "Europe/Moscow"


def test_get_unknown_client_returns_none() -> None:
    pool = _FakePool(read_rows=[])
    service = ClientService(pool)

    assert service.get(999) is None
