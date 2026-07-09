"""Чистое ядро генерации свободных слотов — эфемерная read-модель.

Без I/O и без персистентности: внутри каждого интервала недельного расписания
порождаются слоты с шагом = длительность специалиста (полуоткрытая сетка
``t + D ≤ end``, без «хвостового» слота за концом интервала), затем локальное
настенное время интервалов материализуется в конкретные UTC-моменты для дат
запрошенного окна, чей день недели совпадает с днём интервала.

Это единственное место, где решается перевод локального→UTC, поэтому здесь же
зафиксирована политика DST: несуществующее локальное время (весенний переход)
пропускается, неоднозначное (осенний переход) даёт ровно один слот (``fold=0``).
Оркестрация (реестр, расписание, брони) — в сервисном слое, не здесь.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.domain.availability import AvailabilityInterval

_MINUTES_PER_HOUR = 60
_ONE_DAY = timedelta(days=1)


@dataclass(frozen=True, slots=True)
class Slot:
    """Неизменяемый эфемерный слот с явными ``start``/``end`` в UTC.

    Слоты нигде не хранятся — вычисляются на лету из расписания и длительности.
    ``start_utc`` и ``end_utc`` всегда timezone-aware в UTC.
    """

    specialist_id: str
    start_utc: datetime
    end_utc: datetime


def _slot_start_minutes(
    start_minute: int, end_minute: int, duration: int
) -> Iterator[int]:
    """Минуты начала слотов в интервале: полуоткрытая сетка ``t + D ≤ end``."""
    minute = start_minute
    while minute + duration <= end_minute:
        yield minute
        minute += duration


def _window_dates(
    window_start: datetime, window_end: datetime
) -> Iterator[date]:
    """Локальные даты, покрывающие окно с запасом ±1 день.

    Запас снимает off-by-one на границах суток из-за смещения таймзоны:
    локальная дата специалиста может смещать свои слоты в UTC-окно соседнего
    дня. Финальный фильтр по UTC-окну отсекает лишнее.
    """
    day = (window_start - _ONE_DAY).date()
    last = (window_end + _ONE_DAY).date()
    while day <= last:
        yield day
        day += _ONE_DAY


def _materialize(
    specialist_id: str,
    day: date,
    interval: AvailabilityInterval,
    duration: int,
    tz: ZoneInfo,
) -> Iterator[Slot]:
    """Материализовать слоты интервала на конкретную дату в UTC.

    Локальное время строится в таймзоне специалиста; проверка существования —
    round-trip (UTC→локаль): если настенное время не совпало, локального
    момента не существует (весенний переход) — слот пропускается. Для
    неоднозначного часа берётся ``fold=0`` — одно детерминированное вхождение.
    """
    for minute in _slot_start_minutes(
        interval.start_minute, interval.end_minute, duration
    ):
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
            specialist_id=specialist_id,
            start_utc=start_utc,
            end_utc=start_utc + timedelta(minutes=duration),
        )


def generate(
    *,
    specialist_id: str,
    intervals: Sequence[AvailabilityInterval],
    duration_minutes: int,
    timezone: str,
    window_start: datetime,
    window_end: datetime,
) -> list[Slot]:
    """Породить свободные слоты специалиста в окне ``[window_start, window_end)``.

    Возвращает слоты, чьё ``start_utc`` попадает в окно, упорядоченные по
    возрастанию ``start_utc``. Занятость бронями здесь не учитывается — это
    забота сервисного слоя. Слоты нигде не персистятся.
    """
    tz = ZoneInfo(timezone)
    by_weekday: dict[int, list[AvailabilityInterval]] = {}
    for interval in intervals:
        by_weekday.setdefault(interval.weekday, []).append(interval)

    slots = [
        slot
        for day in _window_dates(window_start, window_end)
        for interval in by_weekday.get(day.weekday(), ())
        for slot in _materialize(
            specialist_id, day, interval, duration_minutes, tz
        )
        if window_start <= slot.start_utc < window_end
    ]
    slots.sort(key=lambda slot: slot.start_utc)
    return slots
