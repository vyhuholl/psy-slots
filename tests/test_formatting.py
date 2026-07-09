from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.bot.formatting import format_slot_range, format_time

_MOSCOW = ZoneInfo("Europe/Moscow")  # UTC+3


def test_format_time_converts_utc_to_client_tz() -> None:
    # 07:00 UTC → 10:00 в Москве.
    assert format_time(datetime(2026, 7, 9, 7, 0, tzinfo=UTC), _MOSCOW) == (
        "10:00"
    )


def test_format_slot_range_converts_both_bounds() -> None:
    start = datetime(2026, 7, 9, 7, 0, tzinfo=UTC)
    end = datetime(2026, 7, 9, 7, 20, tzinfo=UTC)

    assert format_slot_range(start, end, _MOSCOW) == "10:00–10:20"


def test_format_time_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError):
        format_time(datetime(2026, 7, 9, 7, 0), _MOSCOW)


def test_format_slot_range_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError):
        format_slot_range(
            datetime(2026, 7, 9, 7, 0),
            datetime(2026, 7, 9, 7, 20),
            _MOSCOW,
        )
