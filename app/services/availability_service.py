"""Доменный сервис недельного расписания над пулом YDB.

Единственный вход к интервалам доступности: добавление, удаление, список
интервалов специалиста. Хендлеры Telegram обращаются только сюда. Сервис
проверяет существование специалиста (через лукап реестра), запрещает
пересечения интервалов в один день недели и генерирует неизменный UUID для
каждого интервала. Модель формы валидирует :class:`AvailabilityInterval`;
проверка пересечений и persistence — здесь.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, Protocol

import ydb

from app.domain.availability import AvailabilityInterval, IntervalOverlap
from app.domain.specialist import Specialist, SpecialistNotFound
from app.services.specialist_service import SpecialistService
from app.ydb_client import get_pool

_UPSERT = """\
UPSERT INTO availability_intervals
    (id, specialist_id, weekday, start_minute, end_minute)
VALUES
    ($id, $specialist_id, $weekday, $start_minute, $end_minute);
"""

_SELECT_BY_SPECIALIST = """\
SELECT id, specialist_id, weekday, start_minute, end_minute
FROM availability_intervals
WHERE specialist_id = $specialist_id;
"""

_DELETE_BY_ID = """\
DELETE FROM availability_intervals WHERE id = $id;
"""


class SpecialistLookup(Protocol):
    """Минимальный лукап реестра специалистов, нужный сервису доступности."""

    def get(self, specialist_id: str) -> Specialist | None: ...


def _row_to_interval(row: Mapping[str, Any]) -> AvailabilityInterval:
    return AvailabilityInterval(
        id=str(row["id"]),
        specialist_id=str(row["specialist_id"]),
        weekday=int(row["weekday"]),
        start_minute=int(row["start_minute"]),
        end_minute=int(row["end_minute"]),
    )


def _overlaps(a: AvailabilityInterval, b: AvailabilityInterval) -> bool:
    """Пересечение полуоткрытых диапазонов ``[start, end)``.

    Смежные интервалы (``end == start``) не считаются пересечением.
    """
    return a.start_minute < b.end_minute and b.start_minute < a.end_minute


class AvailabilityService:
    """Единый слой доступа к интервалам расписания в YDB."""

    def __init__(
        self,
        pool: ydb.QuerySessionPool | None = None,
        specialists: SpecialistLookup | None = None,
    ) -> None:
        self._pool = pool if pool is not None else get_pool()
        self._specialists: SpecialistLookup = (
            specialists
            if specialists is not None
            else SpecialistService(pool=self._pool)
        )

    def add_interval(
        self,
        *,
        specialist_id: str,
        weekday: int,
        start_minute: int,
        end_minute: int,
    ) -> AvailabilityInterval:
        """Добавить интервал существующему специалисту без пересечений.

        Валидирует форму (модель), существование специалиста и отсутствие
        пересечений в тот же день недели; при нарушении — доменная ошибка, в
        YDB ничего не пишется.
        """
        interval = AvailabilityInterval(
            id=str(uuid.uuid4()),
            specialist_id=specialist_id,
            weekday=weekday,
            start_minute=start_minute,
            end_minute=end_minute,
        )
        if self._specialists.get(specialist_id) is None:
            raise SpecialistNotFound(specialist_id)
        for existing in self.list(specialist_id):
            if existing.weekday == weekday and _overlaps(existing, interval):
                raise IntervalOverlap(
                    "Интервал пересекается с существующим в тот же день "
                    f"недели: {existing.id}"
                )
        self._pool.execute_with_retries(
            _UPSERT,
            {
                "$id": (interval.id, ydb.PrimitiveType.Utf8),
                "$specialist_id": (
                    interval.specialist_id,
                    ydb.PrimitiveType.Utf8,
                ),
                "$weekday": (interval.weekday, ydb.PrimitiveType.Uint8),
                "$start_minute": (
                    interval.start_minute,
                    ydb.PrimitiveType.Uint16,
                ),
                "$end_minute": (
                    interval.end_minute,
                    ydb.PrimitiveType.Uint16,
                ),
            },
        )
        return interval

    def remove_interval(self, interval_id: str) -> None:
        """Удалить интервал по идентификатору (реальное удаление строки)."""
        self._pool.execute_with_retries(
            _DELETE_BY_ID,
            {"$id": (interval_id, ydb.PrimitiveType.Utf8)},
        )

    def list(self, specialist_id: str) -> list[AvailabilityInterval]:
        """Вернуть интервалы специалиста; пустой список при их отсутствии."""
        result_sets = self._pool.execute_with_retries(
            _SELECT_BY_SPECIALIST,
            {"$specialist_id": (specialist_id, ydb.PrimitiveType.Utf8)},
        )
        return [
            _row_to_interval(row)
            for result_set in result_sets
            for row in result_set.rows
        ]
