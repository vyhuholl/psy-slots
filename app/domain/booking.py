"""Доменная модель брони и её ошибки.

Бронь — самостоятельная персистентная сущность с неизменным UUID и
явными ``start``/``end`` в UTC (а не «слот в статусе занят»): слоты
эфемерны, бронь — нет. Модель неизменяема; «переход состояния» —
построение нового экземпляра. Здесь нет ни YDB, ни Telegram — только
чистый домен, тестируемый в изоляции.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, replace
from datetime import datetime


class BookingStatus(enum.Enum):
    """Состояние брони. «Свободен» = отсутствие активной брони."""

    BOOKED = "booked"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class Booking:
    """Неизменяемая бронь с явными границами в UTC.

    ``end`` денормализуется при создании (``start + длительность``), чтобы
    позднее изменение длительности не сдвигало существующие записи.
    """

    id: str
    client_id: int
    start: datetime
    end: datetime
    status: BookingStatus
    created_at: datetime
    cancelled_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        """Активна ли бронь (в состоянии ``booked``)."""
        return self.status is BookingStatus.BOOKED

    def cancelled(self, at: datetime) -> Booking:
        """Вернуть новую бронь в состоянии ``cancelled`` (без мутации)."""
        return replace(self, status=BookingStatus.CANCELLED, cancelled_at=at)


class BookingError(RuntimeError):
    """Базовая доменная ошибка брони."""


class SlotNotToday(BookingError):
    """Слот не на сегодня: другой день или уже прошедшее время."""


class SlotOutsideAvailability(BookingError):
    """Слот не попадает ни в один интервал доступности."""


class SlotMisaligned(BookingError):
    """Слот не выровнен по сетке или выходит за конец интервала."""


class SlotTaken(BookingError):
    """Слот пересекается с активной бронью (двойное бронирование)."""


class BookingNotFound(BookingError):
    """Бронь с указанным id не найдена."""
