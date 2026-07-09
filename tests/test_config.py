from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest

from app.config import Config, ConfigError, TimeInterval, load_config
from tests.conftest import (
    TEST_ADMIN_TELEGRAM_ID,
    TEST_BOOKING_UNAVAILABLE_MESSAGE,
    TEST_BOT_TOKEN,
    TEST_TIMEZONE,
    TEST_WEBHOOK_SECRET,
    TEST_WELCOME_MESSAGE,
    TEST_YDB_DATABASE,
    TEST_YDB_ENDPOINT,
)


def test_load_config_reads_all_variables(env: None) -> None:
    config = load_config()

    assert isinstance(config, Config)
    assert config.bot_token == TEST_BOT_TOKEN
    assert config.webhook_secret == TEST_WEBHOOK_SECRET
    assert config.ydb_endpoint == TEST_YDB_ENDPOINT
    assert config.ydb_database == TEST_YDB_DATABASE
    assert config.admin_telegram_id == int(TEST_ADMIN_TELEGRAM_ID)
    assert config.timezone == ZoneInfo(TEST_TIMEZONE)
    assert config.welcome_message == TEST_WELCOME_MESSAGE
    assert (
        config.booking_unavailable_message == TEST_BOOKING_UNAVAILABLE_MESSAGE
    )
    # SLOT_DURATION_MINUTES не задан в окружении → дефолт 20.
    assert config.slot_duration_minutes == 20
    assert config.availability_intervals == (
        TimeInterval(start_minute=600, end_minute=840),
        TimeInterval(start_minute=900, end_minute=1080),
    )


@pytest.mark.parametrize(
    "missing",
    [
        "BOT_TOKEN",
        "WEBHOOK_SECRET",
        "YDB_ENDPOINT",
        "YDB_DATABASE",
        "ADMIN_TELEGRAM_ID",
        "AVAILABILITY_INTERVALS",
        "TIMEZONE",
        "WELCOME_MESSAGE",
        "BOOKING_UNAVAILABLE_MESSAGE",
    ],
)
def test_load_config_missing_variable_raises(
    env: None, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    monkeypatch.delenv(missing, raising=False)

    with pytest.raises(ConfigError) as excinfo:
        load_config()

    assert missing in str(excinfo.value)


def test_load_config_empty_variable_raises(
    env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BOT_TOKEN", "")

    with pytest.raises(ConfigError):
        load_config()


# --- Длительность слота ---------------------------------------------------


def test_slot_duration_custom_value(
    env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SLOT_DURATION_MINUTES", "30")

    assert load_config().slot_duration_minutes == 30


@pytest.mark.parametrize("value", ["0", "-5", "abc", "20.5"])
def test_slot_duration_invalid_raises(
    env: None, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("SLOT_DURATION_MINUTES", value)

    with pytest.raises(ConfigError):
        load_config()


# --- Интервалы доступности ------------------------------------------------


def test_availability_single_interval(
    env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AVAILABILITY_INTERVALS", "09:30-10:00")

    assert load_config().availability_intervals == (
        TimeInterval(start_minute=570, end_minute=600),
    )


def test_availability_adjacent_intervals_ok(
    env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AVAILABILITY_INTERVALS", "10:00-12:00,12:00-14:00")

    assert load_config().availability_intervals == (
        TimeInterval(start_minute=600, end_minute=720),
        TimeInterval(start_minute=720, end_minute=840),
    )


@pytest.mark.parametrize(
    "value",
    [
        "10:00",  # нет конца
        "14:00-10:00",  # начало не раньше конца
        "10:00-10:00",  # нулевая длина
        "10:00-14:00,13:00-18:00",  # пересечение
        "25:00-26:00",  # вне суток
        "10:60-11:00",  # минуты вне диапазона
        "abc",  # мусор
    ],
)
def test_availability_invalid_raises(
    env: None, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("AVAILABILITY_INTERVALS", value)

    with pytest.raises(ConfigError):
        load_config()


# --- Таймзона -------------------------------------------------------------


def test_timezone_invalid_raises(
    env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TIMEZONE", "Not/AZone")

    with pytest.raises(ConfigError):
        load_config()


# --- Идентификатор администратора -----------------------------------------


def test_admin_id_invalid_raises(
    env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", "not-a-number")

    with pytest.raises(ConfigError):
        load_config()
