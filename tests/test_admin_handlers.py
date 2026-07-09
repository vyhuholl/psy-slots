"""Тесты админ-хендлеров (авторизация, просмотр, отмена).

Тесты TDD: сначала падающие тесты, затем реализация. Хендлеры тонкие —
проверяют только интеграцию с сервисами и форматирование ответа.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from app.bot.keyboards import pack
from app.config import Config, load_config
from app.domain.booking import Booking, BookingStatus
from tests.conftest import TEST_ADMIN_TELEGRAM_ID

# --- Константы --------------------------------------------------------------

ADMIN_ID = int(TEST_ADMIN_TELEGRAM_ID)  # 42 из conftest
OTHER_ID = 999  # Не-админ
CLIENT_ID = 123  # ID клиента для уведомлений
NOW = datetime(2026, 7, 9, 7, 0, tzinfo=UTC)
START = datetime(2026, 7, 9, 7, 0, tzinfo=UTC)  # 10:00 MSK


def _message(user_id: int) -> Any:
    return SimpleNamespace(
        from_user=SimpleNamespace(id=user_id),
        chat=SimpleNamespace(id=user_id),
        answer=AsyncMock(),
    )


def _callback(data: str, user_id: int) -> Any:
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=user_id),
        answer=AsyncMock(),
    )


def _booking(start: datetime = START, client_id: int = CLIENT_ID) -> Booking:
    return Booking(
        id="11111111-1111-4111-8111-111111111111",
        client_id=client_id,
        start=start,
        end=start + timedelta(minutes=20),
        status=BookingStatus.BOOKED,
        created_at=NOW,
    )


# --- 1.1 Авторизация --------------------------------------------------------

# Этот тест падает, т.к. хендлер админ-команд ещё не реализован.
# После реализации 1.2 он станет зелёным (1.3).


@pytest.fixture
def config(env: None) -> Config:
    return load_config()


async def test_admin_command_granted_to_admin(config: Config) -> None:
    """Администратор (id = ADMIN_TELEGRAM_ID) получает доступ к админ-меню."""
    bot = AsyncMock()
    booking_service = MagicMock()
    # Сервис замокан — проверяем только авторизацию, не логику списка.
    booking_service.list_active.return_value = []

    # Импорт после создания mocks для avoidance of circular imports
    # Хендлер будет реализован в 1.2
    from app.bot.handlers.admin import handle_admin_list

    await handle_admin_list(
        _message(ADMIN_ID),
        bot=bot,
        config=config,
        booking_service=booking_service,
    )

    # Админ видит ответ (список броней или сообщение об отсутствии)
    bot.send_message.assert_awaited_once()


async def test_admin_command_denied_to_non_admin(config: Config) -> None:
    """Не-администратор получает отказ, управляющие действия не показываются."""
    bot = AsyncMock()
    booking_service = MagicMock()

    from app.bot.handlers.admin import handle_admin_list

    await handle_admin_list(
        _message(OTHER_ID),
        bot=bot,
        config=config,
        booking_service=booking_service,
    )

    # Сервис не вызывался — доступ запрещён на входе
    booking_service.list_active.assert_not_called()
    # Сообщение об отказе (а не список броней)
    text = bot.send_message.call_args.args[1]
    assert "прав" in text.lower() or "доступ" in text.lower()


# --- 2.1 Просмотр броней ---------------------------------------------------

# Эти тесты падают, т.к. хендлер просмотра ещё не реализован.
# После реализации 2.2 они станут зелёными (2.3).


async def test_admin_list_shows_active_bookings_in_config_tz(
    config: Config,
) -> None:
    """Администратор видит список активных броней во времени конфигурации."""
    bot = AsyncMock()
    booking_service = MagicMock()
    booking_service.list_active.return_value = [
        _booking(start=START, client_id=CLIENT_ID),
        _booking(
            start=START + timedelta(minutes=20),
            client_id=456,
        ),
    ]

    from app.bot.handlers.admin import handle_admin_list

    await handle_admin_list(
        _message(ADMIN_ID),
        bot=bot,
        config=config,
        booking_service=booking_service,
    )

    booking_service.list_active.assert_called_once()
    # Проверяем клавиатуру - время в ней должно быть в таймзоне конфигурации
    markup = bot.send_message.call_args.kwargs.get("reply_markup")
    buttons = [btn for row in markup.inline_keyboard for btn in row]
    assert len(buttons) == 2
    # Время в таймзоне конфигурации (Europe/Moscow = UTC+3): 07:00 UTC → 10:00 MSK
    assert "10:00" in buttons[0].text
    assert str(CLIENT_ID) in buttons[0].text  # client id shown


async def test_admin_list_empty_shows_message_without_error(
    config: Config,
) -> None:
    """Пустой список броней → сообщение без ошибки."""
    bot = AsyncMock()
    booking_service = MagicMock()
    booking_service.list_active.return_value = []

    from app.bot.handlers.admin import handle_admin_list

    await handle_admin_list(
        _message(ADMIN_ID),
        bot=bot,
        config=config,
        booking_service=booking_service,
    )

    booking_service.list_active.assert_called_once()
    text = bot.send_message.call_args.args[1]
    assert "нет" in text.lower() or "пуст" in text.lower()


# --- 3.1-3.2 Отмена брони -----------------------------------------------------

# Эти тесты падают, т.к. хендлеры отмены ещё не реализованы.
# После реализации 3.3 они станут зелёными (3.4).


async def test_admin_cancel_cancels_via_service_and_notifies_client(
    config: Config,
) -> None:
    """Отмена брони → вызов booking_service.cancel + уведомление клиента."""
    bot = AsyncMock()
    booking_service = MagicMock()
    booking_service.cancel.return_value = _booking().cancelled(NOW)
    client_service = MagicMock()
    # Для получения TZ клиента при отправке уведомления
    from app.domain.client import Client

    client_service.get.return_value = Client(
        telegram_id=CLIENT_ID,
        timezone="Europe/Moscow",
        created_at=NOW,
    )

    from app.bot.handlers.admin import handle_admin_cancel_confirm

    booking_id = _booking().id
    await handle_admin_cancel_confirm(
        _callback(pack("admincancel", booking_id), ADMIN_ID),
        bot=bot,
        config=config,
        booking_service=booking_service,
        client_service=client_service,
    )

    # Отмена через сервис
    booking_service.cancel.assert_called_once_with(booking_id)
    # Уведомление клиенту
    bot.send_message.assert_any_call(CLIENT_ID, ANY)


async def test_admin_cancel_already_cancelled_is_idempotent(
    config: Config,
) -> None:
    """Отмена уже отменённой брони → без ошибки и без повторного эффекта."""
    bot = AsyncMock()
    booking_service = MagicMock()
    # Сервис возвращает уже отменённую бронь
    cancelled = _booking().cancelled(NOW)
    booking_service.cancel.return_value = cancelled
    client_service = MagicMock()
    from app.domain.client import Client

    client_service.get.return_value = Client(
        telegram_id=CLIENT_ID,
        timezone="Europe/Moscow",
        created_at=NOW,
    )

    from app.bot.handlers.admin import handle_admin_cancel_confirm

    await handle_admin_cancel_confirm(
        _callback(pack("admincancel", _booking().id), ADMIN_ID),
        bot=bot,
        config=config,
        booking_service=booking_service,
        client_service=client_service,
    )

    # Сервис вызван (идемпотентно)
    booking_service.cancel.assert_called_once()
    # Уведомление отправлено
    bot.send_message.assert_called()
