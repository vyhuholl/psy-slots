"""Доменная модель интервала недельного расписания и её ошибки.

Неизменяемый типизированный интервал доступности специалиста: день недели
(Monday=0 … Sunday=6) и время начала/конца в **минутах от полуночи** —
локальное настенное время в таймзоне специалиста, НЕ UTC (расписание
повторяется еженедельно, перевод в конкретные UTC-моменты — забота генерации
слотов). Валидация формы выполняется при создании модели. Модель не знает про
YDB и Telegram — доступ к хранилищу и проверка пересечений лежат в сервисе.
"""

from __future__ import annotations

from dataclasses import dataclass

# Границы дня в минутах: [0, 1440]. 1440 == 24:00 — допустимый конец интервала.
_MINUTES_PER_DAY = 24 * 60


class ValidationError(Exception):
    """Данные интервала не прошли доменную валидацию."""


class IntervalOverlap(Exception):
    """Интервал пересекается с существующим в тот же день недели."""


def validate_weekday(weekday: int) -> None:
    """День недели обязан лежать в диапазоне 0..6 (Monday=0 … Sunday=6)."""
    if not 0 <= weekday <= 6:
        raise ValidationError(
            f"День недели должен быть в диапазоне 0..6, получено: {weekday}"
        )


def validate_bounds(start_minute: int, end_minute: int) -> None:
    """Границы в пределах суток [0, 1440] и начало строго меньше конца."""
    for label, value in (("начала", start_minute), ("конца", end_minute)):
        if not 0 <= value <= _MINUTES_PER_DAY:
            raise ValidationError(
                f"Минута {label} должна быть в диапазоне 0..{_MINUTES_PER_DAY}"
                f", получено: {value}"
            )
    if start_minute >= end_minute:
        raise ValidationError(
            "Начало интервала должно быть строго раньше конца, получено: "
            f"{start_minute} >= {end_minute}"
        )


@dataclass(frozen=True, slots=True)
class AvailabilityInterval:
    """Неизменяемый интервал недельного расписания.

    ``id`` неизменен после создания. ``weekday`` и границы задают повторяющееся
    окно в локальном времени специалиста; любой валидный экземпляр модели
    удовлетворяет доменным инвариантам формы интервала.
    """

    id: str
    specialist_id: str
    weekday: int
    start_minute: int
    end_minute: int

    def __post_init__(self) -> None:
        validate_weekday(self.weekday)
        validate_bounds(self.start_minute, self.end_minute)
