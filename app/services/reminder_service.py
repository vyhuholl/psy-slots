"""Сервис напоминаний за 5 минут до начала брони.

Отдельная функция по timer-триггеру YC, шлющая клиенту одно напоминание
за фиксированные 5 минут до начала активной брони — идемпотентная
(персистентный маркер по booking_id), с показом времени в Europe/Moscow.
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timedelta, timezone
from logging import getLogger
from typing import Any
from zoneinfo import ZoneInfo

import ydb
from aiogram import Bot

from app.bot.formatting import format_slot_range
from app.bot.naming import resolve_client_name
from app.services.booking_service import BookingService

logger = getLogger(__name__)

# Фиксированный лид-тайм 5 минут — константа, не из окружения.
REMINDER_LEAD = timedelta(minutes=5)

_SELECT_SENT_REMINDER = """
DECLARE $booking_id AS Utf8;
SELECT booking_id, sent_at FROM sent_reminders WHERE booking_id = $booking_id;
"""

_INSERT_SENT_REMINDER = """
DECLARE $booking_id AS Utf8;
DECLARE $sent_at AS Timestamp;
INSERT INTO sent_reminders (booking_id, sent_at)
VALUES ($booking_id, $sent_at);
"""

_DELETE_SENT_REMINDER = """
DECLARE $booking_id AS Utf8;
DELETE FROM sent_reminders WHERE booking_id = $booking_id;
"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    """Привести момент к tz-aware UTC (naive трактуется как UTC)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _utf8(value: str) -> Any:
    return ydb.TypedValue(value, ydb.PrimitiveType.Utf8)


def _ts(value: datetime) -> Any:
    return ydb.TypedValue(value, ydb.PrimitiveType.Timestamp)


class ReminderService:
    """Сервис отправки напоминаний за фиксированные 5 минут до начала."""

    def __init__(
        self,
        booking_service: BookingService,
        pool: ydb.QuerySessionPool,
        bot: Bot,
        display_timezone: ZoneInfo,
        admin_telegram_id: int,
    ) -> None:
        self._booking_service = booking_service
        self._pool = pool
        self._bot = bot
        self._display_timezone = display_timezone
        self._admin_telegram_id = admin_telegram_id

    def send_pending(self, *, now: datetime | None = None) -> None:
        """Отправить напоминания по созревшим броням.

        Находит активные будущие брони в горизонте REMINDER_LEAD,
        проверяет зрелость (now ≥ start - REMINDER_LEAD), отправляет
        с идемпотентностью через маркер sent_reminders.
        """
        now_utc = _utcnow() if now is None else _as_utc(now)
        horizon_end = now_utc + REMINDER_LEAD

        # Выборка кандидатов в горизонте [now, now + REMINDER_LEAD]
        candidates = self._booking_service.list_active_in_range(
            now_utc, horizon_end
        )

        for booking in candidates:
            self._try_send_reminder(booking, now_utc)

    def _try_send_reminder(self, booking: Any, now: datetime) -> None:
        """Попробовать отправить напоминание по брони с claim-then-send."""
        # Проверка зрелости: now ≥ start - REMINDER_LEAD
        reminder_time = booking.start - REMINDER_LEAD
        if now < reminder_time:
            return

        # Проверка: бронь ещё будущая
        if booking.start <= now:
            return

        # Проверка идемпотентности: маркер уже существует?
        if self._marker_exists(booking.id):
            return

        # Claim: пытаемся вставить маркер
        if not self._claim_marker(booking.id, now):
            return

        # Send: отправляем напоминание
        try:
            self._send_reminder(booking)
        except Exception as e:
            # Ошибка отправки — снимаем claim для повтора
            logger.warning(
                "Failed to send reminder for booking %s: %s",
                booking.id,
                e,
                exc_info=True,
            )
            self._unclaim_marker(booking.id)
            # Не падаем, продолжаем обработку
            return

        # Напоминание администратору — best-effort: его сбой НЕ снимает claim
        # (клиенту уже доставлено), чтобы не продублировать клиентское.
        try:
            self._send_admin_reminder(booking)
        except Exception as e:
            logger.warning(
                "Failed to send admin reminder for booking %s: %s",
                booking.id,
                e,
                exc_info=True,
            )

    def _marker_exists(self, booking_id: str) -> bool:
        """Проверить существование маркера отправки."""
        rows = _collect_rows(
            self._pool.execute_with_retries(
                _SELECT_SENT_REMINDER, {"$booking_id": _utf8(booking_id)}
            )
        )
        return len(rows) > 0

    def _claim_marker(self, booking_id: str, now: datetime) -> bool:
        """Завладеть маркером (insert-if-not-exists по PK)."""
        try:
            self._pool.execute_with_retries(
                _INSERT_SENT_REMINDER,
                {"$booking_id": _utf8(booking_id), "$sent_at": _ts(now)},
            )
            return True
        except ydb.issues.AlreadyExists:
            # PK-конфликт: маркер уже занят другим тиком
            return False

    def _unclaim_marker(self, booking_id: str) -> None:
        """Снять claim (удалить маркер при ошибке отправки)."""
        try:
            self._pool.execute_with_retries(
                _DELETE_SENT_REMINDER, {"$booking_id": _utf8(booking_id)}
            )
        except Exception:
            # Если удалить не удалось — оставим как есть, редкий дубль лучше пропуска.
            pass

    def _send_reminder(self, booking: Any) -> None:
        """Отправить напоминание клиенту (время в Europe/Moscow)."""
        time_str = format_slot_range(
            booking.start, booking.end, self._display_timezone
        )

        # Текст напоминания
        text = f"❗️ Напоминание: вы записаны на {time_str} (зал Африка)"

        # Отправляем через Bot. В проде send_message возвращает корутину —
        # выполняем её через asyncio.run в sync-контексте; синхронный
        # результат (например, в тестах) awaitable-проверкой пропускается.
        result = self._bot.send_message(booking.client_id, text)
        if inspect.isawaitable(result):
            asyncio.run(result)

    def _send_admin_reminder(self, booking: Any) -> None:
        """Отправить админу напоминание с человекочитаемым именем клиента.

        Имя берётся вживую через ``bot.get_chat`` (как в админ-потоке).
        Резолв имени и отправка выполняются одной корутиной под ``asyncio.run``,
        чтобы поддержать и синхронные тестовые двойники, и реальный async Bot.
        """

        async def _flow() -> None:
            name = await resolve_client_name(self._bot, booking.client_id)
            text = f"❗️ Через 5 минут начнётся сессия с пользователем {name}"
            result = self._bot.send_message(self._admin_telegram_id, text)
            if inspect.isawaitable(result):
                await result

        asyncio.run(_flow())


def _collect_rows(result_sets: Any) -> list[Any]:
    rows: list[Any] = []
    for result_set in result_sets:
        rows.extend(result_set.rows)
    return rows
