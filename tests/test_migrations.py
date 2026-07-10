from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

import app.handler as handler_module
import app.migrations as migrations
from app.migrations import MIGRATIONS, run_migrations
from tests.conftest import TEST_WEBHOOK_SECRET
from tests.test_handler import _event, _start_update

DDL = ("CREATE TABLE IF NOT EXISTS demo (id Uint64, PRIMARY KEY (id));",)


def test_run_migrations_executes_each_statement() -> None:
    pool = MagicMock(name="pool")

    run_migrations(pool=pool, statements=DDL)

    pool.execute_with_retries.assert_called_once_with(DDL[0])


def test_run_migrations_is_idempotent_on_repeat() -> None:
    pool = MagicMock(name="pool")

    run_migrations(pool=pool, statements=DDL)
    run_migrations(pool=pool, statements=DDL)

    # Повторный запуск безопасен: те же идемпотентные DDL, без ошибок.
    assert pool.execute_with_retries.call_count == 2


def test_run_migrations_uses_warm_pool_when_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = MagicMock(name="warm-pool")
    monkeypatch.setattr(migrations, "get_pool", lambda: pool)

    run_migrations(statements=DDL)

    pool.execute_with_retries.assert_called_once_with(DDL[0])


def test_all_migrations_are_idempotent() -> None:
    # Каждая зарегистрированная capability добавляет только идемпотентный DDL.
    assert all("IF NOT EXISTS" in stmt for stmt in MIGRATIONS)


def test_bookings_table_and_index_are_migrated() -> None:
    joined = "\n".join(MIGRATIONS)
    # Таблица bookings с явными start/end в UTC и вторичным индексом
    # по start_utc для проверки пересечений и списков в диапазоне.
    assert "bookings" in joined
    assert "start_utc" in joined
    assert "end_utc" in joined
    assert "INDEX" in joined
    assert "start_utc" in joined
    # Идемпотентность: повторный прогон миграций безопасен.
    assert all("IF NOT EXISTS" in stmt for stmt in MIGRATIONS)


def test_run_migrations_creates_bookings_idempotently() -> None:
    pool = MagicMock(name="pool")

    run_migrations(pool=pool)
    run_migrations(pool=pool)

    executed = [
        call.args[0] for call in pool.execute_with_retries.call_args_list
    ]
    assert any("bookings" in stmt and "start_utc" in stmt for stmt in executed)
    # Каждый прогон применяет тот же идемпотентный DDL.
    assert len(executed) == 2 * len(MIGRATIONS)


def test_clients_table_is_not_migrated() -> None:
    # Профиля клиента больше нет: таймзона фиксирована (Europe/Moscow),
    # имена берутся из Telegram на лету — таблица clients не создаётся.
    joined = "\n".join(MIGRATIONS)
    assert "CREATE TABLE IF NOT EXISTS clients" not in joined


def test_obsolete_tables_are_not_migrated() -> None:
    # Психолог один, интервалы — из окружения: таблиц специалистов и
    # недельного расписания больше нет в схеме. Профиля клиента тоже нет.
    joined = "\n".join(MIGRATIONS)
    assert "specialists" not in joined
    assert "availability_intervals" not in joined
    assert "CREATE TABLE IF NOT EXISTS clients" not in joined


def test_migration_not_invoked_on_webhook_path(
    env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_spy = MagicMock(name="run_migrations")
    monkeypatch.setattr(migrations, "run_migrations", run_spy)
    # Диспетчер замокан, чтобы не уходить в сеть Telegram.
    dispatcher = MagicMock(name="Dispatcher")

    async def _noop(*args: object, **kwargs: object) -> None:
        return None

    dispatcher.feed_update = _noop
    monkeypatch.setattr(handler_module, "_dispatcher", dispatcher)
    monkeypatch.setattr(handler_module, "_bot", object())

    event = _event(json.dumps(_start_update()), secret=TEST_WEBHOOK_SECRET)
    response = handler_module.handler(event, None)

    assert response["statusCode"] == 200
    run_spy.assert_not_called()


def test_sent_reminders_table_is_migrated() -> None:
    joined = "\n".join(MIGRATIONS)
    # Таблица sent_reminders: PK booking_id, sent_at для идемпотентности.
    assert "sent_reminders" in joined
    assert "booking_id" in joined
    assert "sent_at" in joined
    # Идемпотентность: повторный прогон миграций безопасен.
    assert all("IF NOT EXISTS" in stmt for stmt in MIGRATIONS)


def test_run_migrations_creates_sent_reminders_idempotently() -> None:
    pool = MagicMock(name="pool")

    run_migrations(pool=pool)
    run_migrations(pool=pool)

    executed = [
        call.args[0] for call in pool.execute_with_retries.call_args_list
    ]
    assert any(
        "sent_reminders" in stmt and "booking_id" in stmt for stmt in executed
    )
    # Каждый прогон применяет тот же идемпотентный DDL.
    assert len(executed) == 2 * len(MIGRATIONS)
