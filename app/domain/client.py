"""Доменная модель профиля клиента и её ошибки.

Минимальный профиль: идентификатор пользователя Telegram и его таймзона как
корректный IANA-идентификатор. Больше ничего (имя/контакты/история) — только
то, что нужно для показа времени в таймзоне клиента. Здесь нет ни YDB, ни
Telegram — только чистый домен с валидацией таймзоны через ``zoneinfo``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ClientError(RuntimeError):
    """Базовая доменная ошибка профиля клиента."""


class InvalidTimezone(ClientError):
    """Строка таймзоны не является корректным IANA-идентификатором."""


def ensure_valid_timezone(timezone: str) -> ZoneInfo:
    """Вернуть ``ZoneInfo`` или бросить :class:`InvalidTimezone`."""
    if not timezone:
        raise InvalidTimezone("Timezone must be a non-empty IANA identifier")
    try:
        return ZoneInfo(timezone)
    except ZoneInfoNotFoundError, ValueError:
        raise InvalidTimezone(f"Invalid IANA timezone: {timezone!r}") from None


@dataclass(frozen=True, slots=True)
class Client:
    """Неизменяемый профиль клиента с провалидированной IANA-таймзоной."""

    telegram_id: int
    timezone: str
    created_at: datetime

    def __post_init__(self) -> None:
        ensure_valid_timezone(self.timezone)

    @property
    def zoneinfo(self) -> ZoneInfo:
        """Таймзона клиента как ``ZoneInfo`` (для форматирования времени)."""
        return ZoneInfo(self.timezone)
