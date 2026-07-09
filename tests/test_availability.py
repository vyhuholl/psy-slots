from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.domain.availability import AvailabilityInterval, ValidationError


def test_interval_created_with_valid_fields() -> None:
    interval = AvailabilityInterval(
        id="int-1",
        specialist_id="spec-1",
        weekday=1,
        start_minute=600,
        end_minute=840,
    )

    assert interval.id == "int-1"
    assert interval.specialist_id == "spec-1"
    assert interval.weekday == 1
    assert interval.start_minute == 600
    assert interval.end_minute == 840


def test_interval_is_immutable() -> None:
    interval = AvailabilityInterval(
        id="int-1",
        specialist_id="spec-1",
        weekday=1,
        start_minute=600,
        end_minute=840,
    )

    # setattr обходит статическую проверку; frozen роняет во время выполнения.
    with pytest.raises(FrozenInstanceError):
        setattr(interval, "start_minute", 0)


@pytest.mark.parametrize("bad_weekday", [-1, 7, 8, 100])
def test_weekday_out_of_range_rejected(bad_weekday: int) -> None:
    with pytest.raises(ValidationError):
        AvailabilityInterval(
            id="int-1",
            specialist_id="spec-1",
            weekday=bad_weekday,
            start_minute=600,
            end_minute=840,
        )


@pytest.mark.parametrize("weekday", [0, 6])
def test_weekday_bounds_accepted(weekday: int) -> None:
    interval = AvailabilityInterval(
        id="int-1",
        specialist_id="spec-1",
        weekday=weekday,
        start_minute=600,
        end_minute=840,
    )

    assert interval.weekday == weekday


@pytest.mark.parametrize(
    ("start_minute", "end_minute"),
    [
        (-1, 840),  # начало вне суток
        (600, 1441),  # конец вне суток
        (840, 600),  # начало > конца
        (600, 600),  # начало == конца
    ],
)
def test_out_of_day_or_start_not_before_end_rejected(
    start_minute: int, end_minute: int
) -> None:
    with pytest.raises(ValidationError):
        AvailabilityInterval(
            id="int-1",
            specialist_id="spec-1",
            weekday=1,
            start_minute=start_minute,
            end_minute=end_minute,
        )


@pytest.mark.parametrize(
    ("start_minute", "end_minute"),
    [(0, 1440), (0, 1), (1439, 1440)],
)
def test_day_bounds_accepted(start_minute: int, end_minute: int) -> None:
    interval = AvailabilityInterval(
        id="int-1",
        specialist_id="spec-1",
        weekday=1,
        start_minute=start_minute,
        end_minute=end_minute,
    )

    assert interval.start_minute == start_minute
    assert interval.end_minute == end_minute
