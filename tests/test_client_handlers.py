from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.bot.handlers.client import (
    handle_book,
    handle_cancel_confirm,
    handle_cancel_request,
    handle_confirm,
    handle_my_bookings,
    handle_slot,
    handle_start,
)
from app.bot.keyboards import (
    ACTION_CANCEL,
    ACTION_CANCEL_CONFIRM,
    ACTION_CONFIRM,
    ACTION_SLOT,
    BUTTON_ADMIN,
    BUTTON_BOOK,
    BUTTON_MY_BOOKINGS,
    pack,
    unpack,
)
from app.config import Config, load_config
from app.domain.booking import (
    Booking,
    BookingStatus,
    ClientAlreadyBooked,
    SlotNotToday,
    SlotTaken,
)
from app.domain.slots import Slot
from tests.conftest import (
    TEST_ADMIN_TELEGRAM_ID,
    TEST_BOOKING_UNAVAILABLE_MESSAGE,
    TEST_WELCOME_MESSAGE,
)

ADMIN_ID = int(TEST_ADMIN_TELEGRAM_ID)  # 42 из conftest
CLIENT_ID = 100  # обычный клиент (не админ)
NOW = datetime(2026, 7, 9, 6, 0, tzinfo=UTC)
START = datetime(2026, 7, 9, 7, 0, tzinfo=UTC)  # 10:00 MSK


@pytest.fixture
def config(env: None) -> Config:
    return load_config()


def _booking(start: datetime = START, client_id: int = CLIENT_ID) -> Booking:
    return Booking(
        id="11111111-1111-4111-8111-111111111111",
        client_id=client_id,
        start=start,
        end=start + timedelta(minutes=20),
        status=BookingStatus.BOOKED,
        created_at=NOW,
    )


def _message(user_id: int = CLIENT_ID) -> Any:
    return SimpleNamespace(
        from_user=SimpleNamespace(id=user_id),
        chat=SimpleNamespace(id=user_id),
        answer=AsyncMock(),
    )


def _callback(data: str, user_id: int = CLIENT_ID) -> Any:
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=user_id),
        answer=AsyncMock(),
    )


def _reply_markup(send: AsyncMock) -> Any:
    return send.call_args.kwargs.get("reply_markup")


def _markup_actions(markup: Any) -> set[str]:
    return {
        unpack(btn.callback_data)[0]
        for row in markup.inline_keyboard
        for btn in row
        if btn.callback_data is not None
    }


def _menu_texts(markup: Any) -> list[str]:
    return [btn.text for row in markup.keyboard for btn in row]


# --- /start: приветствие + слоты либо сообщение о невозможности -------------


async def test_start_with_slots_sends_welcome_and_slots(
    config: Config,
) -> None:
    bot = AsyncMock()
    slot_service = MagicMock()
    slot_service.list_free_slots.return_value = [
        Slot(start=START, end=START + timedelta(minutes=20))
    ]

    await handle_start(
        _message(), bot=bot, config=config, slot_service=slot_service
    )

    # Первое сообщение — приветствие с главным меню.
    first = bot.send_message.call_args_list[0]
    assert first.args[1] == TEST_WELCOME_MESSAGE
    assert _menu_texts(first.kwargs["reply_markup"]) == [
        BUTTON_BOOK,
        BUTTON_MY_BOOKINGS,
    ]
    # Второе — слоты на сегодня.
    second = bot.send_message.call_args_list[1]
    assert _markup_actions(second.kwargs["reply_markup"]) == {ACTION_SLOT}


async def test_start_without_slots_sends_unavailable(config: Config) -> None:
    bot = AsyncMock()
    slot_service = MagicMock()
    slot_service.list_free_slots.return_value = []

    await handle_start(
        _message(), bot=bot, config=config, slot_service=slot_service
    )

    bot.send_message.assert_awaited_once()
    assert (
        bot.send_message.call_args.args[1] == TEST_BOOKING_UNAVAILABLE_MESSAGE
    )
    assert _menu_texts(_reply_markup(bot.send_message)) == [
        BUTTON_BOOK,
        BUTTON_MY_BOOKINGS,
    ]


async def test_start_admin_sees_admin_button(config: Config) -> None:
    bot = AsyncMock()
    slot_service = MagicMock()
    slot_service.list_free_slots.return_value = []

    await handle_start(
        _message(ADMIN_ID), bot=bot, config=config, slot_service=slot_service
    )

    assert BUTTON_ADMIN in _menu_texts(_reply_markup(bot.send_message))


# --- /book: показ слотов / нет слотов ---------------------------------------


async def test_book_lists_todays_slots_as_ranges(config: Config) -> None:
    bot = AsyncMock()
    slot_service = MagicMock()
    slot_service.list_free_slots.return_value = [
        Slot(start=START, end=START + timedelta(minutes=20)),
        Slot(
            start=START + timedelta(minutes=20),
            end=START + timedelta(minutes=40),
        ),
    ]

    await handle_book(
        _message(), bot=bot, config=config, slot_service=slot_service
    )

    markup = _reply_markup(bot.send_message)
    buttons = [btn for row in markup.inline_keyboard for btn in row]
    assert len(buttons) == 2
    # Диапазон в московском времени: 07:00 UTC → 10:00–10:20 MSK.
    assert buttons[0].text == "10:00–10:20"
    assert unpack(buttons[0].callback_data)[0] == ACTION_SLOT


async def test_book_without_free_slots_shows_unavailable(
    config: Config,
) -> None:
    bot = AsyncMock()
    slot_service = MagicMock()
    slot_service.list_free_slots.return_value = []

    await handle_book(
        _message(), bot=bot, config=config, slot_service=slot_service
    )

    bot.send_message.assert_awaited_once_with(
        CLIENT_ID, TEST_BOOKING_UNAVAILABLE_MESSAGE
    )


# --- slot: → шаг подтверждения ---------------------------------------------


async def test_slot_shows_confirmation(config: Config) -> None:
    bot = AsyncMock()

    await handle_slot(
        _callback(pack(ACTION_SLOT, str(int(START.timestamp())))),
        bot=bot,
        config=config,
    )

    markup = _reply_markup(bot.send_message)
    assert _markup_actions(markup) == {ACTION_CONFIRM}
    # Подтверждение показывает диапазон в московском времени.
    assert "10:00–10:20" in bot.send_message.call_args.args[1]


# --- подтверждение брони ----------------------------------------------------


async def test_confirm_creates_booking_and_confirms(config: Config) -> None:
    bot = AsyncMock()
    bot.get_chat = AsyncMock(
        return_value=SimpleNamespace(
            first_name="Иван", last_name="Иванов", username="ivanov"
        )
    )
    booking_service = MagicMock()
    booking_service.create.return_value = _booking()

    await handle_confirm(
        _callback(pack(ACTION_CONFIRM, str(int(START.timestamp())))),
        bot=bot,
        config=config,
        booking_service=booking_service,
    )

    booking_service.create.assert_called_once_with(
        client_id=CLIENT_ID, start=START
    )
    # Клиенту — подтверждение записи.
    client_call = bot.send_message.await_args_list[0]
    assert client_call.args[0] == CLIENT_ID
    assert "Готово" in client_call.args[1]
    assert "10:00" in client_call.args[1]


async def test_confirm_notifies_admin_of_new_booking(config: Config) -> None:
    bot = AsyncMock()
    bot.get_chat = AsyncMock(
        return_value=SimpleNamespace(
            first_name="Иван", last_name="Иванов", username="ivanov"
        )
    )
    booking_service = MagicMock()
    booking_service.create.return_value = _booking()

    await handle_confirm(
        _callback(pack(ACTION_CONFIRM, str(int(START.timestamp())))),
        bot=bot,
        config=config,
        booking_service=booking_service,
    )

    admin_call = next(
        call
        for call in bot.send_message.await_args_list
        if call.args[0] == ADMIN_ID
    )
    assert admin_call.args[1] == (
        "Пользователь Иван Иванов (@ivanov) забронировал слот на 10:00–10:20."
    )


async def test_confirm_admin_notify_failure_does_not_raise(
    config: Config,
) -> None:
    bot = AsyncMock()
    bot.get_chat = AsyncMock(
        return_value=SimpleNamespace(
            first_name=None, last_name=None, username=None
        )
    )
    # Клиенту — успех, администратору — сбой доставки.
    bot.send_message.side_effect = [None, RuntimeError("admin unreachable")]
    booking_service = MagicMock()
    booking_service.create.return_value = _booking()

    await handle_confirm(
        _callback(pack(ACTION_CONFIRM, str(int(START.timestamp())))),
        bot=bot,
        config=config,
        booking_service=booking_service,
    )

    # Бронь создана, несмотря на сбой уведомления администратора.
    booking_service.create.assert_called_once()


async def test_confirm_rejected_does_not_notify_admin(config: Config) -> None:
    bot = AsyncMock()
    booking_service = MagicMock()
    booking_service.create.side_effect = SlotTaken("taken")
    booking_service.list_active_for_client.return_value = []

    await handle_confirm(
        _callback(pack(ACTION_CONFIRM, str(int(START.timestamp())))),
        bot=bot,
        config=config,
        booking_service=booking_service,
    )

    # Администратору не отправлялось уведомление о новой броне.
    assert all(
        call.args[0] != ADMIN_ID for call in bot.send_message.await_args_list
    )


async def test_confirm_client_already_booked_is_reported(
    config: Config,
) -> None:
    bot = AsyncMock()
    booking_service = MagicMock()
    booking_service.create.side_effect = ClientAlreadyBooked("dup")

    await handle_confirm(
        _callback(pack(ACTION_CONFIRM, str(int(START.timestamp())))),
        bot=bot,
        config=config,
        booking_service=booking_service,
    )

    client_call = next(
        call
        for call in bot.send_message.await_args_list
        if call.args[0] == CLIENT_ID
    )
    assert "одну" in client_call.args[1].lower()
    # Уведомление о брони администратору не уходит.
    assert all(
        call.args[0] != ADMIN_ID for call in bot.send_message.await_args_list
    )


async def test_confirm_slot_taken_by_other_is_friendly(
    config: Config,
) -> None:
    bot = AsyncMock()
    booking_service = MagicMock()
    booking_service.create.side_effect = SlotTaken("taken")
    booking_service.list_active_for_client.return_value = []  # чужая бронь

    await handle_confirm(
        _callback(pack(ACTION_CONFIRM, str(int(START.timestamp())))),
        bot=bot,
        config=config,
        booking_service=booking_service,
    )

    booking_service.create.assert_called_once()
    text = bot.send_message.call_args.args[1]
    assert "друг" in text.lower()


async def test_confirm_repeat_shows_existing_booking(config: Config) -> None:
    bot = AsyncMock()
    booking_service = MagicMock()
    booking_service.create.side_effect = SlotTaken("taken")
    booking_service.list_active_for_client.return_value = [_booking()]

    await handle_confirm(
        _callback(pack(ACTION_CONFIRM, str(int(START.timestamp())))),
        bot=bot,
        config=config,
        booking_service=booking_service,
    )

    booking_service.create.assert_called_once()
    text = bot.send_message.call_args.args[1]
    assert "уже запис" in text.lower()
    assert "10:00" in text


async def test_confirm_stale_slot_is_friendly(config: Config) -> None:
    bot = AsyncMock()
    booking_service = MagicMock()
    booking_service.create.side_effect = SlotNotToday("passed")

    await handle_confirm(
        _callback(pack(ACTION_CONFIRM, str(int(START.timestamp())))),
        bot=bot,
        config=config,
        booking_service=booking_service,
    )

    text = bot.send_message.call_args.args[1]
    assert "недоступ" in text.lower()


# --- свои брони -------------------------------------------------------------


async def test_mybookings_lists_active_in_moscow_tz(config: Config) -> None:
    bot = AsyncMock()
    booking_service = MagicMock()
    booking_service.list_active_for_client.return_value = [_booking()]

    await handle_my_bookings(
        _message(),
        bot=bot,
        config=config,
        booking_service=booking_service,
    )

    booking_service.list_active_for_client.assert_called_once_with(CLIENT_ID)
    markup = _reply_markup(bot.send_message)
    buttons = [btn for row in markup.inline_keyboard for btn in row]
    assert len(buttons) == 1
    assert "10:00–10:20" in buttons[0].text
    assert unpack(buttons[0].callback_data) == (ACTION_CANCEL, _booking().id)


async def test_mybookings_empty_shows_message_without_error(
    config: Config,
) -> None:
    bot = AsyncMock()
    booking_service = MagicMock()
    booking_service.list_active_for_client.return_value = []

    await handle_my_bookings(
        _message(),
        bot=bot,
        config=config,
        booking_service=booking_service,
    )

    text = bot.send_message.call_args.args[1]
    assert "нет" in text.lower()
    assert _reply_markup(bot.send_message) is None


# --- отмена с шагом подтверждения -------------------------------------------


async def test_cancel_request_shows_confirm_step(config: Config) -> None:
    bot = AsyncMock()
    booking_service = MagicMock()
    booking_service.get.return_value = _booking()

    await handle_cancel_request(
        _callback(pack(ACTION_CANCEL, _booking().id)),
        bot=bot,
        config=config,
        booking_service=booking_service,
    )

    assert _markup_actions(_reply_markup(bot.send_message)) == {
        ACTION_CANCEL_CONFIRM
    }
    booking_service.cancel.assert_not_called()


async def test_cancel_request_unknown_booking_is_friendly(
    config: Config,
) -> None:
    bot = AsyncMock()
    booking_service = MagicMock()
    booking_service.get.return_value = None

    await handle_cancel_request(
        _callback(pack(ACTION_CANCEL, "missing-id")),
        bot=bot,
        config=config,
        booking_service=booking_service,
    )

    assert _reply_markup(bot.send_message) is None
    text = bot.send_message.call_args.args[1]
    assert "не найдена" in text.lower()


# --- отмена клиентом уведомляет администратора ------------------------------


async def test_cancel_confirm_cancels_and_notifies_admin(
    config: Config,
) -> None:
    bot = AsyncMock()
    bot.get_chat = AsyncMock(
        return_value=SimpleNamespace(
            first_name="Иван", last_name="Иванов", username="ivanov"
        )
    )
    booking_service = MagicMock()
    booking_service.cancel.return_value = _booking()

    await handle_cancel_confirm(
        _callback(pack(ACTION_CANCEL_CONFIRM, _booking().id)),
        bot=bot,
        config=config,
        booking_service=booking_service,
    )

    booking_service.cancel.assert_called_once_with(_booking().id)
    # Клиенту — подтверждение отмены.
    bot.send_message.assert_any_await(CLIENT_ID, "Запись отменена.")
    # Администратору — уведомление с человекочитаемым именем и диапазоном.
    admin_call = next(
        call
        for call in bot.send_message.await_args_list
        if call.args[0] == ADMIN_ID
    )
    assert admin_call.args[1] == (
        "Пользователь Иван Иванов (@ivanov) отменил запись на 10:00–10:20."
    )


async def test_cancel_confirm_admin_notify_failure_does_not_raise(
    config: Config,
) -> None:
    bot = AsyncMock()
    bot.get_chat = AsyncMock(
        return_value=SimpleNamespace(
            first_name=None, last_name=None, username=None
        )
    )
    # Клиенту — успех, администратору — сбой доставки.
    bot.send_message.side_effect = [None, RuntimeError("admin unreachable")]
    booking_service = MagicMock()
    booking_service.cancel.return_value = _booking()

    await handle_cancel_confirm(
        _callback(pack(ACTION_CANCEL_CONFIRM, _booking().id)),
        bot=bot,
        config=config,
        booking_service=booking_service,
    )

    # Отмена выполнена, несмотря на сбой уведомления администратора.
    booking_service.cancel.assert_called_once_with(_booking().id)
