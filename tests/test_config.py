from __future__ import annotations

import pytest

from app.config import Config, ConfigError, load_config
from tests.conftest import (
    TEST_BOT_TOKEN,
    TEST_WEBHOOK_SECRET,
    TEST_YDB_DATABASE,
    TEST_YDB_ENDPOINT,
)


def test_load_config_reads_all_variables(env: None) -> None:
    config = load_config()

    assert isinstance(config, Config)
    assert config.bot_token == TEST_BOT_TOKEN
    assert config.webhook_secret == TEST_WEBHOOK_SECRET
    assert config.ydb_endpoint == TEST_YDB_ENDPOINT
    assert config.ydb_database == TEST_YDB_DATABASE


@pytest.mark.parametrize(
    "missing",
    ["BOT_TOKEN", "WEBHOOK_SECRET", "YDB_ENDPOINT", "YDB_DATABASE"],
)
def test_load_config_missing_variable_raises(
    env: None, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    monkeypatch.delenv(missing, raising=False)

    with pytest.raises(ConfigError) as excinfo:
        load_config()

    assert missing in str(excinfo.value)


def test_load_config_empty_variable_raises(
    env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BOT_TOKEN", "")

    with pytest.raises(ConfigError):
        load_config()
