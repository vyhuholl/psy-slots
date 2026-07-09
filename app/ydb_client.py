"""Тёплый модульный клиент YDB.

Драйвер и пул сессий создаются один раз (лениво, при первом обращении) и
переиспользуются тёплым инстансом функции между вызовами. Готовность
драйвера дожидается лениво; вручную клиент не закрывается. Конфигурация
подключения берётся из окружения через :mod:`app.config`.
"""

from __future__ import annotations

import ydb

from app.config import Config, load_config

_WAIT_TIMEOUT_SECONDS = 10

_driver: ydb.Driver | None = None
_pool: ydb.QuerySessionPool | None = None
_ready = False


def _build_driver(config: Config) -> ydb.Driver:
    driver_config = ydb.DriverConfig(
        endpoint=config.ydb_endpoint,
        database=config.ydb_database,
        credentials=ydb.credentials_from_env_variables(),
    )
    return ydb.Driver(driver_config)


def get_driver() -> ydb.Driver:
    """Вернуть тёплый драйвер, дождавшись готовности при первом вызове."""
    global _driver, _ready
    if _driver is None:
        _driver = _build_driver(load_config())
    if not _ready:
        _driver.wait(timeout=_WAIT_TIMEOUT_SECONDS)
        _ready = True
    return _driver


def get_pool() -> ydb.QuerySessionPool:
    """Вернуть тёплый пул сессий поверх драйвера."""
    global _pool
    if _pool is None:
        _pool = ydb.QuerySessionPool(get_driver())
    return _pool
