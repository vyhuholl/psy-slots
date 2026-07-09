from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from typing import Any

import pytest

from app.domain.booking import Booking, BookingStatus

_UTC = timezone.utc


def _booking(**overrides: Any) -> Booking:
    base = Booking(
        id="11111111-1111-4111-8111-111111111111",
        client_id=42,
        start=datetime(2026, 7, 9, 7, 0, tzinfo=_UTC),
        end=datetime(2026, 7, 9, 7, 20, tzinfo=_UTC),
        status=BookingStatus.BOOKED,
        created_at=datetime(2026, 7, 9, 6, 0, tzinfo=_UTC),
        cancelled_at=None,
    )
    return replace(base, **overrides) if overrides else base


def test_booking_holds_id_client_and_utc_bounds() -> None:
    booking = _booking()

    assert booking.id == "11111111-1111-4111-8111-111111111111"
    assert booking.client_id == 42
    assert booking.start == datetime(2026, 7, 9, 7, 0, tzinfo=_UTC)
    assert booking.end == datetime(2026, 7, 9, 7, 20, tzinfo=_UTC)
    assert booking.status is BookingStatus.BOOKED
    assert booking.cancelled_at is None


def test_booking_is_immutable() -> None:
    booking = _booking()

    with pytest.raises(FrozenInstanceError):
        setattr(booking, "id", "other")


def test_booking_status_values() -> None:
    assert BookingStatus.BOOKED.value == "booked"
    assert BookingStatus.CANCELLED.value == "cancelled"
    assert {s.value for s in BookingStatus} == {"booked", "cancelled"}


def test_cancelled_transition_is_reflected_in_model() -> None:
    booking = _booking()
    when = datetime(2026, 7, 9, 8, 0, tzinfo=_UTC)

    cancelled = booking.cancelled(when)

    # Переход booked → cancelled отражается в новой (неизменной) модели.
    assert cancelled.status is BookingStatus.CANCELLED
    assert cancelled.cancelled_at == when
    assert cancelled.id == booking.id
    assert cancelled.start == booking.start
    # Исходная бронь не мутирована.
    assert booking.status is BookingStatus.BOOKED
    assert booking.cancelled_at is None


def test_is_active_reflects_status() -> None:
    assert _booking().is_active is True
    assert _booking(status=BookingStatus.CANCELLED).is_active is False
