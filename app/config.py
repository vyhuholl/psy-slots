"""Типизированная загрузка конфигурации из переменных окружения.

Секреты (токен бота, webhook-секрет, параметры YDB) читаются только из
окружения функции и никогда не хардкодятся. Отсутствие обязательной
переменной — явная ошибка на этапе инициализации.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    """Обязательная переменная окружения отсутствует или пуста."""


@dataclass(frozen=True)
class Config:
    """Разобранная конфигурация приложения."""

    bot_token: str
    webhook_secret: str
    ydb_endpoint: str
    ydb_database: str


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def load_config() -> Config:
    """Прочитать и провалидировать конфигурацию из окружения."""
    return Config(
        bot_token=_require("BOT_TOKEN"),
        webhook_secret=_require("WEBHOOK_SECRET"),
        ydb_endpoint=_require("YDB_ENDPOINT"),
        ydb_database=_require("YDB_DATABASE"),
    )
