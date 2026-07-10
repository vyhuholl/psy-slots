"""Точка входа Yandex Cloud Function в webhook-режиме.

Разбирает HTTP-событие YC (``body``/``headers``), валидирует секрет
вебхука Telegram, десериализует апдейт и прогоняет его через aiogram
Dispatcher, возвращая корректный HTTP-ответ. Никакого long polling, без
фоновых задач и планировщиков: один апдейт на вызов, состояние между
вызовами не удерживается.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.types import Update
from pydantic import ValidationError

from app.bot import create_bot, create_dispatcher
from app.config import load_config
from app.services.booking_service import BookingService
from app.services.slot_service import SlotService
from app.ydb_client import get_pool

logger = logging.getLogger(__name__)

SECRET_HEADER = "x-telegram-bot-api-secret-token"

_HTTP_OK = 200
_HTTP_FORBIDDEN = 403

# Тёплые синглтоны переиспользуются между вызовами тёплого инстанса.
_bot: Bot | None = None
_dispatcher: Dispatcher | None = None
# Тёплый событийный цикл: aiohttp-сессия бота привязывается к циклу при
# создании, поэтому цикл нельзя закрывать между апдейтами. ``asyncio.run()``
# создавал и закрывал новый цикл на каждый вызов — из-за чего повторный вызов
# на тёплом инстансе падал с «Event loop is closed». Переиспользуем один цикл.
_loop: asyncio.AbstractEventLoop | None = None


def _get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = create_bot()
    return _bot


def _get_loop() -> asyncio.AbstractEventLoop:
    global _loop
    if _loop is None:
        _loop = asyncio.new_event_loop()
    return _loop


def _get_dispatcher() -> Dispatcher:
    global _dispatcher
    if _dispatcher is None:
        config = load_config()
        pool = get_pool()
        booking_service = BookingService(config, pool)
        _dispatcher = create_dispatcher(
            config=config,
            slot_service=SlotService(config, booking_service),
            booking_service=booking_service,
        )
    return _dispatcher


def _extract_secret(headers: dict[str, Any]) -> str | None:
    for key, value in headers.items():
        if key.lower() == SECRET_HEADER:
            return value if isinstance(value, str) else None
    return None


def _extract_body(event: dict[str, Any]) -> str:
    body = event.get("body") or ""
    if not isinstance(body, str):
        return ""
    if event.get("isBase64Encoded"):
        try:
            return base64.b64decode(body).decode("utf-8")
        except binascii.Error, UnicodeDecodeError:
            return ""
    return body


def _response(status_code: int, body: str) -> dict[str, Any]:
    return {"statusCode": status_code, "body": body}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Обработать одно webhook-событие YC и вернуть HTTP-ответ."""
    config = load_config()
    headers = event.get("headers") or {}

    if _extract_secret(headers) != config.webhook_secret:
        logger.warning("Rejected webhook request: bad or missing secret")
        return _response(_HTTP_FORBIDDEN, "forbidden")

    raw_body = _extract_body(event)
    try:
        payload = json.loads(raw_body)
        update = Update.model_validate(payload)
    except json.JSONDecodeError, ValidationError, TypeError:
        logger.warning("Ignored webhook request: malformed update body")
        return _response(_HTTP_OK, "ignored")

    _get_loop().run_until_complete(
        _get_dispatcher().feed_update(_get_bot(), update)
    )
    return _response(_HTTP_OK, "ok")
