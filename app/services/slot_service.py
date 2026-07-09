"""Сервис-оркестратор свободных слотов над чистым ядром генерации.

Единственный вход к списку свободных слотов: берёт длительность, таймзону и
интервалы доступности из конфигурации, зовёт чистое ядро
(:func:`app.domain.slots.generate_slots`) на сегодняшнюю дату, отбрасывает уже
прошедшие слоты (``start ≥ now``) и вычитает слоты, пересекающиеся с активными
бронями. Выдача упорядочена по началу и пуста, когда на сегодня свободных
будущих слотов не осталось.

Слоты эфемерны и нигде не сохраняются; выдача совещательная — финальную защиту
от двойного бронирования даёт `booking-lifecycle` при записи. Зависимость от
броней задана как ``Protocol``, чтобы сервис тестировался без YDB.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol

from app.config import Config
from app.domain.booking import Booking
from app.domain.slots import Slot, generate_slots


class BookingReader(Protocol):
    """Чтение активных (``booked``) броней с началом в диапазоне UTC."""

    def list_active_in_range(
        self, range_start: datetime, range_end: datetime
    ) -> list[Booking]: ...


def _overlaps(slot: Slot, booking: Booking) -> bool:
    """Пересечение полуоткрытых диапазонов ``[start, end)``.

    Смежные (конец брони == начало слота) пересечением не считаются.
    """
    return slot.start < booking.end and booking.start < slot.end


class SlotService:
    """Единый слой выдачи свободных слотов на сегодня."""

    def __init__(self, config: Config, bookings: BookingReader) -> None:
        self._config = config
        self._bookings = bookings

    def list_free_slots(self, *, now: datetime | None = None) -> list[Slot]:
        """Свободные будущие слоты сегодняшнего дня в UTC, по возрастанию.

        Слоты, чьё ``[start, end)`` пересекается с активной бронью, исключены.
        Прошедшие сегодня слоты (``start < now``) исключены. Когда свободных
        будущих слотов на сегодня нет — пустой список (без ошибки).
        """
        now_utc = (
            datetime.now(UTC)
            if now is None
            else now.astimezone(UTC)
            if now.tzinfo is not None
            else now.replace(tzinfo=UTC)
        )
        tz = self._config.timezone
        today = now_utc.astimezone(tz).date()

        intervals = [
            (interval.start_minute, interval.end_minute)
            for interval in self._config.availability_intervals
        ]
        slots = generate_slots(
            day=today,
            intervals=intervals,
            duration_minutes=self._config.slot_duration_minutes,
            tz=tz,
        )
        future = [slot for slot in slots if slot.start >= now_utc]
        if not future:
            return []

        day_start_local = datetime(
            today.year, today.month, today.day, tzinfo=tz
        )
        day_start_utc = day_start_local.astimezone(UTC)
        day_end_utc = (day_start_local + timedelta(days=1)).astimezone(UTC)
        booked = self._bookings.list_active_in_range(
            day_start_utc, day_end_utc
        )

        return [
            slot
            for slot in future
            if not any(_overlaps(slot, booking) for booking in booked)
        ]
