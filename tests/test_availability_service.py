from __future__ import annotations

import uuid
from typing import Any

import pytest

import app.services.availability_service as service_module
from app.domain.availability import IntervalOverlap
from app.domain.specialist import Specialist, SpecialistNotFound
from app.services.availability_service import AvailabilityService


class _FakeResultSet:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows


class FakePool:
    """Мини-YDB в памяти: разбирает запросы сервиса по их SQL-константам."""

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
                "specialist_id": self._value(params["$specialist_id"]),
                "weekday": self._value(params["$weekday"]),
                "start_minute": self._value(params["$start_minute"]),
                "end_minute": self._value(params["$end_minute"]),
            }
            self.rows[row["id"]] = row
            return []
        if query == service_module._SELECT_BY_SPECIALIST:
            wanted = self._value(params["$specialist_id"])
            found = [
                r for r in self.rows.values() if r["specialist_id"] == wanted
            ]
            return [_FakeResultSet(found)]
        if query == service_module._DELETE_BY_ID:
            self.rows.pop(self._value(params["$id"]), None)
            return []
        raise AssertionError(f"unexpected query: {query!r}")


class FakeSpecialists:
    """Замоканный лукап специалиста: знает лишь заданные id."""

    def __init__(self, known: set[str]) -> None:
        self._known = known

    def get(self, specialist_id: str) -> Specialist | None:
        if specialist_id not in self._known:
            return None
        return Specialist(
            id=specialist_id,
            name="Анна",
            slot_duration_minutes=15,
            timezone="Europe/Moscow",
        )


def _service(
    known: set[str] | None = None,
) -> tuple[AvailabilityService, FakePool]:
    pool = FakePool()
    specialists = FakeSpecialists(known if known is not None else {"spec-1"})
    return AvailabilityService(pool=pool, specialists=specialists), pool


def test_add_interval_persists_with_uuid_and_appears_in_list() -> None:
    service, _ = _service()

    created = service.add_interval(
        specialist_id="spec-1",
        weekday=1,
        start_minute=600,
        end_minute=840,
    )

    # id — сгенерированный uuid4 (парсится без ошибки).
    assert uuid.UUID(created.id).version == 4
    assert created.specialist_id == "spec-1"
    assert created.weekday == 1
    assert created.start_minute == 600
    assert created.end_minute == 840

    assert service.list("spec-1") == [created]


def test_add_interval_for_unknown_specialist_raises_and_saves_nothing() -> (
    None
):
    service, pool = _service(known=set())

    with pytest.raises(SpecialistNotFound):
        service.add_interval(
            specialist_id="ghost",
            weekday=1,
            start_minute=600,
            end_minute=840,
        )

    assert pool.rows == {}


def test_overlapping_interval_same_weekday_rejected() -> None:
    service, pool = _service()
    service.add_interval(
        specialist_id="spec-1",
        weekday=1,
        start_minute=600,
        end_minute=840,
    )

    with pytest.raises(IntervalOverlap):
        service.add_interval(
            specialist_id="spec-1",
            weekday=1,
            start_minute=800,
            end_minute=900,
        )

    # Пересечение не сохранилось: остался лишь первый интервал.
    assert len(pool.rows) == 1


def test_overlap_check_is_scoped_to_same_weekday() -> None:
    service, _ = _service()
    service.add_interval(
        specialist_id="spec-1", weekday=1, start_minute=600, end_minute=840
    )

    # Тот же диапазон в другой день недели — не пересечение.
    other_day = service.add_interval(
        specialist_id="spec-1", weekday=2, start_minute=600, end_minute=840
    )

    assert other_day in service.list("spec-1")


def test_adjacent_interval_saved() -> None:
    service, _ = _service()
    service.add_interval(
        specialist_id="spec-1",
        weekday=1,
        start_minute=600,
        end_minute=840,
    )

    # Смежный: начало == концу существующего, без перекрытия.
    adjacent = service.add_interval(
        specialist_id="spec-1",
        weekday=1,
        start_minute=840,
        end_minute=1000,
    )

    assert adjacent in service.list("spec-1")
    assert len(service.list("spec-1")) == 2


def test_remove_interval_drops_it_from_list() -> None:
    service, _ = _service()
    created = service.add_interval(
        specialist_id="spec-1",
        weekday=1,
        start_minute=600,
        end_minute=840,
    )

    service.remove_interval(created.id)

    assert service.list("spec-1") == []


def test_list_empty_when_no_intervals() -> None:
    service, _ = _service()

    assert service.list("spec-1") == []


def test_list_returns_only_that_specialist_intervals() -> None:
    service, _ = _service(known={"spec-1", "spec-2"})
    mine = service.add_interval(
        specialist_id="spec-1", weekday=1, start_minute=600, end_minute=840
    )
    other = service.add_interval(
        specialist_id="spec-2", weekday=3, start_minute=60, end_minute=120
    )

    listed = service.list("spec-1")
    assert listed == [mine]
    assert other not in listed


def test_service_uses_warm_pool_when_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = FakePool()
    monkeypatch.setattr(service_module, "get_pool", lambda: pool)
    specialists = FakeSpecialists({"spec-1"})

    service = AvailabilityService(specialists=specialists)
    created = service.add_interval(
        specialist_id="spec-1", weekday=1, start_minute=600, end_minute=840
    )

    assert created.id in pool.rows
