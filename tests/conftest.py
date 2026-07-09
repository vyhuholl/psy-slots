from __future__ import annotations

from collections.abc import Iterator

import pytest

# Валидный по формату тестовый токен (не настоящий).
TEST_BOT_TOKEN = "123456789:AAExampleTokenForTestsOnly-0123456789"
TEST_WEBHOOK_SECRET = "test-webhook-secret"
TEST_YDB_ENDPOINT = "grpcs://localhost:2135"
TEST_YDB_DATABASE = "/local"


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Задать все обязательные переменные окружения приложения."""
    monkeypatch.setenv("BOT_TOKEN", TEST_BOT_TOKEN)
    monkeypatch.setenv("WEBHOOK_SECRET", TEST_WEBHOOK_SECRET)
    monkeypatch.setenv("YDB_ENDPOINT", TEST_YDB_ENDPOINT)
    monkeypatch.setenv("YDB_DATABASE", TEST_YDB_DATABASE)
    yield
