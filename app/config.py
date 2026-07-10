"""Типизированная загрузка конфигурации из переменных окружения.

Психолог один; его параметры и тексты читаются только из окружения функции:
длительность слота, интервалы доступности (только время суток, без дня недели),
тексты сообщений и идентификатор администратора. Отсутствие обязательной
переменной или недопустимое значение — явная ошибка на этапе инициализации.

Таймзона не настраивается: она фиксирована как ``Europe/Moscow`` (в ней
трактуются интервалы доступности и показывается время). Хранение в БД — в UTC.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Длительность слота по умолчанию, если переменная не задана.
DEFAULT_SLOT_DURATION_MINUTES = 20
# Минут в сутках — верхняя граница интервалов доступности.
_MINUTES_PER_DAY = 24 * 60
# Фиксированная таймзона показа и трактовки интервалов (не из окружения).
MOSCOW_TZ = ZoneInfo("Europe/Moscow")


class ConfigError(RuntimeError):
    """Обязательная переменная отсутствует, пуста или недопустима."""


@dataclass(frozen=True)
class TimeInterval:
    """Интервал времени суток в минутах от полуночи (без дня недели)."""

    start_minute: int
    end_minute: int


def _parse_time_of_day(value: str) -> int:
    """Разобрать ``HH:MM`` в минуты от полуночи, провалидировав границы."""
    hours_str, sep, minutes_str = value.partition(":")
    if not sep or not hours_str.isdigit() or not minutes_str.isdigit():
        raise ValueError(f"Invalid time of day: {value!r}")
    hours, minutes = int(hours_str), int(minutes_str)
    if minutes >= 60:
        raise ValueError(f"Invalid minutes in time of day: {value!r}")
    total = hours * 60 + minutes
    if total > _MINUTES_PER_DAY:
        raise ValueError(f"Time of day out of bounds: {value!r}")
    return total


class Config(BaseSettings):
    """Разобранная конфигурация приложения (из переменных окружения)."""

    model_config = SettingsConfigDict(
        frozen=True,
        case_sensitive=False,
        extra="ignore",
        arbitrary_types_allowed=True,
    )

    bot_token: str = Field(min_length=1)
    webhook_secret: str = Field(min_length=1)
    ydb_endpoint: str = Field(min_length=1)
    ydb_database: str = Field(min_length=1)
    admin_telegram_id: int
    slot_duration_minutes: int = Field(
        default=DEFAULT_SLOT_DURATION_MINUTES, gt=0
    )
    availability_intervals: Annotated[tuple[TimeInterval, ...], NoDecode]
    welcome_message: str = Field(min_length=1)
    booking_unavailable_message: str = Field(min_length=1)

    @property
    def timezone(self) -> ZoneInfo:
        """Фиксированная таймзона Europe/Moscow (показ и трактовка интервалов)."""
        return MOSCOW_TZ

    @field_validator("availability_intervals", mode="before")
    @classmethod
    def _parse_intervals(cls, value: object) -> object:
        """Разобрать ``10:00-14:00,15:00-18:00`` в набор интервалов."""
        if not isinstance(value, str):
            return value
        intervals: list[TimeInterval] = []
        for chunk in value.split(","):
            start_str, sep, end_str = chunk.strip().partition("-")
            if not sep:
                raise ValueError(f"Invalid availability interval: {chunk!r}")
            start = _parse_time_of_day(start_str.strip())
            end = _parse_time_of_day(end_str.strip())
            if start >= end:
                raise ValueError(
                    f"Interval start must be before end: {chunk!r}"
                )
            intervals.append(TimeInterval(start_minute=start, end_minute=end))

        ordered = sorted(intervals, key=lambda i: i.start_minute)
        for previous, current in zip(ordered, ordered[1:]):
            if current.start_minute < previous.end_minute:
                raise ValueError("Availability intervals must not overlap")
        return tuple(ordered)


def load_config() -> Config:
    """Прочитать и провалидировать конфигурацию из окружения."""
    try:
        return Config()
    except ValidationError as exc:
        names = sorted(
            {str(err["loc"][0]).upper() for err in exc.errors() if err["loc"]}
        )
        detail = ", ".join(names) if names else str(exc)
        raise ConfigError(f"Invalid configuration: {detail}") from exc
