"""Форматирование моментов UTC в строки в таймзоне клиента.

Единственное место перевода UTC→локаль для показа: слоты, подтверждения и
списки броней. Вход обязан быть timezone-aware (моменты хранятся в UTC);
naive-время отклоняется, чтобы не показать клиенту неоднозначное время.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

_EN_DASH = "–"


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware (UTC)")


def format_time(dt_utc: datetime, tz: ZoneInfo) -> str:
    """Вернуть ``HH:MM`` момента ``dt_utc`` в таймзоне ``tz``."""
    _require_aware(dt_utc)
    return dt_utc.astimezone(tz).strftime("%H:%M")


def format_slot_range(
    start_utc: datetime, end_utc: datetime, tz: ZoneInfo
) -> str:
    """Вернуть ``HH:MM–HH:MM`` границ слота в таймзоне ``tz``."""
    return f"{format_time(start_utc, tz)}{_EN_DASH}{format_time(end_utc, tz)}"
