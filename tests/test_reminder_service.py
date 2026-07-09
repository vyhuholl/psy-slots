"""Тесты сервиса напоминаний.

Отдельная функция по timer-триггеру YC, шлющая клиенту одно напоминание
за фиксированные 5 минут до начала активной брони — идемпотентная
(персистентный маркер по booking_id), с показом времени в таймзоне клиента.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.config import Config, load_config
from app.domain.booking import Booking, BookingStatus
from app.domain.client import Client
from app.services.reminder_service import REMINDER_LEAD

_UTC = timezone.utc

# Europe/Moscow = UTC+3 (без DST). Локальное 10:00 = 07:00 UTC.
NOW = datetime(2026, 7, 9, 6, 0, tzinfo=_UTC)  # Москва 09:00
BOOKING_START = datetime(2026, 7, 9, 7, 0, tzinfo=_UTC)  # Москва 10:00


# --- Тестовые двойники YDB -------------------------------------------------


class _FakeResultSet:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows


class _FakeTx:
    """Транзакция: SELECT отдаёт заданные строки, запись — пустой набор."""

    def __init__(
        self,
        select_rows: list[dict[str, Any]] | None = None,
        sent_reminders_row: dict[str, Any] | None = None,
    ) -> None:
        self._select_rows = select_rows or []
        self._sent_reminders_row = sent_reminders_row
        self.queries: list[tuple[str, dict[str, Any]]] = []
        self._committed = False

    def execute(
        self, query: str, parameters: dict[str, Any] | None = None
    ) -> list[_FakeResultSet]:
        self.queries.append((query, parameters or {}))
        query_upper = query.upper()

        # Проверка существования маркера sent_reminders
        if "SENT_REMINDERS" in query_upper and "SELECT" in query_upper:
            if self._sent_reminders_row is None:
                return [_FakeResultSet([])]
            return [_FakeResultSet([self._sent_reminders_row])]

        # INSERT маркера
        if "SENT_REMINDERS" in query_upper and "INSERT" in query_upper:
            self._committed = True
            return [_FakeResultSet([])]

        # Чтение броней
        return [_FakeResultSet(list(self._select_rows))]

    def commit(self) -> None:
        self._committed = True


class _FakePool:
    def __init__(
        self,
        *,
        active_bookings: list[Booking] | None = None,
        sent_reminders: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._active_bookings = active_bookings or []
        self._sent_reminders = sent_reminders or {}
        self.tx_queries: list[tuple[str, dict[str, Any]]] = []
        self.read_queries: list[tuple[str, dict[str, Any]]] = []
        self._tx: _FakeTx | None = None

    def _booking_row(self, booking: Booking) -> dict[str, Any]:
        return {
            "id": booking.id,
            "client_id": booking.client_id,
            "start_utc": booking.start,
            "end_utc": booking.end,
            "status": booking.status.value,
            "created_at": booking.created_at,
            "cancelled_at": booking.cancelled_at,
        }

    def retry_tx_sync(
        self,
        callee: Callable[[_FakeTx], Any],
        tx_mode: Any = None,
        retry_settings: Any = None,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        self._tx = _FakeTx(
            select_rows=[self._booking_row(b) for b in self._active_bookings],
            sent_reminders_row=None,
        )
        result = callee(self._tx)
        self.tx_queries.extend(self._tx.queries)
        return result

    def execute_with_retries(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> list[_FakeResultSet]:
        params = parameters or {}
        self.read_queries.append((query, params))

        query_upper = query.upper()

        # Проверка существования маркера sent_reminders
        if "SENT_REMINDERS" in query_upper and "SELECT" in query_upper:
            booking_id = params.get("$booking_id")
            if booking_id and booking_id.value in self._sent_reminders:
                return [
                    _FakeResultSet([self._sent_reminders[booking_id.value]])
                ]
            return [_FakeResultSet([])]

        # INSERT маркера
        if "SENT_REMINDERS" in query_upper and (
            "INSERT" in query_upper or "UPSERT" in query_upper
        ):
            booking_id = params.get("$booking_id")
            if booking_id:
                sent_at = params.get("$sent_at")
                self._sent_reminders[booking_id.value] = {
                    "booking_id": booking_id.value,
                    "sent_at": sent_at.value if sent_at else NOW,
                }
            return [_FakeResultSet([])]

        # DELETE маркера (для unclaim при ошибке отправки)
        if "SENT_REMINDERS" in query_upper and "DELETE" in query_upper:
            booking_id = params.get("$booking_id")
            if booking_id and booking_id.value in self._sent_reminders:
                del self._sent_reminders[booking_id.value]
            return [_FakeResultSet([])]

        # Чтение броней в диапазоне
        if "BOOKINGS" in query_upper and "SELECT" in query_upper:
            # Фильтруем только активные (booked) брони
            active = [
                b
                for b in self._active_bookings
                if b.status == BookingStatus.BOOKED
            ]
            return [_FakeResultSet([self._booking_row(b) for b in active])]

        return [_FakeResultSet([])]


def _booking(
    *,
    booking_id: str = "11111111-1111-4111-8111-111111111111",
    client_id: int = 42,
    start: datetime | None = None,
    status: BookingStatus = BookingStatus.BOOKED,
    cancelled_at: datetime | None = None,
) -> Booking:
    start_val = start if start is not None else BOOKING_START
    return Booking(
        id=booking_id,
        client_id=client_id,
        start=start_val,
        end=start_val + timedelta(minutes=20),
        status=status,
        created_at=NOW,
        cancelled_at=cancelled_at,
    )


@pytest.fixture
def config(env: None) -> Config:
    return load_config()


# --- 2.1 Зрелость напоминания ---------------------------------------------


def test_reminder_sent_when_booking_is_mature(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Бронь созрела (now ≥ start − 5 мин, бронь будущая) → выбрана."""
    from app.services.reminder_service import ReminderService
    from app.services.booking_service import BookingService

    # now = 06:55 UTC, start = 07:00 UTC → ровно 5 минут до начала
    now = datetime(2026, 7, 9, 6, 55, tzinfo=_UTC)
    booking_start = datetime(2026, 7, 9, 7, 0, tzinfo=_UTC)
    booking = _booking(start=booking_start)

    pool = _FakePool(active_bookings=[booking])
    booking_service = BookingService(config, pool)

    bot_mock = MagicMock()
    bot_mock.send_message.return_value = None

    service = ReminderService(booking_service, pool, bot_mock, config.timezone)
    service.send_pending(now=now)

    # Напоминание отправлено
    bot_mock.send_message.assert_called_once()
    call_args = bot_mock.send_message.call_args
    assert call_args[0][0] == 42  # client_id


def test_reminder_not_sent_when_booking_not_mature(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Больше 5 минут до начала → напоминание не отправляется."""
    from app.services.reminder_service import ReminderService
    from app.services.booking_service import BookingService

    # now = 06:00 UTC, start = 07:00 UTC → 60 минут до начала
    now = datetime(2026, 7, 9, 6, 0, tzinfo=_UTC)
    booking_start = datetime(2026, 7, 9, 7, 0, tzinfo=_UTC)
    booking = _booking(start=booking_start)

    pool = _FakePool(active_bookings=[booking])
    booking_service = BookingService(config, pool)

    bot_mock = MagicMock()
    bot_mock.send_message.return_value = None

    service = ReminderService(booking_service, pool, bot_mock, config.timezone)
    service.send_pending(now=now)

    # Напоминание НЕ отправлено
    bot_mock.send_message.assert_not_called()


# --- 2.2 Идемпотентность --------------------------------------------------


def test_reminder_idempotent_no_duplicate_on_second_tick(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """При существующем маркере booking_id повторной отправки нет."""
    from app.services.reminder_service import ReminderService
    from app.services.booking_service import BookingService

    now = datetime(2026, 7, 9, 6, 55, tzinfo=_UTC)
    booking_start = datetime(2026, 7, 9, 7, 0, tzinfo=_UTC)
    booking = _booking(start=booking_start, booking_id="bid-1")

    # Маркер уже существует
    pool = _FakePool(
        active_bookings=[booking],
        sent_reminders={
            "bid-1": {
                "booking_id": "bid-1",
                "sent_at": NOW - timedelta(minutes=1),
            }
        },
    )
    booking_service = BookingService(config, pool)

    bot_mock = MagicMock()
    bot_mock.send_message.return_value = None

    service = ReminderService(booking_service, pool, bot_mock, config.timezone)
    service.send_pending(now=now)

    # Напоминание НЕ отправлено (уже было)
    bot_mock.send_message.assert_not_called()


# --- 2.3 Отменённая и прошедшая бронь исключены ---------------------------


def test_cancelled_booking_not_reminded(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Отменённая бронь исключена."""
    from app.services.reminder_service import ReminderService
    from app.services.booking_service import BookingService

    now = datetime(2026, 7, 9, 6, 55, tzinfo=_UTC)
    booking_start = datetime(2026, 7, 9, 7, 0, tzinfo=_UTC)
    booking = _booking(
        start=booking_start,
        status=BookingStatus.CANCELLED,
        cancelled_at=NOW - timedelta(minutes=10),
    )

    pool = _FakePool(active_bookings=[booking])
    booking_service = BookingService(config, pool)

    bot_mock = MagicMock()
    bot_mock.send_message.return_value = None

    service = ReminderService(booking_service, pool, bot_mock, config.timezone)
    service.send_pending(now=now)

    bot_mock.send_message.assert_not_called()


def test_past_booking_not_reminded(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Прошедшая бронь исключена."""
    from app.services.reminder_service import ReminderService
    from app.services.booking_service import BookingService

    now = datetime(2026, 7, 9, 7, 5, tzinfo=_UTC)  # После начала брони
    booking_start = datetime(2026, 7, 9, 7, 0, tzinfo=_UTC)
    booking = _booking(start=booking_start)

    pool = _FakePool(active_bookings=[booking])
    booking_service = BookingService(config, pool)

    bot_mock = MagicMock()
    bot_mock.send_message.return_value = None

    service = ReminderService(booking_service, pool, bot_mock, config.timezone)
    service.send_pending(now=now)

    bot_mock.send_message.assert_not_called()


# --- 2.4 Текст форматируется в TZ клиента ----------------------------------


def test_reminder_text_in_client_timezone(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Текст форматируется в TZ клиента (не UTC)."""
    from app.services.reminder_service import ReminderService
    from app.services.booking_service import BookingService
    from app.services.client_service import ClientService

    now = datetime(2026, 7, 9, 6, 55, tzinfo=_UTC)
    booking_start = datetime(2026, 7, 9, 7, 0, tzinfo=_UTC)  # 10:00 Moscow
    booking = _booking(start=booking_start)

    pool = _FakePool(active_bookings=[booking])
    booking_service = BookingService(config, pool)

    # Подменяем client_service для возврата Client с нужной таймзоной
    client_service = MagicMock(spec=ClientService)
    mock_client = Client(
        telegram_id=42,
        timezone="Europe/Moscow",  # IANA-идентификатор как строка
        created_at=NOW,
    )
    client_service.get.return_value = mock_client

    bot_mock = MagicMock()
    bot_mock.send_message.return_value = None

    service = ReminderService(
        booking_service, pool, bot_mock, config.timezone, client_service
    )
    service.send_pending(now=now)

    # Проверяем, что время в сообщении в таймзоне клиента (10:00, не 07:00)
    call_args = bot_mock.send_message.call_args
    message_text = call_args[0][1]
    assert "10:00" in message_text or "10:" in message_text
    # 07:00 UTC не должно быть в тексте
    assert "07:00" not in message_text


# --- 2.5 Устойчивость к ошибкам отправки -----------------------------------


def test_send_error_does_not_crash_loop_and_unclaims_marker(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ошибка отправки одного получателя не роняет проход; маркер не фиксируется."""
    from app.services.reminder_service import ReminderService
    from app.services.booking_service import BookingService

    now = datetime(2026, 7, 9, 6, 55, tzinfo=_UTC)
    booking1 = _booking(start=BOOKING_START, booking_id="bid-1", client_id=1)
    booking2 = _booking(start=BOOKING_START, booking_id="bid-2", client_id=2)

    pool = _FakePool(active_bookings=[booking1, booking2])
    booking_service = BookingService(config, pool)

    bot_mock = MagicMock()
    # Первый отправляется успешно
    bot_mock.send_message.side_effect = [None, Exception("Blocked by user")]

    service = ReminderService(booking_service, pool, bot_mock, config.timezone)
    # Должно завершиться без исключения
    service.send_pending(now=now)

    # Было 2 попытки отправки
    assert bot_mock.send_message.call_count == 2

    # Первая бронь имеет маркер
    assert "bid-1" in pool._sent_reminders
    # Вторая — нет (ошибка отправки, claim снят)
    assert "bid-2" not in pool._sent_reminders


# --- 2.6 Лид-тайм — фиксированная константа 5 минут -----------------------


def test_reminder_lead_is_fixed_five_minutes() -> None:
    """Лид-тайм — фиксированная константа 5 минут, не из окружения."""
    assert REMINDER_LEAD == timedelta(minutes=5)
    assert REMINDER_LEAD.total_seconds() == 300


def test_reminder_lead_not_from_environment(env: None) -> None:
    """Лид-тайм не зависит от переменных окружения."""
    from app.services.reminder_service import REMINDER_LEAD

    # Даже если изменить env, константа остаётся 5 минут
    assert REMINDER_LEAD == timedelta(minutes=5)
