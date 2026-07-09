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
    handle_set_timezone,
    handle_slot,
    handle_start,
    handle_timezone,
)
from app.bot.keyboards import (
    ACTION_CANCEL,
    ACTION_CANCEL_CONFIRM,
    ACTION_CONFIRM,
    ACTION_SLOT,
    ACTION_TZ,
    pack,
    unpack,
)
from app.config import Config, load_config
from app.domain.booking import (
    Booking,
    BookingStatus,
    SlotNotToday,
    SlotTaken,
)
from app.domain.client import Client
from app.domain.slots import Slot
from tests.conftest import (
    TEST_BOOKING_UNAVAILABLE_MESSAGE,
    TEST_WELCOME_MESSAGE,
)

CLIENT_ID = 42
NOW = datetime(2026, 7, 9, 6, 0, tzinfo=UTC)
START = datetime(2026, 7, 9, 7, 0, tzinfo=UTC)  # 10:00 MSK


@pytest.fixture
def config(env: None) -> Config:
    return load_config()


def _client(tz: str = "Europe/Moscow") -> Client:
    return Client(telegram_id=CLIENT_ID, timezone=tz, created_at=NOW)


def _booking(start: datetime = START) -> Booking:
    return Booking(
        id="11111111-1111-4111-8111-111111111111",
        client_id=CLIENT_ID,
        start=start,
        end=start + timedelta(minutes=20),
        status=BookingStatus.BOOKED,
        created_at=NOW,
    )


def _message() -> Any:
    return SimpleNamespace(
        from_user=SimpleNamespace(id=CLIENT_ID),
        chat=SimpleNamespace(id=CLIENT_ID),
        answer=AsyncMock(),
    )


def _callback(data: str) -> Any:
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=CLIENT_ID),
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


# --- 4.1 приветствие --------------------------------------------------------


async def test_start_shows_welcome_from_config(config: Config) -> None:
    message = _message()

    await handle_start(message, config=config)

    message.answer.assert_awaited_once_with(TEST_WELCOME_MESSAGE)


# --- 4.2 запрос/сохранение таймзоны ----------------------------------------


async def test_book_without_timezone_requests_it(config: Config) -> None:
    bot = AsyncMock()
    client_service = MagicMock()
    client_service.get.return_value = None
    slot_service = MagicMock()

    await handle_book(
        _message(),
        bot=bot,
        config=config,
        client_service=client_service,
        slot_service=slot_service,
    )

    # Показана клавиатура выбора таймзоны; слоты не запрашивались.
    assert _markup_actions(_reply_markup(bot.send_message)) == {ACTION_TZ}
    slot_service.list_free_slots.assert_not_called()


async def test_set_timezone_saves_and_continues_to_slots(
    config: Config,
) -> None:
    bot = AsyncMock()
    client_service = MagicMock()
    client_service.set_timezone.return_value = _client()
    slot_service = MagicMock()
    slot_service.list_free_slots.return_value = [
        Slot(start=START, end=START + timedelta(minutes=20))
    ]

    await handle_set_timezone(
        _callback(pack(ACTION_TZ, "Europe/Moscow")),
        bot=bot,
        config=config,
        client_service=client_service,
        slot_service=slot_service,
    )

    client_service.set_timezone.assert_called_once_with(
        CLIENT_ID, "Europe/Moscow"
    )
    # После сохранения показаны слоты.
    assert _markup_actions(_reply_markup(bot.send_message)) == {ACTION_SLOT}


# --- 4.3 / 4.4 показ слотов / нет слотов -----------------------------------


async def test_book_with_timezone_lists_todays_slots(config: Config) -> None:
    bot = AsyncMock()
    client_service = MagicMock()
    client_service.get.return_value = _client()
    slot_service = MagicMock()
    slot_service.list_free_slots.return_value = [
        Slot(start=START, end=START + timedelta(minutes=20)),
        Slot(
            start=START + timedelta(minutes=20),
            end=START + timedelta(minutes=40),
        ),
    ]

    await handle_book(
        _message(),
        bot=bot,
        config=config,
        client_service=client_service,
        slot_service=slot_service,
    )

    markup = _reply_markup(bot.send_message)
    buttons = [btn for row in markup.inline_keyboard for btn in row]
    assert len(buttons) == 2
    # Время в таймзоне клиента: 07:00 UTC → 10:00 MSK.
    assert buttons[0].text == "10:00"
    assert unpack(buttons[0].callback_data)[0] == ACTION_SLOT


async def test_book_without_free_slots_shows_unavailable(
    config: Config,
) -> None:
    bot = AsyncMock()
    client_service = MagicMock()
    client_service.get.return_value = _client()
    slot_service = MagicMock()
    slot_service.list_free_slots.return_value = []

    await handle_book(
        _message(),
        bot=bot,
        config=config,
        client_service=client_service,
        slot_service=slot_service,
    )

    bot.send_message.assert_awaited_once_with(
        CLIENT_ID, TEST_BOOKING_UNAVAILABLE_MESSAGE
    )


# --- slot: → шаг подтверждения ---------------------------------------------


async def test_slot_shows_confirmation(config: Config) -> None:
    bot = AsyncMock()
    client_service = MagicMock()
    client_service.get.return_value = _client()

    await handle_slot(
        _callback(pack(ACTION_SLOT, str(int(START.timestamp())))),
        bot=bot,
        config=config,
        client_service=client_service,
    )

    markup = _reply_markup(bot.send_message)
    assert _markup_actions(markup) == {ACTION_CONFIRM}


# --- 4.5 успешное подтверждение --------------------------------------------


async def test_confirm_creates_booking_and_confirms(config: Config) -> None:
    bot = AsyncMock()
    client_service = MagicMock()
    client_service.get.return_value = _client()
    booking_service = MagicMock()
    booking_service.create.return_value = _booking()

    await handle_confirm(
        _callback(pack(ACTION_CONFIRM, str(int(START.timestamp())))),
        bot=bot,
        config=config,
        client_service=client_service,
        booking_service=booking_service,
    )

    booking_service.create.assert_called_once_with(
        client_id=CLIENT_ID, start=START
    )
    text = bot.send_message.call_args.args[1]
    assert "10:00" in text  # подтверждение во времени клиента


# --- 4.6 занятый слот -------------------------------------------------------


async def test_confirm_slot_taken_by_other_is_friendly(
    config: Config,
) -> None:
    bot = AsyncMock()
    client_service = MagicMock()
    client_service.get.return_value = _client()
    booking_service = MagicMock()
    booking_service.create.side_effect = SlotTaken("taken")
    booking_service.list_active_for_client.return_value = []  # чужая бронь

    await handle_confirm(
        _callback(pack(ACTION_CONFIRM, str(int(START.timestamp())))),
        bot=bot,
        config=config,
        client_service=client_service,
        booking_service=booking_service,
    )

    # Одна попытка создания, без второй брони и без исключения.
    booking_service.create.assert_called_once()
    text = bot.send_message.call_args.args[1]
    assert "друг" in text.lower()  # «выберите другой»


# --- 4.7 повторное подтверждение -------------------------------------------


async def test_confirm_repeat_shows_existing_booking(config: Config) -> None:
    bot = AsyncMock()
    client_service = MagicMock()
    client_service.get.return_value = _client()
    booking_service = MagicMock()
    booking_service.create.side_effect = SlotTaken("taken")
    # У клиента уже есть бронь на этот слот (повтор/двойной тап).
    booking_service.list_active_for_client.return_value = [_booking()]

    await handle_confirm(
        _callback(pack(ACTION_CONFIRM, str(int(START.timestamp())))),
        bot=bot,
        config=config,
        client_service=client_service,
        booking_service=booking_service,
    )

    booking_service.create.assert_called_once()
    text = bot.send_message.call_args.args[1]
    assert "уже запис" in text.lower()  # показана существующая бронь
    assert "10:00" in text


# --- 5.1 просмотр своих броней ---------------------------------------------


async def test_mybookings_lists_active_in_client_tz(config: Config) -> None:
    bot = AsyncMock()
    client_service = MagicMock()
    client_service.get.return_value = _client()
    booking_service = MagicMock()
    booking_service.list_active_for_client.return_value = [_booking()]

    await handle_my_bookings(
        _message(),
        bot=bot,
        config=config,
        client_service=client_service,
        booking_service=booking_service,
    )

    booking_service.list_active_for_client.assert_called_once_with(CLIENT_ID)
    markup = _reply_markup(bot.send_message)
    buttons = [btn for row in markup.inline_keyboard for btn in row]
    assert len(buttons) == 1
    # Время в таймзоне клиента и действие отмены на кнопке.
    assert "10:00–10:20" in buttons[0].text
    assert unpack(buttons[0].callback_data) == (ACTION_CANCEL, _booking().id)


async def test_mybookings_empty_shows_message_without_error(
    config: Config,
) -> None:
    bot = AsyncMock()
    client_service = MagicMock()
    client_service.get.return_value = _client()
    booking_service = MagicMock()
    booking_service.list_active_for_client.return_value = []

    await handle_my_bookings(
        _message(),
        bot=bot,
        config=config,
        client_service=client_service,
        booking_service=booking_service,
    )

    text = bot.send_message.call_args.args[1]
    assert "нет" in text.lower()
    # Без клавиатуры при пустом списке.
    assert _reply_markup(bot.send_message) is None


# --- 5.2 отмена с шагом подтверждения --------------------------------------


async def test_cancel_request_shows_confirm_step(config: Config) -> None:
    bot = AsyncMock()
    client_service = MagicMock()
    client_service.get.return_value = _client()
    booking_service = MagicMock()
    booking_service.get.return_value = _booking()

    await handle_cancel_request(
        _callback(pack(ACTION_CANCEL, _booking().id)),
        bot=bot,
        config=config,
        client_service=client_service,
        booking_service=booking_service,
    )

    # Показан confirm-шаг; сама отмена ещё не выполнена.
    assert _markup_actions(_reply_markup(bot.send_message)) == {
        ACTION_CANCEL_CONFIRM
    }
    booking_service.cancel.assert_not_called()


async def test_cancel_confirm_cancels_via_service(config: Config) -> None:
    bot = AsyncMock()
    client_service = MagicMock()
    client_service.get.return_value = _client()
    booking_service = MagicMock()
    booking_service.cancel.return_value = _booking().cancelled(NOW)

    await handle_cancel_confirm(
        _callback(pack(ACTION_CANCEL_CONFIRM, _booking().id)),
        bot=bot,
        booking_service=booking_service,
    )

    booking_service.cancel.assert_called_once_with(_booking().id)
    text = bot.send_message.call_args.args[1]
    assert "отмен" in text.lower()


# --- прочие ветки -----------------------------------------------------------


async def test_timezone_command_offers_zone_choice(config: Config) -> None:
    bot = AsyncMock()

    await handle_timezone(_message(), bot=bot)

    assert _markup_actions(_reply_markup(bot.send_message)) == {ACTION_TZ}


async def test_confirm_stale_slot_is_friendly(config: Config) -> None:
    # Устаревшая клавиатура: слот уже не на сегодня → дружелюбная ошибка.
    bot = AsyncMock()
    client_service = MagicMock()
    client_service.get.return_value = _client()
    booking_service = MagicMock()
    booking_service.create.side_effect = SlotNotToday("passed")

    await handle_confirm(
        _callback(pack(ACTION_CONFIRM, str(int(START.timestamp())))),
        bot=bot,
        config=config,
        client_service=client_service,
        booking_service=booking_service,
    )

    text = bot.send_message.call_args.args[1]
    assert "недоступ" in text.lower()


async def test_cancel_request_unknown_booking_is_friendly(
    config: Config,
) -> None:
    bot = AsyncMock()
    client_service = MagicMock()
    client_service.get.return_value = _client()
    booking_service = MagicMock()
    booking_service.get.return_value = None

    await handle_cancel_request(
        _callback(pack(ACTION_CANCEL, "missing-id")),
        bot=bot,
        config=config,
        client_service=client_service,
        booking_service=booking_service,
    )

    # Нет клавиатуры подтверждения; сообщение об отсутствии брони.
    assert _reply_markup(bot.send_message) is None
    text = bot.send_message.call_args.args[1]
    assert "не найдена" in text.lower()
