"""Сервис-оркестратор свободных слотов над чистым ядром генерации.

Единственный вход к списку свободных слотов специалиста: тянет из реестра
длительность и таймзону, из расписания — интервалы доступности, из брони —
активные брони в окне, зовёт чистое ядро (:func:`app.domain.slots.generate`),
вычитает слоты, пересекающиеся с активными бронями, и отдаёт упорядоченную по
началу выдачу. Слоты эфемерны и нигде не сохраняются; выдача совещательная —
финальную защиту от двойного бронирования даёт `booking-lifecycle` при записи.

Хендлеры Telegram обращаются только сюда. Зависимости заданы как ``Protocol``,
чтобы сервис тестировался с замоканными репозиториями без YDB.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from app.domain.availability import AvailabilityInterval
from app.domain.slots import Slot, generate
from app.domain.specialist import Specialist, SpecialistNotFound
from app.services.availability_service import AvailabilityService
from app.services.specialist_service import SpecialistService


class SpecialistLookup(Protocol):
    """Минимальный лукап реестра: длительность и TZ специалиста."""

    def get(self, specialist_id: str) -> Specialist | None: ...


class AvailabilityLookup(Protocol):
    """Минимальный лукап расписания: интервалы доступности специалиста."""

    def list(self, specialist_id: str) -> list[AvailabilityInterval]: ...


class ActiveBooking(Protocol):
    """Активная бронь глазами генерации слотов — только UTC-границы."""

    @property
    def start_utc(self) -> datetime: ...

    @property
    def end_utc(self) -> datetime: ...


class BookingLookup(Protocol):
    """Чтение активных (`booked`) броней специалиста в окне времени."""

    def list_active_for_specialist(
        self,
        specialist_id: str,
        window_start: datetime,
        window_end: datetime,
    ) -> Sequence[ActiveBooking]: ...


def _overlaps(slot: Slot, booking: ActiveBooking) -> bool:
    """Пересечение полуоткрытых диапазонов ``[start, end)``.

    Смежные (конец брони == начало слота) пересечением не считаются.
    """
    return (
        slot.start_utc < booking.end_utc and booking.start_utc < slot.end_utc
    )


class SlotService:
    """Единый слой выдачи свободных слотов специалиста."""

    def __init__(
        self,
        *,
        bookings: BookingLookup,
        specialists: SpecialistLookup | None = None,
        availability: AvailabilityLookup | None = None,
    ) -> None:
        self._bookings = bookings
        self._specialists: SpecialistLookup = (
            specialists if specialists is not None else SpecialistService()
        )
        self._availability: AvailabilityLookup = (
            availability if availability is not None else AvailabilityService()
        )

    def list_free_slots(
        self,
        specialist_id: str,
        window_start: datetime,
        window_end: datetime,
    ) -> list[Slot]:
        """Вернуть свободные слоты специалиста в окне ``[start, end)`` в UTC.

        Слоты, чьё ``[start, end)`` пересекается с активной бронью, исключены.
        Выдача упорядочена по началу; при отсутствии доступности или дат в окне
        — пуста. Неизвестный специалист → :class:`SpecialistNotFound`.
        """
        specialist = self._specialists.get(specialist_id)
        if specialist is None:
            raise SpecialistNotFound(specialist_id)

        slots = generate(
            specialist_id=specialist_id,
            intervals=self._availability.list(specialist_id),
            duration_minutes=specialist.slot_duration_minutes,
            timezone=specialist.timezone,
            window_start=window_start,
            window_end=window_end,
        )
        if not slots:
            return []

        booked = self._bookings.list_active_for_specialist(
            specialist_id, window_start, window_end
        )
        return [
            slot
            for slot in slots
            if not any(_overlaps(slot, booking) for booking in booked)
        ]
