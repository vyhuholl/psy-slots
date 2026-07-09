"""Тесты чистого ядра генерации слотов (`app/domain/slots.py`).

Ядро без I/O: сетка слотов внутри окон доступности с шагом длительности,
материализация локального времени в UTC и политика DST. Всё детерминировано
и тестируется без сети и Telegram.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.availability import AvailabilityInterval
from app.domain.slots import Slot, generate


def _interval(
    weekday: int,
    start_minute: int,
    end_minute: int,
    *,
    id_: str = "int-1",
    specialist_id: str = "spec-1",
) -> AvailabilityInterval:
    return AvailabilityInterval(
        id=id_,
        specialist_id=specialist_id,
        weekday=weekday,
        start_minute=start_minute,
        end_minute=end_minute,
    )


def _utc(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


# --- 1. Сетка слотов -------------------------------------------------------


def test_slots_step_by_duration() -> None:
    # Вторник 2026-07-07, интервал 10:00–11:00, шаг 15 минут (tz=UTC).
    slots = generate(
        specialist_id="spec-1",
        intervals=[_interval(1, 600, 660)],
        duration_minutes=15,
        timezone="UTC",
        window_start=_utc(2026, 7, 7, 0, 0),
        window_end=_utc(2026, 7, 8, 0, 0),
    )

    assert [s.start_utc for s in slots] == [
        _utc(2026, 7, 7, 10, 0),
        _utc(2026, 7, 7, 10, 15),
        _utc(2026, 7, 7, 10, 30),
        _utc(2026, 7, 7, 10, 45),
    ]
    assert all(s.end_utc - s.start_utc == timedelta(minutes=15) for s in slots)
    assert all(s.specialist_id == "spec-1" for s in slots)


def test_no_tail_slot_beyond_interval_end() -> None:
    # Интервал 10:00–10:50, шаг 15: хвостовой 10:45–11:00 не влезает.
    slots = generate(
        specialist_id="spec-1",
        intervals=[_interval(1, 600, 650)],
        duration_minutes=15,
        timezone="UTC",
        window_start=_utc(2026, 7, 7, 0, 0),
        window_end=_utc(2026, 7, 8, 0, 0),
    )

    assert [s.start_utc for s in slots] == [
        _utc(2026, 7, 7, 10, 0),
        _utc(2026, 7, 7, 10, 15),
        _utc(2026, 7, 7, 10, 30),
    ]


def test_slot_is_immutable() -> None:
    slot = Slot(
        specialist_id="spec-1",
        start_utc=_utc(2026, 7, 7, 10, 0),
        end_utc=_utc(2026, 7, 7, 10, 15),
    )

    # setattr обходит статическую проверку; frozen роняет во время выполнения.
    with pytest.raises(FrozenInstanceError):
        setattr(slot, "start_utc", _utc(2026, 7, 7, 11, 0))


def test_slots_ordered_by_start() -> None:
    # Два интервала того же дня, поданы в обратном порядке — выдача сортирована.
    late = _interval(1, 780, 810, id_="int-late")  # 13:00–13:30
    early = _interval(1, 600, 630, id_="int-early")  # 10:00–10:30
    slots = generate(
        specialist_id="spec-1",
        intervals=[late, early],
        duration_minutes=30,
        timezone="UTC",
        window_start=_utc(2026, 7, 7, 0, 0),
        window_end=_utc(2026, 7, 8, 0, 0),
    )

    starts = [s.start_utc for s in slots]
    assert starts == sorted(starts)
    assert starts == [_utc(2026, 7, 7, 10, 0), _utc(2026, 7, 7, 13, 0)]


# --- 2. Материализация в UTC и DST ----------------------------------------


def test_local_interval_materialized_to_utc_only_on_matching_weekday() -> None:
    # Europe/Moscow (UTC+3, без DST); интервал только на вторник.
    slots = generate(
        specialist_id="spec-1",
        intervals=[_interval(1, 600, 660)],  # вт 10:00–11:00 локально
        duration_minutes=15,
        timezone="Europe/Moscow",
        window_start=_utc(2026, 7, 6, 0, 0),  # понедельник
        window_end=_utc(2026, 7, 9, 0, 0),  # четверг
    )

    # Единственный вторник в окне — 2026-07-07; 10:00 MSK == 07:00 UTC.
    assert [s.start_utc for s in slots] == [
        _utc(2026, 7, 7, 7, 0),
        _utc(2026, 7, 7, 7, 15),
        _utc(2026, 7, 7, 7, 30),
        _utc(2026, 7, 7, 7, 45),
    ]
    assert slots[0].end_utc == _utc(2026, 7, 7, 7, 15)


def test_nonexistent_local_time_skipped_on_spring_forward() -> None:
    # 2026-03-29 Берлин: 02:00→03:00 «дыра». Интервал 01:30–03:00, шаг 30:
    # кандидаты 01:30 (есть), 02:00 и 02:30 (не существуют) — пропущены.
    slots = generate(
        specialist_id="spec-1",
        intervals=[_interval(6, 90, 180)],  # вс 01:30–03:00 локально
        duration_minutes=30,
        timezone="Europe/Berlin",
        window_start=_utc(2026, 3, 29, 0, 0),
        window_end=_utc(2026, 3, 30, 0, 0),
    )

    # 01:30 CET (UTC+1) == 00:30 UTC; несуществующие слоты не порождены.
    assert [s.start_utc for s in slots] == [_utc(2026, 3, 29, 0, 30)]


def test_ambiguous_local_time_yields_single_slot_on_fall_back() -> None:
    # 2026-10-25 Берлин: 02:00 повторяется дважды. Интервал 02:00–02:30:
    # ровно один слот (fold=0, первое вхождение), без дубля.
    slots = generate(
        specialist_id="spec-1",
        intervals=[_interval(6, 120, 150)],  # вс 02:00–02:30 локально
        duration_minutes=30,
        timezone="Europe/Berlin",
        window_start=_utc(2026, 10, 25, 0, 0),
        window_end=_utc(2026, 10, 26, 0, 0),
    )

    # fold=0 == первое вхождение (CEST, UTC+2) == 00:00 UTC.
    assert len(slots) == 1
    assert slots[0].start_utc == _utc(2026, 10, 25, 0, 0)


def test_empty_when_no_intervals() -> None:
    assert (
        generate(
            specialist_id="spec-1",
            intervals=[],
            duration_minutes=15,
            timezone="UTC",
            window_start=_utc(2026, 7, 7, 0, 0),
            window_end=_utc(2026, 7, 8, 0, 0),
        )
        == []
    )
