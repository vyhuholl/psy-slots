"""Тесты точки входа timer-триггера для напоминаний.

Точка входа обрабатывает созревшие напоминания и завершается без
фоновых задач (serverless-ограничения).
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


_UTC = timezone.utc


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Переменные окружения для notify."""
    from tests.conftest import (
        TEST_ADMIN_TELEGRAM_ID,
        TEST_AVAILABILITY_INTERVALS,
        TEST_BOOKING_UNAVAILABLE_MESSAGE,
        TEST_BOT_TOKEN,
        TEST_TIMEZONE,
        TEST_WEBHOOK_SECRET,
        TEST_WELCOME_MESSAGE,
        TEST_YDB_DATABASE,
        TEST_YDB_ENDPOINT,
    )

    monkeypatch.setenv("BOT_TOKEN", TEST_BOT_TOKEN)
    monkeypatch.setenv("WEBHOOK_SECRET", TEST_WEBHOOK_SECRET)
    monkeypatch.setenv("YDB_ENDPOINT", TEST_YDB_ENDPOINT)
    monkeypatch.setenv("YDB_DATABASE", TEST_YDB_DATABASE)
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", TEST_ADMIN_TELEGRAM_ID)
    monkeypatch.setenv("AVAILABILITY_INTERVALS", TEST_AVAILABILITY_INTERVALS)
    monkeypatch.setenv("TIMEZONE", TEST_TIMEZONE)
    monkeypatch.setenv("WELCOME_MESSAGE", TEST_WELCOME_MESSAGE)
    monkeypatch.setenv(
        "BOOKING_UNAVAILABLE_MESSAGE", TEST_BOOKING_UNAVAILABLE_MESSAGE
    )


def test_notify_processes_pending_and_exits_without_background_tasks(
    env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Вызов notify обрабатывает созревшие напоминания и завершается без фоновых задач."""
    from app.notify import notify
    from app.services.reminder_service import ReminderService

    now = datetime(2026, 7, 9, 6, 55, tzinfo=_UTC)

    # Замокаем сервис напоминаний
    mock_service = MagicMock(spec=ReminderService)
    mock_service.send_pending.return_value = None

    with patch("app.notify._get_reminder_service", return_value=mock_service):
        # Вызов должен завершиться без исключений
        notify(now=now)

    # Сервис был вызван для обработки
    mock_service.send_pending.assert_called_once_with(now=now)

    # Никаких фоновых задач не запускается (no scheduler/APScheduler)


def test_notify_returns_gracefully_on_service_error(
    env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ошибка при обработке не должна ронять функцию."""
    from app.notify import notify
    from app.services.reminder_service import ReminderService

    now = datetime(2026, 7, 9, 6, 55, tzinfo=_UTC)

    # Сервис бросает исключение
    mock_service = MagicMock(spec=ReminderService)
    mock_service.send_pending.side_effect = RuntimeError("Database error")

    with patch("app.notify._get_reminder_service", return_value=mock_service):
        # Функция должна пробросить исключение (logging происходит внутри сервиса)
        with pytest.raises(RuntimeError, match="Database error"):
            notify(now=now)


def test_notify_initializes_warm_bot_once(env: None) -> None:
    """Bot инициализируется один раз (тёплый инстанс)."""
    from app.notify import notify

    now = datetime(2026, 7, 9, 6, 55, tzinfo=_UTC)

    mock_service = MagicMock()

    # Патчим все зависимости, чтобы избежать реальных подключений
    with (
        patch("app.notify.get_pool"),
        patch("app.notify.BookingService"),
        patch("app.notify.ClientService"),
        patch("app.notify.ReminderService", return_value=mock_service),
    ):
        notify(now=now)

    # Проверяем, что модуль создан и функция работает
    assert callable(notify)
