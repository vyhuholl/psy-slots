"""Доменная модель психолога и её ошибки.

Неизменяемая типизированная сущность специалиста: неизменный id, имя,
редактируемая длительность слота (минуты, > 0) и таймзона (корректный
IANA-идентификатор). Валидация выполняется при создании модели. Модель не
знает про YDB и Telegram — доступ к хранилищу лежит в сервисном слое.
"""

from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ValidationError(Exception):
    """Данные специалиста не прошли доменную валидацию."""


class SpecialistNotFound(Exception):
    """Специалист с запрошенным id отсутствует в реестре."""


def validate_duration(slot_duration_minutes: int) -> None:
    """Длительность слота обязана быть строго положительной."""
    if slot_duration_minutes <= 0:
        raise ValidationError(
            "Длительность слота должна быть > 0, получено: "
            f"{slot_duration_minutes}"
        )


def validate_timezone(timezone: str) -> None:
    """Таймзона обязана быть корректным IANA-идентификатором."""
    try:
        ZoneInfo(timezone)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ValidationError(
            f"Некорректный IANA-идентификатор таймзоны: {timezone!r}"
        ) from exc


@dataclass(frozen=True, slots=True)
class Specialist:
    """Неизменяемая запись психолога.

    ``id`` неизменен после создания. ``slot_duration_minutes`` и ``timezone``
    редактируемы на уровне специалиста (через сервисный слой), но валидны в
    любом валидном экземпляре модели.
    """

    id: str
    name: str
    slot_duration_minutes: int
    timezone: str

    def __post_init__(self) -> None:
        validate_duration(self.slot_duration_minutes)
        validate_timezone(self.timezone)
