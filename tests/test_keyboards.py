from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.keyboards import (
    ACTION_ADMIN_CANCEL,
    ACTION_CANCEL,
    ACTION_CANCEL_CONFIRM,
    ACTION_CONFIRM,
    ACTION_SLOT,
    BUTTON_ADMIN,
    BUTTON_BOOK,
    BUTTON_MY_BOOKINGS,
    CALLBACK_MAX_BYTES,
    admin_bookings_keyboard,
    bookings_keyboard,
    cancel_confirm_keyboard,
    confirm_keyboard,
    main_menu_keyboard,
    pack,
    slots_keyboard,
    start_from_value,
    unpack,
)
from app.domain.booking import Booking, BookingStatus
from app.domain.slots import Slot

_MOSCOW = ZoneInfo("Europe/Moscow")
_START = datetime(2026, 7, 9, 7, 0, tzinfo=UTC)
_UUID = "11111111-1111-4111-8111-111111111111"


def _buttons(markup: InlineKeyboardMarkup) -> list[InlineKeyboardButton]:
    return [btn for row in markup.inline_keyboard for btn in row]


# --- (де)сериализация callback_data ----------------------------------------


def test_pack_unpack_round_trip() -> None:
    for action in (ACTION_SLOT, ACTION_CONFIRM, ACTION_CANCEL):
        data = pack(action, "value-1")
        assert unpack(data) == (action, "value-1")


def test_unpack_splits_on_first_colon_only() -> None:
    # Значение может содержать ':' — разбор идёт по первому двоеточию.
    assert unpack(f"{ACTION_CANCEL}:11:22") == (ACTION_CANCEL, "11:22")


def test_confirm_callback_within_budget_for_real_epoch() -> None:
    epoch = str(int(_START.timestamp()))
    data = pack(ACTION_CONFIRM, epoch)
    assert len(data.encode("utf-8")) <= CALLBACK_MAX_BYTES


def test_cancel_callback_within_budget_for_real_uuid() -> None:
    data = pack(ACTION_CANCEL, _UUID)
    assert len(data.encode("utf-8")) <= CALLBACK_MAX_BYTES


def test_pack_rejects_overlong_payload() -> None:
    with pytest.raises(ValueError):
        pack(ACTION_CANCEL, "x" * CALLBACK_MAX_BYTES)


def test_start_from_value_round_trips_epoch() -> None:
    _, value = unpack(pack(ACTION_SLOT, str(int(_START.timestamp()))))
    assert start_from_value(value) == _START


# --- Главное меню (reply-клавиатура) ---------------------------------------


def test_main_menu_admin_has_all_three_buttons() -> None:
    markup = main_menu_keyboard(is_admin=True)

    texts = [btn.text for row in markup.keyboard for btn in row]
    assert texts == [BUTTON_BOOK, BUTTON_MY_BOOKINGS, BUTTON_ADMIN]


def test_main_menu_non_admin_hides_admin_button() -> None:
    markup = main_menu_keyboard(is_admin=False)

    texts = [btn.text for row in markup.keyboard for btn in row]
    assert texts == [BUTTON_BOOK, BUTTON_MY_BOOKINGS]
    assert BUTTON_ADMIN not in texts


# --- сборка клавиатур -------------------------------------------------------


def test_slots_keyboard_labels_as_range_and_encodes_start() -> None:
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
    # Слот показывается диапазоном: 07:00 UTC → 10:00 MSK, конец 10:20 MSK.
    assert buttons[0].text == "10:00–10:20"
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


def test_admin_bookings_keyboard_shows_name_after_range() -> None:
    booking = Booking(
        id=_UUID,
        client_id=123,
        start=_START,
        end=_START + timedelta(minutes=20),
        status=BookingStatus.BOOKED,
        created_at=_START,
    )

    markup = admin_bookings_keyboard(
        [booking], _MOSCOW, {123: "Иван Иванов (@ivanov)"}
    )

    buttons = _buttons(markup)
    assert len(buttons) == 1
    # Имя после диапазона без обрамляющих скобок.
    assert buttons[0].text == "10:00–10:20 Иван Иванов (@ivanov) ❌"
    assert buttons[0].callback_data is not None
    assert unpack(buttons[0].callback_data) == (ACTION_ADMIN_CANCEL, _UUID)


def test_admin_bookings_keyboard_falls_back_to_id_when_no_name() -> None:
    booking = Booking(
        id=_UUID,
        client_id=456,
        start=_START,
        end=_START + timedelta(minutes=20),
        status=BookingStatus.BOOKED,
        created_at=_START,
    )

    markup = admin_bookings_keyboard([booking], _MOSCOW, {})

    buttons = _buttons(markup)
    assert "456" in buttons[0].text
