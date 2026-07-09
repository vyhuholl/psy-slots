"""Единый доменный сервис переходов состояния брони над YDB.

Все переходы (создание, отмена) и чтение проходят через этот слой, а не
инлайн в aiogram-хендлерах: доменная логика тестируется без Telegram.
Сервис читает длительность/таймзону/интервалы из конфигурации (``bot-config``),
денормализует ``end`` при создании, валидирует «сегодня + окно + сетка» и
защищает от двойного бронирования сериализуемой транзакцией YDB.

Время везде в UTC; окно доступности проверяется в таймзоне конфигурации.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import ydb

from app.config import Config
from app.domain.booking import (
    Booking,
    BookingNotFound,
    BookingStatus,
    SlotMisaligned,
    SlotNotToday,
    SlotOutsideAvailability,
    SlotTaken,
)

_US_PER_MINUTE = 60_000_000
_US_PER_DAY = 24 * 60 * _US_PER_MINUTE

_COLUMNS = (
    "id, client_id, start_utc, end_utc, status, created_at, cancelled_at"
)

_SELECT_OVERLAP = """
DECLARE $start_utc AS Timestamp;
DECLARE $end_utc AS Timestamp;
SELECT id FROM bookings
WHERE status = 'booked' AND start_utc < $end_utc AND end_utc > $start_utc;
"""

_UPSERT_BOOKING = """
DECLARE $id AS Utf8;
DECLARE $client_id AS Int64;
DECLARE $start_utc AS Timestamp;
DECLARE $end_utc AS Timestamp;
DECLARE $status AS Utf8;
DECLARE $created_at AS Timestamp;
UPSERT INTO bookings (id, client_id, start_utc, end_utc, status, created_at)
VALUES ($id, $client_id, $start_utc, $end_utc, $status, $created_at);
"""

_SELECT_BY_ID = f"""
DECLARE $id AS Utf8;
SELECT {_COLUMNS} FROM bookings WHERE id = $id;
"""

_UPDATE_CANCEL = """
DECLARE $id AS Utf8;
DECLARE $cancelled_at AS Timestamp;
UPDATE bookings SET status = 'cancelled', cancelled_at = $cancelled_at
WHERE id = $id;
"""

_SELECT_ACTIVE_IN_RANGE = f"""
DECLARE $range_start AS Timestamp;
DECLARE $range_end AS Timestamp;
SELECT {_COLUMNS} FROM bookings
WHERE status = 'booked'
  AND start_utc >= $range_start AND start_utc < $range_end;
"""

_SELECT_ACTIVE_FOR_CLIENT = f"""
DECLARE $client_id AS Int64;
SELECT {_COLUMNS} FROM bookings
WHERE status = 'booked' AND client_id = $client_id;
"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    """Привести момент к tz-aware UTC (naive трактуется как UTC)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _microsecond_of_day(dt: datetime) -> int:
    """Микросекунды от полуночи по настенным часам (без учёта DST)."""
    seconds = (dt.hour * 60 + dt.minute) * 60 + dt.second
    return seconds * 1_000_000 + dt.microsecond


def _ts(value: datetime) -> Any:
    return ydb.TypedValue(value, ydb.PrimitiveType.Timestamp)


def _utf8(value: str) -> Any:
    return ydb.TypedValue(value, ydb.PrimitiveType.Utf8)


def _int64(value: int) -> Any:
    return ydb.TypedValue(value, ydb.PrimitiveType.Int64)


def _collect_rows(result_sets: Iterable[Any]) -> list[Any]:
    rows: list[Any] = []
    for result_set in result_sets:
        rows.extend(result_set.rows)
    return rows


def _row_to_booking(row: Any) -> Booking:
    cancelled_raw = row["cancelled_at"]
    return Booking(
        id=row["id"],
        client_id=row["client_id"],
        start=_as_utc(row["start_utc"]),
        end=_as_utc(row["end_utc"]),
        status=BookingStatus(row["status"]),
        created_at=_as_utc(row["created_at"]),
        cancelled_at=(
            _as_utc(cancelled_raw) if cancelled_raw is not None else None
        ),
    )


class BookingService:
    """Создание, отмена и чтение броней над пулом сессий YDB."""

    def __init__(self, config: Config, pool: ydb.QuerySessionPool) -> None:
        self._config = config
        self._pool = pool

    # --- Создание ----------------------------------------------------------

    def create(
        self,
        client_id: int,
        start: datetime,
        *,
        now: datetime | None = None,
    ) -> Booking:
        """Создать бронь на слот ``start`` (UTC), провалидировав окно.

        Проверяет «сегодня + интервал доступности + сетка», денормализует
        ``end`` и вставляет строку в сериализуемой транзакции, отклоняя
        пересечение с активной бронью (``SlotTaken``).
        """
        now_utc = _utcnow() if now is None else _as_utc(now)
        start_utc = _as_utc(start)
        self._validate_window(start_utc, now_utc)

        duration = timedelta(minutes=self._config.slot_duration_minutes)
        end_utc = start_utc + duration
        booking = Booking(
            id=str(uuid4()),
            client_id=client_id,
            start=start_utc,
            end=end_utc,
            status=BookingStatus.BOOKED,
            created_at=now_utc,
            cancelled_at=None,
        )

        def _insert(tx: Any) -> None:
            overlap = _collect_rows(
                tx.execute(
                    _SELECT_OVERLAP,
                    {"$start_utc": _ts(start_utc), "$end_utc": _ts(end_utc)},
                )
            )
            if overlap:
                raise SlotTaken(f"Slot {start_utc.isoformat()} is taken")
            tx.execute(
                _UPSERT_BOOKING,
                {
                    "$id": _utf8(booking.id),
                    "$client_id": _int64(client_id),
                    "$start_utc": _ts(start_utc),
                    "$end_utc": _ts(end_utc),
                    "$status": _utf8(booking.status.value),
                    "$created_at": _ts(now_utc),
                },
            )

        try:
            self._pool.retry_tx_sync(
                _insert, tx_mode=ydb.QuerySerializableReadWrite()
            )
        except ydb.issues.Aborted as exc:
            # Проигравший конкурентный коммит (Transaction Locks Invalidated)
            # трактуется как «слот занят».
            raise SlotTaken(f"Slot {start_utc.isoformat()} is taken") from exc
        return booking

    def _validate_window(self, start_utc: datetime, now_utc: datetime) -> None:
        tz = self._config.timezone
        duration = self._config.slot_duration_minutes
        local_start = start_utc.astimezone(tz)
        local_end = (start_utc + timedelta(minutes=duration)).astimezone(tz)
        local_now = now_utc.astimezone(tz)

        if local_start.date() != local_now.date() or start_utc < now_utc:
            raise SlotNotToday(
                f"Slot {local_start.isoformat()} is not today or has passed"
            )

        start_us = _microsecond_of_day(local_start)
        end_us = _microsecond_of_day(local_end)
        if local_end.date() != local_start.date():
            end_us += _US_PER_DAY
        duration_us = duration * _US_PER_MINUTE

        for interval in self._config.availability_intervals:
            interval_start_us = interval.start_minute * _US_PER_MINUTE
            interval_end_us = interval.end_minute * _US_PER_MINUTE
            if interval_start_us <= start_us and end_us <= interval_end_us:
                if (start_us - interval_start_us) % duration_us != 0:
                    raise SlotMisaligned(
                        f"Slot {local_start.isoformat()} is off the grid"
                    )
                return
        raise SlotOutsideAvailability(
            f"Slot {local_start.isoformat()} is outside availability"
        )

    # --- Отмена ------------------------------------------------------------

    def cancel(
        self, booking_id: str, *, now: datetime | None = None
    ) -> Booking:
        """Отменить бронь (soft-переход ``booked → cancelled``).

        Идемпотентна: повторная отмена уже отменённой брони — успех без
        второго эффекта. Неизвестный id — ``BookingNotFound``. Строка
        никогда не удаляется.
        """
        now_utc = _utcnow() if now is None else _as_utc(now)

        def _cancel(tx: Any) -> Booking:
            rows = _collect_rows(
                tx.execute(_SELECT_BY_ID, {"$id": _utf8(booking_id)})
            )
            if not rows:
                raise BookingNotFound(booking_id)
            booking = _row_to_booking(rows[0])
            if booking.status is BookingStatus.CANCELLED:
                return booking
            tx.execute(
                _UPDATE_CANCEL,
                {"$id": _utf8(booking_id), "$cancelled_at": _ts(now_utc)},
            )
            return booking.cancelled(now_utc)

        result: Booking = self._pool.retry_tx_sync(
            _cancel, tx_mode=ydb.QuerySerializableReadWrite()
        )
        return result

    # --- Чтение ------------------------------------------------------------

    def get(self, booking_id: str) -> Booking | None:
        """Вернуть бронь по id или ``None``, если не найдена."""
        rows = _collect_rows(
            self._pool.execute_with_retries(
                _SELECT_BY_ID, {"$id": _utf8(booking_id)}
            )
        )
        if not rows:
            return None
        return _row_to_booking(rows[0])

    def list_active_in_range(
        self, range_start: datetime, range_end: datetime
    ) -> list[Booking]:
        """Активные (``booked``) брони с началом в ``[start, end)``."""
        rows = _collect_rows(
            self._pool.execute_with_retries(
                _SELECT_ACTIVE_IN_RANGE,
                {
                    "$range_start": _ts(_as_utc(range_start)),
                    "$range_end": _ts(_as_utc(range_end)),
                },
            )
        )
        return [_row_to_booking(row) for row in rows]

    def list_active_for_client(self, client_id: int) -> list[Booking]:
        """Активные (``booked``) брони указанного клиента."""
        rows = _collect_rows(
            self._pool.execute_with_retries(
                _SELECT_ACTIVE_FOR_CLIENT, {"$client_id": _int64(client_id)}
            )
        )
        return [_row_to_booking(row) for row in rows]
