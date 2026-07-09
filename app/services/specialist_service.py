"""Доменный сервис реестра специалистов над пулом YDB.

Единственный вход к строкам специалистов: регистрация, список, получение по
id, изменение длительности и таймзоны. Хендлеры Telegram обращаются только
сюда — прямого доступа к строкам инлайн быть не должно. Низкоуровневые
ошибки YDB не протекают наружу: отсутствие выражается явно (``get`` → None,
мутации несуществующего id → :class:`SpecialistNotFound`).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import ydb

from app.domain.specialist import (
    Specialist,
    SpecialistNotFound,
    validate_duration,
    validate_timezone,
)
from app.ydb_client import get_pool

_UPSERT = """\
UPSERT INTO specialists
    (id, name, slot_duration_minutes, timezone, created_at)
VALUES
    ($id, $name, $slot_duration_minutes, $timezone, $created_at);
"""

_SELECT_ALL = """\
SELECT id, name, slot_duration_minutes, timezone FROM specialists;
"""

_SELECT_BY_ID = """\
SELECT id, name, slot_duration_minutes, timezone
FROM specialists
WHERE id = $id;
"""

_UPDATE_DURATION = """\
UPDATE specialists SET slot_duration_minutes = $slot_duration_minutes
WHERE id = $id;
"""

_UPDATE_TIMEZONE = """\
UPDATE specialists SET timezone = $timezone WHERE id = $id;
"""


def _row_to_specialist(row: Mapping[str, Any]) -> Specialist:
    return Specialist(
        id=str(row["id"]),
        name=str(row["name"]),
        slot_duration_minutes=int(row["slot_duration_minutes"]),
        timezone=str(row["timezone"]),
    )


class SpecialistService:
    """Единый слой доступа к записям специалистов в YDB."""

    def __init__(self, pool: ydb.QuerySessionPool | None = None) -> None:
        self._pool = pool if pool is not None else get_pool()

    def register(
        self, *, name: str, slot_duration_minutes: int, timezone: str
    ) -> Specialist:
        """Создать специалиста с новым UUID; вернуть сохранённую модель."""
        specialist = Specialist(
            id=str(uuid.uuid4()),
            name=name,
            slot_duration_minutes=slot_duration_minutes,
            timezone=timezone,
        )
        self._pool.execute_with_retries(
            _UPSERT,
            {
                "$id": (specialist.id, ydb.PrimitiveType.Utf8),
                "$name": (specialist.name, ydb.PrimitiveType.Utf8),
                "$slot_duration_minutes": (
                    specialist.slot_duration_minutes,
                    ydb.PrimitiveType.Uint32,
                ),
                "$timezone": (specialist.timezone, ydb.PrimitiveType.Utf8),
                "$created_at": (
                    datetime.now(tz=UTC),
                    ydb.PrimitiveType.Timestamp,
                ),
            },
        )
        return specialist

    def list(self) -> list[Specialist]:
        """Вернуть всех специалистов; пустой список при пустом реестре."""
        result_sets = self._pool.execute_with_retries(_SELECT_ALL)
        return [
            _row_to_specialist(row)
            for result_set in result_sets
            for row in result_set.rows
        ]

    def get(self, specialist_id: str) -> Specialist | None:
        """Вернуть специалиста по id или None, если его нет."""
        result_sets = self._pool.execute_with_retries(
            _SELECT_BY_ID,
            {"$id": (specialist_id, ydb.PrimitiveType.Utf8)},
        )
        for result_set in result_sets:
            for row in result_set.rows:
                return _row_to_specialist(row)
        return None

    def update_duration(
        self, specialist_id: str, slot_duration_minutes: int
    ) -> Specialist:
        """Изменить длительность существующего специалиста."""
        validate_duration(slot_duration_minutes)
        current = self._require(specialist_id)
        self._pool.execute_with_retries(
            _UPDATE_DURATION,
            {
                "$id": (specialist_id, ydb.PrimitiveType.Utf8),
                "$slot_duration_minutes": (
                    slot_duration_minutes,
                    ydb.PrimitiveType.Uint32,
                ),
            },
        )
        return Specialist(
            id=current.id,
            name=current.name,
            slot_duration_minutes=slot_duration_minutes,
            timezone=current.timezone,
        )

    def update_timezone(self, specialist_id: str, timezone: str) -> Specialist:
        """Изменить таймзону существующего специалиста."""
        validate_timezone(timezone)
        current = self._require(specialist_id)
        self._pool.execute_with_retries(
            _UPDATE_TIMEZONE,
            {
                "$id": (specialist_id, ydb.PrimitiveType.Utf8),
                "$timezone": (timezone, ydb.PrimitiveType.Utf8),
            },
        )
        return Specialist(
            id=current.id,
            name=current.name,
            slot_duration_minutes=current.slot_duration_minutes,
            timezone=timezone,
        )

    def _require(self, specialist_id: str) -> Specialist:
        current = self.get(specialist_id)
        if current is None:
            raise SpecialistNotFound(specialist_id)
        return current
