from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.keyboards import (
    ACTION_CANCEL,
    ACTION_CANCEL_CONFIRM,
    ACTION_CONFIRM,
    ACTION_SLOT,
    ACTION_TZ,
    CALLBACK_MAX_BYTES,
    COMMON_TIMEZONES,
    bookings_keyboard,
    cancel_confirm_keyboard,
    confirm_keyboard,
    pack,
    slots_keyboard,
    start_from_value,
    timezone_keyboard,
    unpack,
)
from app.domain.booking import Booking, BookingStatus
from app.domain.slots import Slot

_MOSCOW = ZoneInfo("Europe/Moscow")
_START = datetime(2026, 7, 9, 7, 0, tzinfo=UTC)
_UUID = "11111111-1111-4111-8111-111111111111"


def _buttons(markup: InlineKeyboardMarkup) -> list[InlineKeyboardButton]:
    return [btn for row in markup.inline_keyboard for btn in row]


# --- 2.1 (де)сериализация callback_data ------------------------------------


def test_pack_unpack_round_trip() -> None:
    for action in (ACTION_SLOT, ACTION_CONFIRM, ACTION_CANCEL, ACTION_TZ):
        data = pack(action, "value-1")
        assert unpack(data) == (action, "value-1")


def test_unpack_splits_on_first_colon_only() -> None:
    # Имя таймзоны содержит '/', но не ':' — безопасно.
    data = pack(ACTION_TZ, "Europe/Moscow")
    assert unpack(data) == (ACTION_TZ, "Europe/Moscow")


def test_confirm_callback_within_budget_for_real_epoch() -> None:
    epoch = str(int(_START.timestamp()))
    data = pack(ACTION_CONFIRM, epoch)
    assert len(data.encode("utf-8")) <= CALLBACK_MAX_BYTES


def test_cancel_callback_within_budget_for_real_uuid() -> None:
    data = pack(ACTION_CANCEL, _UUID)
    assert len(data.encode("utf-8")) <= CALLBACK_MAX_BYTES


def test_pack_rejects_overlong_payload() -> None:
    with pytest.raises(ValueError):
        pack(ACTION_TZ, "x" * CALLBACK_MAX_BYTES)


def test_start_from_value_round_trips_epoch() -> None:
    _, value = unpack(pack(ACTION_SLOT, str(int(_START.timestamp()))))
    assert start_from_value(value) == _START


# --- 2.2 сборка клавиатур ---------------------------------------------------


def test_timezone_keyboard_offers_common_zones() -> None:
    markup = timezone_keyboard()

    buttons = _buttons(markup)
    assert buttons, "ожидались кнопки таймзон"
    for btn in buttons:
        assert btn.callback_data is not None
        action, name = unpack(btn.callback_data)
        assert action == ACTION_TZ
        assert name in COMMON_TIMEZONES


def test_slots_keyboard_labels_in_client_tz_and_encodes_start() -> None:
    slots = [
        Slot(start=_START, end=_START + timedelta(minutes=20)),
        Slot(
            start=_START + timedelta(minutes=20),
            end=_START + timedelta(minutes=40),
        ),
    ]

    markup = slots_keyboard(slots, _MOSCOW)

    buttons = _buttons(markup)
    assert len(buttons) == 2
    # Первый слот 07:00 UTC → 10:00 MSK, callback декодируется обратно в start.
    assert buttons[0].text == "10:00"
    assert buttons[0].callback_data is not None
    action, value = unpack(buttons[0].callback_data)
    assert action == ACTION_SLOT
    assert start_from_value(value) == _START


def test_confirm_keyboard_encodes_start() -> None:
    markup = confirm_keyboard(_START)

    buttons = _buttons(markup)
    assert any(
        btn.callback_data is not None
        and unpack(btn.callback_data)[0] == ACTION_CONFIRM
        and start_from_value(unpack(btn.callback_data)[1]) == _START
        for btn in buttons
    )


def test_bookings_keyboard_has_cancel_per_booking() -> None:
    booking = Booking(
        id=_UUID,
        client_id=42,
        start=_START,
        end=_START + timedelta(minutes=20),
        status=BookingStatus.BOOKED,
        created_at=_START,
    )

    markup = bookings_keyboard([booking], _MOSCOW)

    buttons = _buttons(markup)
    assert len(buttons) == 1
    assert "10:00" in buttons[0].text
    assert buttons[0].callback_data is not None
    assert unpack(buttons[0].callback_data) == (ACTION_CANCEL, _UUID)


def test_cancel_confirm_keyboard_encodes_booking_id() -> None:
    markup = cancel_confirm_keyboard(_UUID)

    buttons = _buttons(markup)
    assert any(
        btn.callback_data is not None
        and unpack(btn.callback_data) == (ACTION_CANCEL_CONFIRM, _UUID)
        for btn in buttons
    )
