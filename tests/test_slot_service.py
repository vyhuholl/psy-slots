"""Тесты сервиса-оркестратора свободных слотов (`app/services/slot_service.py`).

Репозитории (реестр, расписание, брони) замоканы. Сервис тянет длительность и
TZ специалиста, интервалы и активные брони, зовёт чистое ядро, вычитает
пересечения с активными бронями и фильтрует по окну. Без YDB и Telegram.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from app.domain.availability import AvailabilityInterval
from app.domain.specialist import Specialist, SpecialistNotFound
from app.services.slot_service import SlotService


@dataclass(frozen=True)
class _Booking:
    """Минимальная активная бронь: только UTC-границы, нужные сервису."""

    start_utc: datetime
    end_utc: datetime


class FakeSpecialists:
    def __init__(self, specialist: Specialist | None) -> None:
        self._specialist = specialist

    def get(self, specialist_id: str) -> Specialist | None:
        if self._specialist is None or self._specialist.id != specialist_id:
            return None
        return self._specialist


class FakeAvailability:
    def __init__(self, intervals: list[AvailabilityInterval]) -> None:
        self._intervals = intervals

    def list(self, specialist_id: str) -> list[AvailabilityInterval]:
        return [i for i in self._intervals if i.specialist_id == specialist_id]


class FakeBookings:
    def __init__(self, bookings: list[_Booking]) -> None:
        self._bookings = bookings
        self.calls: list[tuple[str, datetime, datetime]] = []

    def list_active_for_specialist(
        self,
        specialist_id: str,
        window_start: datetime,
        window_end: datetime,
    ) -> list[_Booking]:
        self.calls.append((specialist_id, window_start, window_end))
        return list(self._bookings)


def _utc(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def _specialist(
    duration: int = 15, timezone: str = "Europe/Moscow"
) -> Specialist:
    return Specialist(
        id="spec-1",
        name="Анна",
        slot_duration_minutes=duration,
        timezone=timezone,
    )


def _tuesday_interval() -> AvailabilityInterval:
    # Вт 10:00–11:00 MSK → 07:00–08:00 UTC; слоты 07:00/07:15/07:30/07:45.
    return AvailabilityInterval(
        id="int-1",
        specialist_id="spec-1",
        weekday=1,
        start_minute=600,
        end_minute=660,
    )


def _service(
    *,
    specialist: Specialist | None,
    intervals: list[AvailabilityInterval],
    bookings: list[_Booking],
) -> tuple[SlotService, FakeBookings]:
    fake_bookings = FakeBookings(bookings)
    service = SlotService(
        specialists=FakeSpecialists(specialist),
        availability=FakeAvailability(intervals),
        bookings=fake_bookings,
    )
    return service, fake_bookings


def test_slot_overlapping_active_booking_is_excluded() -> None:
    # Активная бронь 07:15–07:30 UTC убирает слот 07:15; смежная граница —
    # слот 07:30 (начинается ровно в конце брони) остаётся.
    service, _ = _service(
        specialist=_specialist(),
        intervals=[_tuesday_interval()],
        bookings=[_Booking(_utc(2026, 7, 7, 7, 15), _utc(2026, 7, 7, 7, 30))],
    )

    starts = [
        s.start_utc
        for s in service.list_free_slots(
            "spec-1", _utc(2026, 7, 7, 0, 0), _utc(2026, 7, 8, 0, 0)
        )
    ]

    assert starts == [
        _utc(2026, 7, 7, 7, 0),
        _utc(2026, 7, 7, 7, 30),
        _utc(2026, 7, 7, 7, 45),
    ]


def test_cancelled_booking_leaves_slot_free() -> None:
    # Отменённая бронь не входит в активные → слот снова свободен.
    service, bookings = _service(
        specialist=_specialist(),
        intervals=[_tuesday_interval()],
        bookings=[],  # отменённых среди активных нет
    )

    starts = [
        s.start_utc
        for s in service.list_free_slots(
            "spec-1", _utc(2026, 7, 7, 7, 0), _utc(2026, 7, 7, 7, 30)
        )
    ]

    assert starts == [_utc(2026, 7, 7, 7, 0), _utc(2026, 7, 7, 7, 15)]
    assert bookings.calls  # активные брони были запрошены


def test_window_filter_is_half_open() -> None:
    # Окно [07:15, 07:45): только 07:15 ≤ start < 07:45, упорядочено.
    service, _ = _service(
        specialist=_specialist(),
        intervals=[_tuesday_interval()],
        bookings=[],
    )

    starts = [
        s.start_utc
        for s in service.list_free_slots(
            "spec-1", _utc(2026, 7, 7, 7, 15), _utc(2026, 7, 7, 7, 45)
        )
    ]

    assert starts == [_utc(2026, 7, 7, 7, 15), _utc(2026, 7, 7, 7, 30)]


def test_empty_when_no_availability() -> None:
    # Нет интервалов → пустая выдача; активные брони даже не запрашиваются.
    service, bookings = _service(
        specialist=_specialist(),
        intervals=[],
        bookings=[],
    )

    result = service.list_free_slots(
        "spec-1", _utc(2026, 7, 7, 0, 0), _utc(2026, 7, 8, 0, 0)
    )

    assert result == []
    assert bookings.calls == []


def test_empty_when_no_dates_in_window() -> None:
    # Интервал во вторник, но окно покрывает только среду → пусто, без ошибки.
    service, _ = _service(
        specialist=_specialist(),
        intervals=[_tuesday_interval()],
        bookings=[],
    )

    result = service.list_free_slots(
        "spec-1", _utc(2026, 7, 8, 0, 0), _utc(2026, 7, 9, 0, 0)
    )

    assert result == []


def test_unknown_specialist_raises() -> None:
    service, _ = _service(
        specialist=None,
        intervals=[],
        bookings=[],
    )

    with pytest.raises(SpecialistNotFound):
        service.list_free_slots(
            "ghost", _utc(2026, 7, 7, 0, 0), _utc(2026, 7, 8, 0, 0)
        )
