"""Чистое ядро генерации свободных слотов — эфемерная read-модель.

Без I/O и без персистентности: внутри каждого интервала доступности (время
суток, без дня недели — психолог один) порождаются слоты с шагом = длительность
слота (полуоткрытая сетка ``t + D ≤ end``, без «хвостового» слота за концом
интервала), затем локальное настенное время интервалов материализуется в
конкретные UTC-моменты для заданной даты.

Это единственное место, где решается перевод локального→UTC, поэтому здесь же
зафиксирована политика DST: несуществующее локальное время (весенний переход)
пропускается, неоднозначное (осенний переход) даёт ровно один слот (``fold=0``).
Фильтрация «сегодня/будущее/занятость» — забота сервисного слоя, не ядра.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

_MINUTES_PER_HOUR = 60


@dataclass(frozen=True, slots=True)
class Slot:
    """Неизменяемый эфемерный слот с явными ``start``/``end`` в UTC.

    Слоты нигде не хранятся — вычисляются на лету из интервалов и длительности.
    ``start`` и ``end`` всегда timezone-aware в UTC.
    """

    start: datetime
    end: datetime


def _slot_start_minutes(
    start_minute: int, end_minute: int, duration: int
) -> Iterator[int]:
    """Минуты начала слотов в интервале: полуоткрытая сетка ``t + D ≤ end``."""
    minute = start_minute
    while minute + duration <= end_minute:
        yield minute
        minute += duration


def _materialize(
    day: date,
    start_minute: int,
    end_minute: int,
    duration: int,
    tz: ZoneInfo,
) -> Iterator[Slot]:
    """Материализовать слоты интервала на конкретную дату в UTC.

    Локальное время строится в таймзоне конфигурации; существование
    проверяется round-trip (UTC→локаль): если настенное время не совпало,
    локального момента не существует (весенний переход) — слот пропускается.
    Для неоднозначного часа берётся ``fold=0`` — одно детерминированное
    вхождение (без дубликата).
    """
    for minute in _slot_start_minutes(start_minute, end_minute, duration):
        hour, minute_of_hour = divmod(minute, _MINUTES_PER_HOUR)
        local = datetime(
            day.year, day.month, day.day, hour, minute_of_hour, tzinfo=tz
        )
        start_utc = local.astimezone(UTC)
        if start_utc.astimezone(tz).replace(tzinfo=None) != local.replace(
            tzinfo=None
        ):
            continue  # несуществующее локальное время — пропуск
        yield Slot(
            start=start_utc,
            end=start_utc + timedelta(minutes=duration),
        )


def generate_slots(
    *,
    day: date,
    intervals: Sequence[tuple[int, int]],
    duration_minutes: int,
    tz: ZoneInfo,
) -> list[Slot]:
    """Породить слоты на ``day`` внутри ``intervals`` (минуты от полуночи).

    Возвращает слоты, упорядоченные по возрастанию ``start`` (в UTC). Занятость
    бронями и фильтр «сегодня/будущее» здесь не учитываются — это забота
    сервисного слоя. Слоты нигде не персистятся.
    """
    slots = [
        slot
        for start_minute, end_minute in intervals
        for slot in _materialize(
            day, start_minute, end_minute, duration_minutes, tz
        )
    ]
    slots.sort(key=lambda slot: slot.start)
    return slots
