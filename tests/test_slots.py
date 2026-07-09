from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.domain.slots import Slot, generate_slots

_MOSCOW = ZoneInfo("Europe/Moscow")  # UTC+3, без DST
_NEW_YORK = ZoneInfo("America/New_York")  # с DST


def _hm(hour: int, minute: int = 0) -> int:
    """Минуты от полуночи для ``HH:MM``."""
    return hour * 60 + minute


def test_slots_step_by_duration() -> None:
    # Интервал 10:00–11:00, длительность 20 → 10:00, 10:20, 10:40 (местное).
    slots = generate_slots(
        day=date(2026, 7, 9),
        intervals=[(_hm(10), _hm(11))],
        duration_minutes=20,
        tz=_MOSCOW,
    )

    starts = [s.start for s in slots]
    assert starts == [
        datetime(2026, 7, 9, 7, 0, tzinfo=UTC),  # 10:00 MSK
        datetime(2026, 7, 9, 7, 20, tzinfo=UTC),  # 10:20 MSK
        datetime(2026, 7, 9, 7, 40, tzinfo=UTC),  # 10:40 MSK
    ]
    assert all(s.end == s.start + timedelta(minutes=20) for s in slots)


def test_tail_slot_not_generated() -> None:
    # Интервал 10:00–10:50, длительность 20 → 10:00, 10:20; хвост 10:40 нет.
    slots = generate_slots(
        day=date(2026, 7, 9),
        intervals=[(_hm(10), _hm(10, 50))],
        duration_minutes=20,
        tz=_MOSCOW,
    )

    assert [s.start for s in slots] == [
        datetime(2026, 7, 9, 7, 0, tzinfo=UTC),
        datetime(2026, 7, 9, 7, 20, tzinfo=UTC),
    ]


def test_slots_are_materialized_in_utc() -> None:
    slots = generate_slots(
        day=date(2026, 7, 9),
        intervals=[(_hm(10), _hm(10, 20))],
        duration_minutes=20,
        tz=_MOSCOW,
    )

    (slot,) = slots
    assert slot.start.tzinfo is UTC
    assert slot.end.tzinfo is UTC
    # 10:00 MSK == 07:00 UTC.
    assert slot.start == datetime(2026, 7, 9, 7, 0, tzinfo=UTC)


def test_multiple_intervals_sorted_by_start() -> None:
    slots = generate_slots(
        day=date(2026, 7, 9),
        intervals=[(_hm(15), _hm(15, 20)), (_hm(10), _hm(10, 20))],
        duration_minutes=20,
        tz=_MOSCOW,
    )

    assert [s.start for s in slots] == sorted(s.start for s in slots)
    assert len(slots) == 2


def test_spring_forward_skips_nonexistent_local_time() -> None:
    # 2026-03-08, America/New_York: 02:00 → 03:00 (весенний переход).
    # Интервал 01:00–04:00, длительность 60 → 01:00, (02:00 нет), 03:00.
    slots = generate_slots(
        day=date(2026, 3, 8),
        intervals=[(_hm(1), _hm(4))],
        duration_minutes=60,
        tz=_NEW_YORK,
    )

    assert [s.start for s in slots] == [
        datetime(2026, 3, 8, 6, 0, tzinfo=UTC),  # 01:00 EST (UTC-5)
        datetime(2026, 3, 8, 7, 0, tzinfo=UTC),  # 03:00 EDT (UTC-4)
    ]


def test_fall_back_yields_single_slot_for_ambiguous_time() -> None:
    # 2026-11-01, America/New_York: 02:00 → 01:00 (осенний переход).
    # 01:00 неоднозначно; MUST дать ровно один слот (fold=0, первое вхождение).
    slots = generate_slots(
        day=date(2026, 11, 1),
        intervals=[(_hm(1), _hm(2))],
        duration_minutes=60,
        tz=_NEW_YORK,
    )

    assert len(slots) == 1
    # Первое вхождение 01:00 — ещё EDT (UTC-4) → 05:00 UTC.
    assert slots[0].start == datetime(2026, 11, 1, 5, 0, tzinfo=UTC)


def test_no_intervals_yields_no_slots() -> None:
    assert (
        generate_slots(
            day=date(2026, 7, 9),
            intervals=[],
            duration_minutes=20,
            tz=_MOSCOW,
        )
        == []
    )


def test_slot_is_immutable() -> None:
    slot = Slot(
        start=datetime(2026, 7, 9, 7, 0, tzinfo=UTC),
        end=datetime(2026, 7, 9, 7, 20, tzinfo=UTC),
    )
    try:
        slot.start = datetime(2026, 7, 9, 8, 0, tzinfo=UTC)  # type: ignore[misc]
    except AttributeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("Slot должен быть неизменяемым")
