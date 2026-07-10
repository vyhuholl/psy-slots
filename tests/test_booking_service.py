from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
import ydb

from app.config import Config, load_config
from app.domain.booking import (
    BookingError,
    BookingNotFound,
    BookingStatus,
    ClientAlreadyBooked,
    SlotMisaligned,
    SlotNotToday,
    SlotOutsideAvailability,
    SlotTaken,
)
from app.services.booking_service import BookingService

_UTC = timezone.utc

# Europe/Moscow = UTC+3 (без DST). Локальное 10:00 = 07:00 UTC.
NOW = datetime(2026, 7, 9, 6, 0, tzinfo=_UTC)  # Москва 09:00, сегодня 07-09
VALID_START = datetime(2026, 7, 9, 7, 0, tzinfo=_UTC)  # Москва 10:00, на сетке


# --- Тестовые двойники YDB -------------------------------------------------


class _FakeResultSet:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows


_WRITE_KEYWORDS = ("UPSERT", "UPDATE", "INSERT", "DELETE")


def _is_write(query: str) -> bool:
    upper = query.upper()
    return any(keyword in upper for keyword in _WRITE_KEYWORDS)


class _FakeTx:
    """Транзакция: SELECT отдаёт заданные строки, запись — пустой набор.

    Отдельный набор ``client_rows`` возвращается для запроса активных броней
    клиента (SELECT c ``client_id``), чтобы отличать проверку слота от
    проверки «одна активная бронь на клиента».
    """

    def __init__(
        self,
        select_rows: list[dict[str, Any]],
        client_rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self._select_rows = select_rows
        self._client_rows = client_rows
        self.queries: list[tuple[str, dict[str, Any]]] = []

    def execute(
        self, query: str, parameters: dict[str, Any] | None = None
    ) -> list[_FakeResultSet]:
        self.queries.append((query, parameters or {}))
        if _is_write(query):
            return [_FakeResultSet([])]
        if self._client_rows is not None and "client_id" in query:
            return [_FakeResultSet(list(self._client_rows))]
        return [_FakeResultSet(list(self._select_rows))]


class _FakePool:
    def __init__(
        self,
        *,
        select_rows: list[dict[str, Any]] | None = None,
        client_rows: list[dict[str, Any]] | None = None,
        tx_error: Exception | None = None,
        read_rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self.tx = _FakeTx(select_rows or [], client_rows)
        self._tx_error = tx_error
        self._read_rows = read_rows or []
        self.read_queries: list[tuple[str, dict[str, Any]]] = []

    def retry_tx_sync(
        self,
        callee: Callable[[_FakeTx], Any],
        tx_mode: Any = None,
        retry_settings: Any = None,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if self._tx_error is not None:
            raise self._tx_error
        return callee(self.tx)

    def execute_with_retries(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> list[_FakeResultSet]:
        self.read_queries.append((query, parameters or {}))
        return [_FakeResultSet(list(self._read_rows))]


def _full_row(
    *,
    booking_id: str = "11111111-1111-4111-8111-111111111111",
    client_id: int = 42,
    status: str = "booked",
    cancelled_at: datetime | None = None,
) -> dict[str, Any]:
    return {
        "id": booking_id,
        "client_id": client_id,
        "start_utc": VALID_START,
        "end_utc": VALID_START + timedelta(minutes=20),
        "status": status,
        "created_at": NOW,
        "cancelled_at": cancelled_at,
    }


@pytest.fixture
def config(env: None) -> Config:
    return load_config()


def _tx_writes(pool: _FakePool) -> list[tuple[str, dict[str, Any]]]:
    return [q for q in pool.tx.queries if _is_write(q[0])]


# --- 3. Создание брони -----------------------------------------------------


def test_create_fixes_uuid_start_and_denormalized_end(config: Config) -> None:
    pool = _FakePool()
    service = BookingService(config, pool)

    booking = service.create(client_id=42, start=VALID_START, now=NOW)

    assert uuid.UUID(booking.id).version == 4
    assert booking.client_id == 42
    assert booking.start == VALID_START
    assert booking.end == VALID_START + timedelta(minutes=20)
    assert booking.status is BookingStatus.BOOKED
    # Запись содержит денормализованный end.
    writes = _tx_writes(pool)
    assert writes, "ожидалась запись брони в транзакции"
    params = writes[0][1]
    assert params["$end_utc"].value == VALID_START + timedelta(minutes=20)
    assert params["$start_utc"].value == VALID_START


def test_duration_change_does_not_move_existing_end(
    env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    config20 = load_config()
    booking20 = BookingService(config20, _FakePool()).create(
        client_id=42, start=VALID_START, now=NOW
    )
    assert booking20.end == VALID_START + timedelta(minutes=20)

    monkeypatch.setenv("SLOT_DURATION_MINUTES", "30")
    config30 = load_config()
    booking30 = BookingService(config30, _FakePool()).create(
        client_id=42, start=VALID_START, now=NOW
    )

    assert booking30.end == VALID_START + timedelta(minutes=30)
    # Ранее созданная бронь не сдвинулась (end денормализован на брони).
    assert booking20.end == VALID_START + timedelta(minutes=20)


def test_create_today_inside_window_on_grid(config: Config) -> None:
    service = BookingService(config, _FakePool())

    booking = service.create(client_id=7, start=VALID_START, now=NOW)

    assert booking.status is BookingStatus.BOOKED
    assert booking.client_id == 7


@pytest.mark.parametrize(
    "start",
    [
        datetime(2026, 7, 10, 7, 0, tzinfo=_UTC),  # другой день
        datetime(
            2026, 7, 9, 4, 0, tzinfo=_UTC
        ),  # уже прошло (Москва 07:00 < now)
    ],
)
def test_create_not_today_is_rejected(config: Config, start: datetime) -> None:
    pool = _FakePool()
    service = BookingService(config, pool)
    # now = Москва 11:00 → слот 07:00 UTC уже прошёл; 07-10 — другой день.
    now = datetime(2026, 7, 9, 8, 0, tzinfo=_UTC)

    with pytest.raises(SlotNotToday):
        service.create(client_id=42, start=start, now=now)

    assert _tx_writes(pool) == []


def test_create_outside_availability_is_rejected(config: Config) -> None:
    pool = _FakePool()
    service = BookingService(config, pool)
    # Москва 14:30 — в разрыве между 10:00-14:00 и 15:00-18:00.
    start = datetime(2026, 7, 9, 11, 30, tzinfo=_UTC)

    with pytest.raises(SlotOutsideAvailability):
        service.create(client_id=42, start=start, now=NOW)

    assert _tx_writes(pool) == []


def test_create_misaligned_is_rejected(config: Config) -> None:
    pool = _FakePool()
    service = BookingService(config, pool)
    # Москва 10:10 — смещение 10 мин не кратно длительности 20.
    start = datetime(2026, 7, 9, 7, 10, tzinfo=_UTC)

    with pytest.raises(SlotMisaligned):
        service.create(client_id=42, start=start, now=NOW)

    assert _tx_writes(pool) == []


# --- 4. Запрет двойного бронирования (race-safe) ---------------------------


def test_create_overlapping_active_booking_is_rejected(config: Config) -> None:
    pool = _FakePool(select_rows=[{"id": "other"}])
    service = BookingService(config, pool)

    with pytest.raises(SlotTaken):
        service.create(client_id=42, start=VALID_START, now=NOW)

    assert _tx_writes(pool) == []


def test_concurrent_creation_conflict_becomes_slot_taken(
    config: Config,
) -> None:
    # Сериализуемая транзакция YDB отклоняет проигравший коммит (TLI/Aborted).
    pool = _FakePool(
        tx_error=ydb.issues.Aborted("Transaction locks invalidated")
    )
    service = BookingService(config, pool)

    with pytest.raises(SlotTaken):
        service.create(client_id=42, start=VALID_START, now=NOW)


def test_rebooking_after_cancellation_succeeds(config: Config) -> None:
    # Отменённая бронь не попадает в SELECT активных (status='booked'),
    # поэтому слот снова свободен.
    pool = _FakePool(select_rows=[])
    service = BookingService(config, pool)

    booking = service.create(client_id=42, start=VALID_START, now=NOW)

    assert booking.status is BookingStatus.BOOKED
    assert _tx_writes(pool), "новая бронь должна быть записана"


# --- 4b. Одна активная бронь на клиента ------------------------------------


def test_create_second_active_booking_is_rejected(config: Config) -> None:
    # Слот свободен (overlap пуст), но у клиента уже есть активная бронь.
    pool = _FakePool(select_rows=[], client_rows=[{"id": "existing"}])
    service = BookingService(config, pool)

    with pytest.raises(ClientAlreadyBooked):
        service.create(client_id=42, start=VALID_START, now=NOW)

    assert _tx_writes(pool) == []


def test_create_after_cancellation_succeeds(config: Config) -> None:
    # После отмены активных броней у клиента нет — запись проходит.
    pool = _FakePool(select_rows=[], client_rows=[])
    service = BookingService(config, pool)

    booking = service.create(client_id=42, start=VALID_START, now=NOW)

    assert booking.status is BookingStatus.BOOKED
    assert _tx_writes(pool), "новая бронь должна быть записана"


def test_other_clients_booking_does_not_block(config: Config) -> None:
    # Активная бронь чужого клиента не попадает в SELECT по этому client_id.
    pool = _FakePool(select_rows=[], client_rows=[])
    service = BookingService(config, pool)

    booking = service.create(client_id=7, start=VALID_START, now=NOW)

    assert booking.client_id == 7
    assert booking.status is BookingStatus.BOOKED


def test_concurrent_creation_by_one_client_becomes_domain_error(
    config: Config,
) -> None:
    # Проигравший конкурентный коммит (Aborted) — доменная ошибка брони.
    pool = _FakePool(
        tx_error=ydb.issues.Aborted("Transaction locks invalidated")
    )
    service = BookingService(config, pool)

    with pytest.raises(BookingError):
        service.create(client_id=42, start=VALID_START, now=NOW)


# --- 5. Отмена (soft, идемпотентная) ---------------------------------------


def test_cancel_active_booking_soft_transitions(config: Config) -> None:
    pool = _FakePool(select_rows=[_full_row(status="booked")])
    service = BookingService(config, pool)

    result = service.cancel("11111111-1111-4111-8111-111111111111", now=NOW)

    assert result.status is BookingStatus.CANCELLED
    assert result.cancelled_at == NOW
    assert result.id == "11111111-1111-4111-8111-111111111111"
    # Переход — UPDATE, не hard-delete.
    writes = _tx_writes(pool)
    assert writes
    assert "UPDATE" in writes[0][0].upper()
    assert "DELETE" not in writes[0][0].upper()


def test_cancel_is_idempotent_on_cancelled(config: Config) -> None:
    pool = _FakePool(
        select_rows=[_full_row(status="cancelled", cancelled_at=NOW)]
    )
    service = BookingService(config, pool)

    result = service.cancel(
        "11111111-1111-4111-8111-111111111111",
        now=datetime(2026, 7, 9, 9, 0, tzinfo=_UTC),
    )

    assert result.status is BookingStatus.CANCELLED
    assert result.cancelled_at == NOW  # прежняя метка, второго эффекта нет
    # Никакого повторного UPDATE.
    assert _tx_writes(pool) == []


def test_cancel_unknown_id_raises_not_found(config: Config) -> None:
    pool = _FakePool(select_rows=[])
    service = BookingService(config, pool)

    with pytest.raises(BookingNotFound):
        service.cancel("does-not-exist", now=NOW)


# --- 6. Чтение броней ------------------------------------------------------


def test_get_returns_booking_with_status(config: Config) -> None:
    pool = _FakePool(
        read_rows=[_full_row(status="cancelled", cancelled_at=NOW)]
    )
    service = BookingService(config, pool)

    booking = service.get("11111111-1111-4111-8111-111111111111")

    assert booking is not None
    assert booking.id == "11111111-1111-4111-8111-111111111111"
    assert booking.status is BookingStatus.CANCELLED
    assert booking.cancelled_at == NOW


def test_get_unknown_id_returns_none(config: Config) -> None:
    pool = _FakePool(read_rows=[])
    service = BookingService(config, pool)

    assert service.get("nope") is None


def test_list_active_in_range_selects_only_booked(config: Config) -> None:
    pool = _FakePool(read_rows=[_full_row(status="booked")])
    service = BookingService(config, pool)
    range_start = datetime(2026, 7, 9, 6, 0, tzinfo=_UTC)
    range_end = datetime(2026, 7, 9, 12, 0, tzinfo=_UTC)

    bookings = service.list_active_in_range(range_start, range_end)

    assert [b.status for b in bookings] == [BookingStatus.BOOKED]
    query, params = pool.read_queries[0]
    assert "'booked'" in query
    assert params["$range_start"].value == range_start
    assert params["$range_end"].value == range_end


def test_list_active_for_client_selects_only_booked(config: Config) -> None:
    pool = _FakePool(read_rows=[_full_row(status="booked", client_id=99)])
    service = BookingService(config, pool)

    bookings = service.list_active_for_client(99)

    assert [b.client_id for b in bookings] == [99]
    assert all(b.status is BookingStatus.BOOKED for b in bookings)
    query, params = pool.read_queries[0]
    assert "'booked'" in query
    assert params["$client_id"].value == 99
