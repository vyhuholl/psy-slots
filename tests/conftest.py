from __future__ import annotations

from collections.abc import Iterator

import pytest

# Валидный по формату тестовый токен (не настоящий).
TEST_BOT_TOKEN = "123456789:AAExampleTokenForTestsOnly-0123456789"
TEST_WEBHOOK_SECRET = "test-webhook-secret"
TEST_YDB_ENDPOINT = "grpcs://localhost:2135"
TEST_YDB_DATABASE = "/local"
TEST_ADMIN_TELEGRAM_ID = "42"
TEST_AVAILABILITY_INTERVALS = "10:00-14:00,15:00-18:00"
TEST_TIMEZONE = "Europe/Moscow"
TEST_WELCOME_MESSAGE = "Добро пожаловать!"
TEST_BOOKING_UNAVAILABLE_MESSAGE = "На сегодня свободных слотов нет."


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Задать все обязательные переменные окружения приложения.

    ``SLOT_DURATION_MINUTES`` намеренно не задаётся — по умолчанию 20 минут.
    """
    monkeypatch.setenv("BOT_TOKEN", TEST_BOT_TOKEN)
    monkeypatch.setenv("WEBHOOK_SECRET", TEST_WEBHOOK_SECRET)
    monkeypatch.setenv("YDB_ENDPOINT", TEST_YDB_ENDPOINT)
    monkeypatch.setenv("YDB_DATABASE", TEST_YDB_DATABASE)
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", TEST_ADMIN_TELEGRAM_ID)
    monkeypatch.setenv("AVAILABILITY_INTERVALS", TEST_AVAILABILITY_INTERVALS)
    monkeypatch.setenv("WELCOME_MESSAGE", TEST_WELCOME_MESSAGE)
    monkeypatch.setenv(
        "BOOKING_UNAVAILABLE_MESSAGE", TEST_BOOKING_UNAVAILABLE_MESSAGE
    )
    monkeypatch.delenv("SLOT_DURATION_MINUTES", raising=False)
    yield
