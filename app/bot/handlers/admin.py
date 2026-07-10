"""Тонкие админ-хендлеры (авторизация, просмотр, отмена).

Поток администратора поверх существующих read/cancel-запросов сервиса броней.
Авторизация — сверка с ADMIN_TELEGRAM_ID из конфигурации. Хендлеры тонкие:
вызывают сервисы и строят ответ; доменная логика — в сервисном слое. Время
показывается в Europe/Moscow (``config.timezone``); имя клиента — человекочитаемо
через ``bot.get_chat`` (см. :func:`app.bot.naming.resolve_client_name`).
"""

from __future__ import annotations


from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.formatting import format_slot_range
from app.bot.keyboards import (
    ACTION_ADMIN_CANCEL,
    BUTTON_ADMIN,
    admin_bookings_keyboard,
    unpack,
)
from app.bot.naming import resolve_client_name
from app.config import Config
from app.services.booking_service import BookingService


# --- Проверка авторизации ----------------------------------------------------


def _is_admin(user_id: int, config: Config) -> bool:
    """Проверить, что пользователь — администратор (id совпадает с конфигом)."""
    return user_id == config.admin_telegram_id


# --- Хендлер просмотра броней ------------------------------------------------


async def handle_admin_list(
    message: Message,
    *,
    bot: Bot,
    config: Config,
    booking_service: BookingService,
) -> None:
    """``/admin`` — показать все активные брони (админ-only, TZ Europe/Moscow)."""
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

    # Человекочитаемые имена клиентов по уникальным id (дедупликация вызовов).
    ordered = sorted(bookings, key=lambda booking: booking.start)
    names = {
        client_id: await resolve_client_name(bot, client_id)
        for client_id in {booking.client_id for booking in ordered}
    }
    await bot.send_message(
        message.chat.id,
        "Активные записи (нажмите для отмены):",
        reply_markup=admin_bookings_keyboard(ordered, config.timezone, names),
    )


# --- Хендлер отмены брони ----------------------------------------------------


async def handle_admin_cancel_confirm(
    callback: CallbackQuery,
    *,
    bot: Bot,
    config: Config,
    booking_service: BookingService,
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

    # Уведомление клиента во времени Москвы
    time_str = format_slot_range(booking.start, booking.end, config.timezone)
    try:
        await bot.send_message(
            booking.client_id,
            f"Ваша запись на {time_str} была отменена администратором.",
        )
    except Exception:
        # Клиент мог заблокировать бота — логируем, но не откатываем отмену
        pass

    await callback.answer()
    await bot.send_message(callback.from_user.id, "Запись отменена.")


# --- Роутер ------------------------------------------------------------------


def build_admin_router() -> Router:
    """Собрать свежий админ-роутер (команда, кнопка меню, колбэк)."""
    router = Router(name="admin")
    router.message.register(handle_admin_list, Command("admin"))
    router.message.register(handle_admin_list, F.text == BUTTON_ADMIN)
    router.callback_query.register(
        handle_admin_cancel_confirm,
        F.data.startswith(f"{ACTION_ADMIN_CANCEL}:"),
    )
    return router
