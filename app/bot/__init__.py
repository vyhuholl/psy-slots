"""Сборка aiogram ``Bot``/``Dispatcher`` для webhook-режима.

Хендлеры тонкие; доменная логика — в сервисном слое и вызывается из клиентского
роутера (:func:`app.bot.handlers.client.build_client_router`). Токен бота и
прочая конфигурация берутся из окружения через :mod:`app.config`.

Сервисы внедряются в диспетчер как workflow-данные и раздаются aiogram в
хендлеры по имени параметра. Фабрика диспетчера не создаёт сервисы сама (чтобы
не трогать YDB там, где он не нужен) — их передаёт тёплый обработчик вебхука.
"""

from __future__ import annotations

from aiogram import Bot, Dispatcher

from app.bot.handlers.client import build_client_router
from app.config import Config, load_config
from app.services.booking_service import BookingService
from app.services.client_service import ClientService
from app.services.slot_service import SlotService


def create_bot(config: Config | None = None) -> Bot:
    """Собрать ``Bot`` с токеном из конфигурации."""
    resolved = config if config is not None else load_config()
    return Bot(token=resolved.bot_token)


def create_dispatcher(
    *,
    config: Config | None = None,
    client_service: ClientService | None = None,
    slot_service: SlotService | None = None,
    booking_service: BookingService | None = None,
) -> Dispatcher:
    """Собрать ``Dispatcher`` с клиентским роутером и внедрёнными сервисами.

    Каждый вызов даёт независимый экземпляр со свежим роутером (общий роутер
    нельзя привязать дважды). Переданные сервисы кладутся в workflow-данные и
    раздаются хендлерам по имени параметра; при их отсутствии диспетчер годится
    для проверок регистрации без обращения к YDB.
    """
    dispatcher = Dispatcher()
    dispatcher.include_router(build_client_router())
    deps: dict[str, object] = {
        "config": config,
        "client_service": client_service,
        "slot_service": slot_service,
        "booking_service": booking_service,
    }
    dispatcher.workflow_data.update(
        {name: value for name, value in deps.items() if value is not None}
    )
    return dispatcher
