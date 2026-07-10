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
from dotenv import load_dotenv

from app.ydb_client import get_pool

load_dotenv()  # для локального запуска миграций из .env

# Бронь — самостоятельная строка с неизменным UUID и явными start/end в UTC
# (а не «слот занят»). Ссылки на специалиста нет — психолог один. Вторичный
# индекс по start_utc ускоряет проверку пересечений и списки в диапазоне.
# Денормализованный end_utc фиксируется при создании, чтобы изменение
# длительности слота (env) не сдвигало существующие брони.
_CREATE_BOOKINGS = """
CREATE TABLE IF NOT EXISTS bookings (
    id Utf8,
    client_id Int64,
    start_utc Timestamp,
    end_utc Timestamp,
    status Utf8,
    created_at Timestamp,
    cancelled_at Timestamp,
    INDEX idx_bookings_start GLOBAL ON (start_utc),
    PRIMARY KEY (id)
);
"""

# Маркеры отправленных напоминаний: booking_id (PK) гарантирует уникальность,
# sent_at фиксирует момент отправки. Таблица обеспечивает идемпотентность —
# одно напоминание на бронь, даже при повторных/перекрывающихся тиках.
_CREATE_SENT_REMINDERS = """
CREATE TABLE IF NOT EXISTS sent_reminders (
    booking_id Utf8,
    sent_at Timestamp,
    PRIMARY KEY (booking_id)
);
"""

# Идемпотентные DDL-инструкции. Психолог один, а длительность и интервалы
# доступности берутся из окружения (см. bot-config), поэтому таблиц
# специалистов и недельного расписания в схеме нет. Профиля клиента тоже нет:
# таймзона фиксирована (Europe/Moscow), имена берутся из Telegram на лету —
# таблица clients не создаётся. Прикладные таблицы добавляют свои DDL сюда.
MIGRATIONS: tuple[str, ...] = (
    _CREATE_BOOKINGS,
    _CREATE_SENT_REMINDERS,
)


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
