"""Доменный сервис профиля клиента над YDB.

Чтение и установка таймзоны клиента проходят через этот слой, а не инлайн в
aiogram-хендлерах. Таймзона валидируется как IANA-идентификатор до записи;
``created_at`` фиксируется при первом контакте и переживает смену таймзоны
(денормализация не нужна — профиль минимален). Время везде в UTC.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import ydb

from app.domain.client import Client, ensure_valid_timezone

_COLUMNS = "telegram_id, timezone, created_at"

_SELECT_BY_ID = f"""
DECLARE $telegram_id AS Int64;
SELECT {_COLUMNS} FROM clients WHERE telegram_id = $telegram_id;
"""

_UPSERT_CLIENT = """
DECLARE $telegram_id AS Int64;
DECLARE $timezone AS Utf8;
DECLARE $created_at AS Timestamp;
UPSERT INTO clients (telegram_id, timezone, created_at)
VALUES ($telegram_id, $timezone, $created_at);
"""


def _int64(value: int) -> Any:
    return ydb.TypedValue(value, ydb.PrimitiveType.Int64)


def _utf8(value: str) -> Any:
    return ydb.TypedValue(value, ydb.PrimitiveType.Utf8)


def _ts(value: datetime) -> Any:
    return ydb.TypedValue(value, ydb.PrimitiveType.Timestamp)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _collect_rows(result_sets: Any) -> list[Any]:
    rows: list[Any] = []
    for result_set in result_sets:
        rows.extend(result_set.rows)
    return rows


def _row_to_client(row: Any) -> Client:
    return Client(
        telegram_id=row["telegram_id"],
        timezone=row["timezone"],
        created_at=_as_utc(row["created_at"]),
    )


class ClientService:
    """Чтение и установка таймзоны клиента над пулом сессий YDB."""

    def __init__(self, pool: ydb.QuerySessionPool) -> None:
        self._pool = pool

    def get(self, telegram_id: int) -> Client | None:
        """Вернуть профиль клиента по ``telegram_id`` или ``None``."""
        rows = _collect_rows(
            self._pool.execute_with_retries(
                _SELECT_BY_ID, {"$telegram_id": _int64(telegram_id)}
            )
        )
        if not rows:
            return None
        return _row_to_client(rows[0])

    def set_timezone(
        self, telegram_id: int, timezone: str, *, now: datetime | None = None
    ) -> Client:
        """Установить клиенту IANA-таймзону, сохранив ``created_at``.

        Невалидная таймзона → :class:`InvalidTimezone`, профиль не меняется.
        ``created_at`` берётся из существующего профиля, иначе — ``now``.
        """
        ensure_valid_timezone(timezone)
        now_utc = datetime.now(UTC) if now is None else _as_utc(now)

        def _upsert(tx: Any) -> Client:
            existing = _collect_rows(
                tx.execute(
                    _SELECT_BY_ID, {"$telegram_id": _int64(telegram_id)}
                )
            )
            created_at = (
                _as_utc(existing[0]["created_at"]) if existing else now_utc
            )
            tx.execute(
                _UPSERT_CLIENT,
                {
                    "$telegram_id": _int64(telegram_id),
                    "$timezone": _utf8(timezone),
                    "$created_at": _ts(created_at),
                },
            )
            return Client(
                telegram_id=telegram_id,
                timezone=timezone,
                created_at=created_at,
            )

        result: Client = self._pool.retry_tx_sync(
            _upsert, tx_mode=ydb.QuerySerializableReadWrite()
        )
        return result
