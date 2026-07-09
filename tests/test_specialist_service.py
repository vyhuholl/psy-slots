from __future__ import annotations

import uuid
from typing import Any

import pytest

import app.services.specialist_service as service_module
from app.domain.specialist import SpecialistNotFound, ValidationError
from app.services.specialist_service import SpecialistService


class _FakeResultSet:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows


class FakePool:
    """Мини-YDB в памяти: разбирает запросы сервиса по их SQL-константам.

    Даёт сквозное поведение (register → get → update → list) без сети,
    оставаясь замоканным пулом, как требует дизайн.
    """

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.queries: list[str] = []

    @staticmethod
    def _value(param: Any) -> Any:
        # Сервис передаёт параметры в форме (value, ydb-тип).
        return param[0]

    def execute_with_retries(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> list[_FakeResultSet]:
        self.queries.append(query)
        params = parameters or {}

        if query == service_module._UPSERT:
            row = {
                "id": self._value(params["$id"]),
                "name": self._value(params["$name"]),
                "slot_duration_minutes": self._value(
                    params["$slot_duration_minutes"]
                ),
                "timezone": self._value(params["$timezone"]),
                "created_at": self._value(params["$created_at"]),
            }
            self.rows[row["id"]] = row
            return []
        if query == service_module._SELECT_ALL:
            return [_FakeResultSet(list(self.rows.values()))]
        if query == service_module._SELECT_BY_ID:
            wanted = self._value(params["$id"])
            found = [r for r in self.rows.values() if r["id"] == wanted]
            return [_FakeResultSet(found)]
        if query == service_module._UPDATE_DURATION:
            self.rows[self._value(params["$id"])]["slot_duration_minutes"] = (
                self._value(params["$slot_duration_minutes"])
            )
            return []
        if query == service_module._UPDATE_TIMEZONE:
            self.rows[self._value(params["$id"])]["timezone"] = self._value(
                params["$timezone"]
            )
            return []
        raise AssertionError(f"unexpected query: {query!r}")


def _service() -> tuple[SpecialistService, FakePool]:
    pool = FakePool()
    return SpecialistService(pool=pool), pool


def test_register_persists_and_get_returns_saved_values() -> None:
    service, _ = _service()

    created = service.register(
        name="Анна", slot_duration_minutes=15, timezone="Europe/Moscow"
    )

    # id — сгенерированный uuid4 (парсится без ошибки).
    assert uuid.UUID(created.id).version == 4

    fetched = service.get(created.id)
    assert fetched == created
    assert fetched is not None
    assert fetched.name == "Анна"
    assert fetched.slot_duration_minutes == 15
    assert fetched.timezone == "Europe/Moscow"


def test_register_rejects_invalid_input_without_writing() -> None:
    service, pool = _service()

    with pytest.raises(ValidationError):
        service.register(
            name="Анна", slot_duration_minutes=0, timezone="Europe/Moscow"
        )
    with pytest.raises(ValidationError):
        service.register(
            name="Анна", slot_duration_minutes=15, timezone="Not/AZone"
        )

    assert pool.rows == {}


def test_list_returns_all_regardless_of_count() -> None:
    service, _ = _service()

    assert service.list() == []

    first = service.register(
        name="Анна", slot_duration_minutes=15, timezone="Europe/Moscow"
    )
    assert service.list() == [first]

    second = service.register(
        name="Борис", slot_duration_minutes=30, timezone="UTC"
    )
    by_id = {s.id: s for s in service.list()}
    assert by_id == {first.id: first, second.id: second}


def test_get_unknown_id_returns_none() -> None:
    service, _ = _service()

    assert service.get(str(uuid.uuid4())) is None


def test_update_duration_and_timezone_persist() -> None:
    service, _ = _service()
    created = service.register(
        name="Анна", slot_duration_minutes=15, timezone="Europe/Moscow"
    )

    updated_duration = service.update_duration(created.id, 30)
    assert updated_duration.slot_duration_minutes == 30
    reread = service.get(created.id)
    assert reread is not None
    assert reread.slot_duration_minutes == 30

    updated_tz = service.update_timezone(created.id, "Asia/Tbilisi")
    assert updated_tz.timezone == "Asia/Tbilisi"
    reread = service.get(created.id)
    assert reread is not None
    assert reread.timezone == "Asia/Tbilisi"


def test_update_unknown_id_raises_not_found_and_creates_nothing() -> None:
    service, pool = _service()
    missing = str(uuid.uuid4())

    with pytest.raises(SpecialistNotFound):
        service.update_duration(missing, 30)
    with pytest.raises(SpecialistNotFound):
        service.update_timezone(missing, "UTC")

    assert service.list() == []
    assert pool.rows == {}


def test_update_invalid_value_is_rejected_and_not_saved() -> None:
    service, _ = _service()
    created = service.register(
        name="Анна", slot_duration_minutes=15, timezone="Europe/Moscow"
    )

    with pytest.raises(ValidationError):
        service.update_duration(created.id, 0)
    with pytest.raises(ValidationError):
        service.update_timezone(created.id, "Not/AZone")

    reread = service.get(created.id)
    assert reread is not None
    assert reread.slot_duration_minutes == 15
    assert reread.timezone == "Europe/Moscow"


def test_service_uses_warm_pool_when_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = FakePool()
    monkeypatch.setattr(service_module, "get_pool", lambda: pool)

    service = SpecialistService()
    created = service.register(
        name="Анна", slot_duration_minutes=15, timezone="Europe/Moscow"
    )

    assert created.id in pool.rows
