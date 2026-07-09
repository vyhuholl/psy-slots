from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.domain.specialist import Specialist, ValidationError


def test_specialist_created_with_valid_fields() -> None:
    specialist = Specialist(
        id="id-1",
        name="Анна",
        slot_duration_minutes=15,
        timezone="Europe/Moscow",
    )

    assert specialist.id == "id-1"
    assert specialist.name == "Анна"
    assert specialist.slot_duration_minutes == 15
    assert specialist.timezone == "Europe/Moscow"


def test_specialist_is_immutable() -> None:
    specialist = Specialist(
        id="id-1",
        name="Анна",
        slot_duration_minutes=15,
        timezone="Europe/Moscow",
    )

    # setattr обходит статическую проверку; frozen роняет во время выполнения.
    with pytest.raises(FrozenInstanceError):
        setattr(specialist, "name", "Другая")


@pytest.mark.parametrize("bad_duration", [0, -1, -15])
def test_non_positive_duration_rejected(bad_duration: int) -> None:
    with pytest.raises(ValidationError):
        Specialist(
            id="id-1",
            name="Анна",
            slot_duration_minutes=bad_duration,
            timezone="Europe/Moscow",
        )


@pytest.mark.parametrize(
    "bad_timezone", ["Not/AZone", "", "Europe/Nowhere", "12:00", "../etc"]
)
def test_invalid_timezone_rejected(bad_timezone: str) -> None:
    with pytest.raises(ValidationError):
        Specialist(
            id="id-1",
            name="Анна",
            slot_duration_minutes=15,
            timezone=bad_timezone,
        )
