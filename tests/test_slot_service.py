from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.config import Config, load_config
from app.domain.booking import Booking, BookingStatus
from app.services.slot_service import SlotService

# Europe/Moscow = UTC+3 (без DST). Локальное 10:00 = 07:00 UTC.
# Интервалы из conftest: 10:00–14:00, 15:00–18:00; длительность 20 мин.
_TODAY_09MSK = datetime(2026, 7, 9, 6, 0, tzinfo=UTC)  # Москва 09:00 07-09


class _FakeBookings:
    """Читатель активных броней: отдаёт заданный список, запоминает запрос."""

    def __init__(self, bookings: list[Booking] | None = None) -> None:
        self._bookings = bookings or []
        self.range_calls: list[tuple[datetime, datetime]] = []

    def list_active_in_range(
        self, range_start: datetime, range_end: datetime
    ) -> list[Booking]:
        self.range_calls.append((range_start, range_end))
        return list(self._bookings)


def _booking(start: datetime, *, minutes: int = 20) -> Booking:
    return Booking(
        id="11111111-1111-4111-8111-111111111111",
        client_id=42,
        start=start,
        end=start + timedelta(minutes=minutes),
        status=BookingStatus.BOOKED,
        created_at=start,
    )


@pytest.fixture
def config(env: None) -> Config:
    return load_config()


def test_lists_only_todays_future_slots_in_utc(config: Config) -> None:
    service = SlotService(config, _FakeBookings())

    slots = service.list_free_slots(now=_TODAY_09MSK)

    assert slots, "ожидались слоты на сегодня"
    # Все слоты — сегодня (07-09) в таймзоне конфигурации и в будущем.
    for slot in slots:
        assert slot.start.tzinfo is UTC
        assert slot.start.astimezone(config.timezone).date() == (
            _TODAY_09MSK.astimezone(config.timezone).date()
        )
        assert slot.start >= _TODAY_09MSK
    # Первый слот — 10:00 MSK = 07:00 UTC.
    assert slots[0].start == datetime(2026, 7, 9, 7, 0, tzinfo=UTC)


def test_slots_sorted_ascending(config: Config) -> None:
    service = SlotService(config, _FakeBookings())

    slots = service.list_free_slots(now=_TODAY_09MSK)

    assert [s.start for s in slots] == sorted(s.start for s in slots)


def test_past_slots_today_excluded(config: Config) -> None:
    # Москва 12:30 — слоты до 12:30 уже прошли.
    now = datetime(2026, 7, 9, 9, 30, tzinfo=UTC)  # 12:30 MSK
    service = SlotService(config, _FakeBookings())

    slots = service.list_free_slots(now=now)

    assert slots
    assert all(s.start >= now for s in slots)
    # Первый доступный — 12:40 MSK = 09:40 UTC.
    assert slots[0].start == datetime(2026, 7, 9, 9, 40, tzinfo=UTC)


def test_booked_slot_is_excluded(config: Config) -> None:
    taken = datetime(2026, 7, 9, 7, 0, tzinfo=UTC)  # 10:00 MSK
    service = SlotService(config, _FakeBookings([_booking(taken)]))

    slots = service.list_free_slots(now=_TODAY_09MSK)

    assert taken not in [s.start for s in slots]
    # Соседний свободный слот остаётся.
    assert datetime(2026, 7, 9, 7, 20, tzinfo=UTC) in [s.start for s in slots]


def test_cancelled_booking_frees_slot(config: Config) -> None:
    # Читатель активных броней не возвращает отменённые → слот снова свободен.
    service = SlotService(config, _FakeBookings([]))

    slots = service.list_free_slots(now=_TODAY_09MSK)

    assert datetime(2026, 7, 9, 7, 0, tzinfo=UTC) in [s.start for s in slots]


def test_empty_when_all_todays_slots_passed(config: Config) -> None:
    # Москва 19:00 — оба интервала (…–18:00) уже позади.
    now = datetime(2026, 7, 9, 16, 0, tzinfo=UTC)  # 19:00 MSK
    service = SlotService(config, _FakeBookings())

    assert service.list_free_slots(now=now) == []


def test_bookings_queried_within_today_window(config: Config) -> None:
    bookings = _FakeBookings()
    service = SlotService(config, bookings)

    service.list_free_slots(now=_TODAY_09MSK)

    assert bookings.range_calls, "сервис должен запросить брони на сегодня"
    range_start, range_end = bookings.range_calls[0]
    assert range_start < range_end
    # Окно покрывает сегодняшний день в UTC.
    assert range_start <= _TODAY_09MSK < range_end
