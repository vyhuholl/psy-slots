from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import ydb

import app.ydb_client as ydb_client
from app.config import ConfigError
from tests.conftest import TEST_YDB_DATABASE, TEST_YDB_ENDPOINT


@pytest.fixture(autouse=True)
def _reset_client() -> None:
    """Сбросить модульные синглтоны между тестами."""
    ydb_client._driver = None
    ydb_client._pool = None
    ydb_client._ready = False


@pytest.fixture
def fake_ydb(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Замокать конструкторы драйвера/пула YDB."""
    driver = MagicMock(name="Driver")
    pool = MagicMock(name="QuerySessionPool")
    driver_ctor = MagicMock(return_value=driver)
    pool_ctor = MagicMock(return_value=pool)
    config_ctor = MagicMock(name="DriverConfig")
    creds = MagicMock(name="credentials")

    monkeypatch.setattr(ydb, "Driver", driver_ctor)
    monkeypatch.setattr(ydb, "QuerySessionPool", pool_ctor)
    monkeypatch.setattr(ydb, "DriverConfig", config_ctor)
    monkeypatch.setattr(ydb, "credentials_from_env_variables", creds)

    holder = MagicMock()
    holder.driver = driver
    holder.pool = pool
    holder.driver_ctor = driver_ctor
    holder.pool_ctor = pool_ctor
    holder.config_ctor = config_ctor
    return holder


def test_driver_initialized_once_and_reused(
    env: None, fake_ydb: MagicMock
) -> None:
    first = ydb_client.get_driver()
    second = ydb_client.get_driver()

    assert first is second is fake_ydb.driver
    # Драйвер сконструирован ровно один раз (тёплый инстанс).
    assert fake_ydb.driver_ctor.call_count == 1
    # Готовность дожидается лениво.
    fake_ydb.driver.wait.assert_called()


def test_pool_reused_and_built_on_driver(
    env: None, fake_ydb: MagicMock
) -> None:
    first = ydb_client.get_pool()
    second = ydb_client.get_pool()

    assert first is second is fake_ydb.pool
    assert fake_ydb.pool_ctor.call_count == 1
    fake_ydb.pool_ctor.assert_called_once_with(fake_ydb.driver)


def test_connection_config_from_env_not_constants(
    env: None, fake_ydb: MagicMock
) -> None:
    ydb_client.get_driver()

    _, kwargs = fake_ydb.config_ctor.call_args
    assert kwargs["endpoint"] == TEST_YDB_ENDPOINT
    assert kwargs["database"] == TEST_YDB_DATABASE


def test_missing_ydb_variable_raises_config_error(
    env: None, monkeypatch: pytest.MonkeyPatch, fake_ydb: MagicMock
) -> None:
    monkeypatch.delenv("YDB_ENDPOINT", raising=False)

    with pytest.raises(ConfigError):
        ydb_client.get_driver()

    # Драйвер не строился при ошибке конфигурации.
    fake_ydb.driver_ctor.assert_not_called()
