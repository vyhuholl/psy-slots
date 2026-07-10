"""Тонкие клиентские хендлеры потока записи (без доменной логики).

Хендлеры только парсят апдейт, зовут сервисы (`slot`, `booking`) и строят
ответ; вся доменная логика — в сервисном слое. Навигация без серверного
состояния: контекст шага берётся из ``callback_data`` (см. `keyboards`). Время
везде показывается в Europe/Moscow (``config.timezone``).

Зависимости (`config`, `slot_service`, `booking_service`, `bot`) внедряются
aiogram из workflow-данных диспетчера по имени параметра, поэтому в тестах
хендлеры вызываются напрямую с замоканными сервисами. Роутер собирается фабрикой
:func:`build_client_router` — свежий экземпляр на каждый вызов, чтобы один роутер
не привязывался к диспетчеру дважды.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from app.bot.formatting import format_slot_range
from app.bot.keyboards import (
    ACTION_CANCEL,
    ACTION_CANCEL_CONFIRM,
    ACTION_CONFIRM,
    ACTION_SLOT,
    BUTTON_BOOK,
    BUTTON_MY_BOOKINGS,
    bookings_keyboard,
    cancel_confirm_keyboard,
    confirm_keyboard,
    main_menu_keyboard,
    slots_keyboard,
    start_from_value,
    unpack,
)
from app.bot.naming import resolve_client_name
from app.config import Config
from app.domain.booking import Booking, BookingError, SlotTaken
from app.services.booking_service import BookingService
from app.services.slot_service import SlotService


async def _send_today_slots(
    bot: Bot,
    chat_id: int,
    config: Config,
    slot_service: SlotService,
) -> bool:
    """Показать сегодняшние свободные слоты; вернуть ``True``, если они есть.

    Если слотов нет — отправить сообщение о невозможности брони (из env) и
    вернуть ``False``.
    """
    slots = slot_service.list_free_slots()
    if not slots:
        await bot.send_message(chat_id, config.booking_unavailable_message)
        return False
    await bot.send_message(
        chat_id,
        "Выберите слот на сегодня (по московскому времени):",
        reply_markup=slots_keyboard(slots, config.timezone),
    )
    return True


def _active_booking_at(
    booking_service: BookingService, client_id: int, start: datetime
) -> Booking | None:
    """Активная бронь клиента, начинающаяся ровно в ``start`` (или ``None``)."""
    for booking in booking_service.list_active_for_client(client_id):
        if booking.start == start:
            return booking
    return None


async def handle_start(
    message: Message,
    *,
    bot: Bot,
    config: Config,
    slot_service: SlotService,
) -> None:
    """``/start`` — главное меню + слоты на сегодня либо сообщение о брони.

    Есть свободные слоты → приветствие (env) и список слотов. Нет → сообщение о
    невозможности брони (env). Постоянное меню прикрепляется к первому ответу
    (админ-кнопка — только администратору).
    """
    user = message.from_user
    if user is None:
        return
    menu = main_menu_keyboard(user.id == config.admin_telegram_id)
    slots = slot_service.list_free_slots()
    if not slots:
        await bot.send_message(
            message.chat.id,
            config.booking_unavailable_message,
            reply_markup=menu,
        )
        return
    await bot.send_message(
        message.chat.id, config.welcome_message, reply_markup=menu
    )
    await bot.send_message(
        message.chat.id,
        "Выберите слот на сегодня (по московскому времени):",
        reply_markup=slots_keyboard(slots, config.timezone),
    )


async def handle_book(
    message: Message,
    *,
    bot: Bot,
    config: Config,
    slot_service: SlotService,
) -> None:
    """``/book`` — показать свободные слоты на сегодня (или сообщение о брони)."""
    user = message.from_user
    if user is None:
        return
    await _send_today_slots(bot, message.chat.id, config, slot_service)


async def handle_slot(
    callback: CallbackQuery,
    *,
    bot: Bot,
    config: Config,
) -> None:
    """``slot:<epoch>`` — показать шаг подтверждения выбранного слота."""
    if callback.data is None:
        return
    _, value = unpack(callback.data)
    start = start_from_value(value)
    end = start + timedelta(minutes=config.slot_duration_minutes)
    await callback.answer()
    await bot.send_message(
        callback.from_user.id,
        f"Подтвердите запись на "
        f"{format_slot_range(start, end, config.timezone)}",
        reply_markup=confirm_keyboard(start),
    )


async def handle_confirm(
    callback: CallbackQuery,
    *,
    bot: Bot,
    config: Config,
    booking_service: BookingService,
) -> None:
    """``confirm:<epoch>`` — создать бронь; занятый слот/повтор — дружелюбно."""
    if callback.data is None:
        return
    _, value = unpack(callback.data)
    start = start_from_value(value)
    client_id = callback.from_user.id
    tz = config.timezone
    await callback.answer()
    try:
        booking = booking_service.create(client_id=client_id, start=start)
    except SlotTaken:
        existing = _active_booking_at(booking_service, client_id, start)
        if existing is not None:
            await bot.send_message(
                client_id,
                "Вы уже записаны на "
                f"{format_slot_range(existing.start, existing.end, tz)}.",
            )
        else:
            await bot.send_message(
                client_id,
                "Этот слот только что заняли — выберите, пожалуйста, другой.",
            )
        return
    except BookingError:
        await bot.send_message(
            client_id,
            "Этот слот сейчас недоступен — выберите, пожалуйста, другой.",
        )
        return
    await bot.send_message(
        client_id,
        f"Готово! Вы записаны на "
        f"{format_slot_range(booking.start, booking.end, tz)}.",
    )


async def handle_my_bookings(
    message: Message,
    *,
    bot: Bot,
    config: Config,
    booking_service: BookingService,
) -> None:
    """``/mybookings`` — активные брони клиента во времени Москвы."""
    user = message.from_user
    if user is None:
        return
    bookings = booking_service.list_active_for_client(user.id)
    if not bookings:
        await bot.send_message(message.chat.id, "У вас нет активных записей.")
        return
    ordered = sorted(bookings, key=lambda booking: booking.start)
    await bot.send_message(
        message.chat.id,
        "Ваши записи (нажмите, чтобы отменить):",
        reply_markup=bookings_keyboard(ordered, config.timezone),
    )


async def handle_cancel_request(
    callback: CallbackQuery,
    *,
    bot: Bot,
    config: Config,
    booking_service: BookingService,
) -> None:
    """``cancel:<id>`` — шаг подтверждения отмены брони."""
    if callback.data is None:
        return
    _, booking_id = unpack(callback.data)
    booking = booking_service.get(booking_id)
    await callback.answer()
    if booking is None or not booking.is_active:
        await bot.send_message(
            callback.from_user.id, "Запись не найдена или уже отменена."
        )
        return
    await bot.send_message(
        callback.from_user.id,
        "Отменить запись на "
        f"{format_slot_range(booking.start, booking.end, config.timezone)}?",
        reply_markup=cancel_confirm_keyboard(booking_id),
    )


async def handle_cancel_confirm(
    callback: CallbackQuery,
    *,
    bot: Bot,
    config: Config,
    booking_service: BookingService,
) -> None:
    """``cancelok:<id>`` — отменить бронь и уведомить администратора."""
    if callback.data is None:
        return
    _, booking_id = unpack(callback.data)
    booking = booking_service.cancel(booking_id)
    await callback.answer()
    await bot.send_message(callback.from_user.id, "Запись отменена.")

    # Уведомление администратору об отмене клиентом (сбой не откатывает отмену).
    name = await resolve_client_name(bot, callback.from_user.id)
    time_str = format_slot_range(booking.start, booking.end, config.timezone)
    try:
        await bot.send_message(
            config.admin_telegram_id,
            f"Пользователь {name} отменил запись на {time_str}.",
        )
    except Exception:
        pass


def build_client_router() -> Router:
    """Собрать свежий роутер клиентского потока (команды, меню, колбэки).

    Новый экземпляр на каждый вызов: один роутер нельзя привязать к диспетчеру
    дважды, а фабрика диспетчера может вызываться многократно. Кнопки меню
    маршрутизируются по тексту в те же хендлеры, что и команды.
    """
    router = Router(name="client")
    router.message.register(handle_start, CommandStart())
    router.message.register(handle_book, Command("book"))
    router.message.register(handle_book, F.text == BUTTON_BOOK)
    router.message.register(handle_my_bookings, Command("mybookings"))
    router.message.register(handle_my_bookings, F.text == BUTTON_MY_BOOKINGS)
    router.callback_query.register(
        handle_slot, F.data.startswith(f"{ACTION_SLOT}:")
    )
    router.callback_query.register(
        handle_confirm, F.data.startswith(f"{ACTION_CONFIRM}:")
    )
    router.callback_query.register(
        handle_cancel_request, F.data.startswith(f"{ACTION_CANCEL}:")
    )
    router.callback_query.register(
        handle_cancel_confirm, F.data.startswith(f"{ACTION_CANCEL_CONFIRM}:")
    )
    return router
