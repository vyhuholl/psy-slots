"""Точка входа timer-триггера для отправки напоминаний.

Отдельная YC-функция с timer-триггером, которая на каждый тик находит
брони, до начала которых осталось 5 минут, и шлёт по ним напоминания.

Никаких фоновых задач и планировщиков — только один проход через
ReminderService и завершение. Bot тёплый (на уровне модуля).
"""

from __future__ import annotations

from datetime import datetime, timezone

from logging import getLogger
from typing import Any

from aiogram import Bot

from app.config import load_config
from app.services.booking_service import BookingService
from app.services.reminder_service import ReminderService
from app.ydb_client import get_pool

logger = getLogger(__name__)

# Тёплый Bot на уровне модуля (повторно используется между вызовами)
_bot: Bot | None = None

# Кэшированный сервис напоминаний (переиспользуется между вызовами)
_reminder_service: ReminderService | None = None


def _get_bot() -> Bot:
    """Вернуть тёплый Bot (инициализируется один раз)."""
    global _bot
    if _bot is None:
        config = load_config()
        _bot = Bot(token=config.bot_token)
    return _bot


def _get_reminder_service() -> ReminderService:
    """Вернуть сервис напоминаний (инициализируется один раз)."""
    global _reminder_service
    if _reminder_service is None:
        config = load_config()
        pool = get_pool()
        booking_service = BookingService(config, pool)
        bot = _get_bot()
        _reminder_service = ReminderService(
            booking_service, pool, bot, config.timezone
        )
    return _reminder_service


def notify(*, now: datetime | None = None) -> None:
    """Обработать созревшие напоминания и завершиться.

    Точка входа для timer-триггера YC. Находит брони, до начала которых
    осталось 5 минут или меньше, и шлёт по ним напоминания.
    Идемпотентна: повторные тики не шлют дублей.

    Args:
        now: Текущий момент для тестирования. По умолчанию — ``now()`` в UTC.
    """
    now_utc = datetime.now(timezone.utc) if now is None else now

    logger.info("Processing reminders at %s", now_utc.isoformat())

    try:
        service = _get_reminder_service()
        service.send_pending(now=now_utc)
        logger.info("Reminder processing completed")
    except Exception as e:
        logger.error("Failed to process reminders: %s", e, exc_info=True)
        raise


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Точка входа YC timer-триггера.

    YC вызывает точку входа как ``h(event, context)`` — два позиционных
    аргумента, тогда как :func:`notify` принимает лишь keyword-only ``now``.
    Эта обёртка адаптирует сигнатуру: аргументы триггера игнорируются,
    обрабатываются созревшие напоминания, возвращается HTTP-ответ.
    """
    notify()
    return {"statusCode": 200, "body": "ok"}


def main() -> None:
    """Точка входа для локального запуска (без триггера)."""
    notify()


if __name__ == "__main__":  # pragma: no cover
    main()
