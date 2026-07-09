"""Тонкие админ-хендлеры (авторизация, просмотр, отмена).

Поток администратора поверх существующих read/cancel-запросов сервиса броней.
Авторизация — сверка с ADMIN_TELEGRAM_ID из конфигурации. Хендлеры тонкие:
вызывают сервисы и строят ответ; доменная логика — в сервисном слое.
"""

from __future__ import annotations


from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.formatting import format_slot_range
from app.bot.keyboards import (
    ACTION_ADMIN_CANCEL,
    admin_bookings_keyboard,
    unpack,
)
from app.config import Config
from app.services.booking_service import BookingService
from app.services.client_service import ClientService


# --- 1.2 Проверка авторизации -----------------------------------------------


def _is_admin(user_id: int, config: Config) -> bool:
    """Проверить, что пользователь — администратор (id совпадает с конфигом)."""
    return user_id == config.admin_telegram_id


# --- 1.2 / 2.2 Хендлер просмотра броней -------------------------------------


async def handle_admin_list(
    message: Message,
    *,
    bot: Bot,
    config: Config,
    booking_service: BookingService,
) -> None:
    """``/admin`` — показать все активные брони (админ-only, TZ конфигурации)."""
    user = message.from_user
    if user is None:
        return

    # Проверка авторизации: не-админ получает отказ
    if not _is_admin(user.id, config):
        await bot.send_message(
            message.chat.id,
            "У вас нет прав для выполнения этой команды.",
        )
        return

    # Список всех активных броней
    bookings = booking_service.list_active()

    if not bookings:
        await bot.send_message(message.chat.id, "Активных записей нет.")
        return

    # Форматирование в таймзоне конфигурации + клавиатура отмены
    ordered = sorted(bookings, key=lambda booking: booking.start)
    text = "Активные записи (нажмите для отмены):"
    await bot.send_message(
        message.chat.id,
        text,
        reply_markup=admin_bookings_keyboard(ordered, config.timezone),
    )


# --- 3.3 Хендлер отмены брони -----------------------------------------------


async def handle_admin_cancel_confirm(
    callback: CallbackQuery,
    *,
    bot: Bot,
    config: Config,
    booking_service: BookingService,
    client_service: ClientService,
) -> None:
    """``admincancel:<id>`` — отменить бронь и уведомить клиента (админ-only)."""
    if callback.data is None:
        return

    # Проверка авторизации
    if not _is_admin(callback.from_user.id, config):
        await callback.answer()
        await bot.send_message(
            callback.from_user.id,
            "У вас нет прав для выполнения этой команды.",
        )
        return

    _, booking_id = unpack(callback.data)

    # Отмена через сервис (идемпотентная)
    booking = booking_service.cancel(booking_id)

    # Уведомление клиента во времени клиента
    client = client_service.get(booking.client_id)
    tz = client.zoneinfo if client is not None else config.timezone

    try:
        await bot.send_message(
            booking.client_id,
            f"Ваша запись на {format_slot_range(booking.start, booking.end, tz)} "
            f"была отменена администратором.",
        )
    except Exception:
        # Клиент мог заблокировать бота — логируем, но не откатываем отмену
        pass

    await callback.answer()
    await bot.send_message(callback.from_user.id, "Запись отменена.")


# --- Роутер ------------------------------------------------------------------


def build_admin_router() -> Router:
    """Собрать свежий админ-роутер (команды + колбэки)."""
    router = Router(name="admin")
    router.message.register(handle_admin_list, Command("admin"))
    router.callback_query.register(
        handle_admin_cancel_confirm,
        F.data.startswith(f"{ACTION_ADMIN_CANCEL}:"),
    )
    return router
