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


def test_specialists_table_created_idempotently() -> None:
    pool = MagicMock(name="pool")

    run_migrations(pool=pool, statements=MIGRATIONS)

    executed = [
        call.args[0] for call in pool.execute_with_retries.call_args_list
    ]
    assert any(
        "CREATE TABLE IF NOT EXISTS specialists" in stmt for stmt in executed
    )
    # Все DDL идемпотентны — повторный прогон не роняет и не дублирует.
    assert all("IF NOT EXISTS" in stmt for stmt in executed)

    run_migrations(pool=pool, statements=MIGRATIONS)
    assert pool.execute_with_retries.call_count == 2 * len(MIGRATIONS)


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
