"""Идемпотентный раннер миграций схемы YDB.

Запускается явно как отдельная операция (локально или деплойным шагом) и
никогда не на горячем пути обработки вебхука. DDL-инструкции пишутся как
``CREATE TABLE IF NOT EXISTS``, поэтому повторный запуск безопасен.

Прикладных таблиц здесь пока нет — доменные changes добавляют свои DDL в
:data:`MIGRATIONS`, чтобы схема жила рядом со своей capability.
"""

from __future__ import annotations

from collections.abc import Sequence

import ydb

from app.ydb_client import get_pool

# Таблица специалистов: неизменный UUID-строка (PK), имя, редактируемые
# длительность слота (минуты) и таймзона (IANA-имя), метка создания.
_SPECIALISTS_DDL = """\
CREATE TABLE IF NOT EXISTS specialists (
    id Utf8,
    name Utf8,
    slot_duration_minutes Uint32,
    timezone Utf8,
    created_at Timestamp,
    PRIMARY KEY (id)
);
"""

# Интервалы недельного расписания: неизменный UUID-строка (PK), ссылка на
# специалиста, день недели (Monday=0 … Sunday=6) и границы в минутах от
# полуночи — локальное настенное время специалиста, НЕ UTC.
_AVAILABILITY_INTERVALS_DDL = """\
CREATE TABLE IF NOT EXISTS availability_intervals (
    id Utf8,
    specialist_id Utf8,
    weekday Uint8,
    start_minute Uint16,
    end_minute Uint16,
    PRIMARY KEY (id)
);
"""

# Идемпотентные DDL-инструкции. Каждая capability добавляет свои таблицы сюда.
MIGRATIONS: tuple[str, ...] = (_SPECIALISTS_DDL, _AVAILABILITY_INTERVALS_DDL)


def run_migrations(
    pool: ydb.QuerySessionPool | None = None,
    statements: Sequence[str] = MIGRATIONS,
) -> None:
    """Применить все DDL-инструкции. Идемпотентно; вне хендлера вебхука."""
    target = pool if pool is not None else get_pool()
    for statement in statements:
        target.execute_with_retries(statement)


def main() -> None:  # pragma: no cover
    """Точка входа для явного запуска миграций."""
    run_migrations()


if __name__ == "__main__":  # pragma: no cover
    main()
