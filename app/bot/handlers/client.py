"""Тонкие клиентские хендлеры потока записи (без доменной логики).

Хендлеры только парсят апдейт, зовут сервисы (`client`, `slot`, `booking`) и
строят ответ; вся доменная логика — в сервисном слое. Навигация без серверного
состояния: контекст шага берётся из ``callback_data`` (см. `keyboards`).

Зависимости (`config`, `client_service`, `slot_service`, `booking_service`,
`bot`) внедряются aiogram из workflow-данных диспетчера по имени параметра,
поэтому в тестах хендлеры вызываются напрямую с замоканными сервисами.
Роутер собирается фабрикой :func:`build_client_router` — свежий экземпляр на
каждый вызов, чтобы один роутер не привязывался к диспетчеру дважды.
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
    ACTION_TZ,
    bookings_keyboard,
    cancel_confirm_keyboard,
    confirm_keyboard,
    slots_keyboard,
    start_from_value,
    timezone_keyboard,
    unpack,
)
from app.config import Config
from app.domain.booking import Booking, BookingError, SlotTaken
from app.domain.client import Client
from app.services.booking_service import BookingService
from app.services.client_service import ClientService
from app.services.slot_service import SlotService


async def _send_today_slots(
    bot: Bot,
    chat_id: int,
    client: Client,
    config: Config,
    slot_service: SlotService,
) -> None:
    """Показать сегодняшние свободные слоты или сообщение об их отсутствии."""
    slots = slot_service.list_free_slots()
    if not slots:
        await bot.send_message(chat_id, config.booking_unavailable_message)
        return
    await bot.send_message(
        chat_id,
        "Свободное время на сегодня — выберите слот:",
        reply_markup=slots_keyboard(slots, client.zoneinfo),
    )


def _active_booking_at(
    booking_service: BookingService, client_id: int, start: datetime
) -> Booking | None:
    """Активная бронь клиента, начинающаяся ровно в ``start`` (или ``None``)."""
    for booking in booking_service.list_active_for_client(client_id):
        if booking.start == start:
            return booking
    return None


async def handle_start(message: Message, *, config: Config) -> None:
    """``/start`` — приветствие с текстом из конфигурации."""
    await message.answer(config.welcome_message)


async def handle_timezone(message: Message, *, bot: Bot) -> None:
    """``/timezone`` — сменить таймзону (показать выбор зон)."""
    await bot.send_message(
        message.chat.id,
        "Выберите свою таймзону:",
        reply_markup=timezone_keyboard(),
    )


async def handle_book(
    message: Message,
    *,
    bot: Bot,
    config: Config,
    client_service: ClientService,
    slot_service: SlotService,
) -> None:
    """``/book`` — при известной TZ показать слоты, иначе запросить TZ."""
    user = message.from_user
    if user is None:
        return
    client = client_service.get(user.id)
    if client is None:
        await bot.send_message(
            message.chat.id,
            "Чтобы показать время в вашем часовом поясе, выберите таймзону:",
            reply_markup=timezone_keyboard(),
        )
        return
    await _send_today_slots(bot, message.chat.id, client, config, slot_service)


async def handle_set_timezone(
    callback: CallbackQuery,
    *,
    bot: Bot,
    config: Config,
    client_service: ClientService,
    slot_service: SlotService,
) -> None:
    """``tz:<name>`` — сохранить таймзону клиента и продолжить к слотам."""
    if callback.data is None:
        return
    _, name = unpack(callback.data)
    client = client_service.set_timezone(callback.from_user.id, name)
    await callback.answer()
    await _send_today_slots(
        bot, callback.from_user.id, client, config, slot_service
    )


async def handle_slot(
    callback: CallbackQuery,
    *,
    bot: Bot,
    config: Config,
    client_service: ClientService,
) -> None:
    """``slot:<epoch>`` — показать шаг подтверждения выбранного слота."""
    if callback.data is None:
        return
    _, value = unpack(callback.data)
    start = start_from_value(value)
    client = client_service.get(callback.from_user.id)
    tz = client.zoneinfo if client is not None else config.timezone
    end = start + timedelta(minutes=config.slot_duration_minutes)
    await callback.answer()
    await bot.send_message(
        callback.from_user.id,
        f"Подтвердите запись на {format_slot_range(start, end, tz)}",
        reply_markup=confirm_keyboard(start),
    )


async def handle_confirm(
    callback: CallbackQuery,
    *,
    bot: Bot,
    config: Config,
    client_service: ClientService,
    booking_service: BookingService,
) -> None:
    """``confirm:<epoch>`` — создать бронь; занятый слот/повтор — дружелюбно."""
    if callback.data is None:
        return
    _, value = unpack(callback.data)
    start = start_from_value(value)
    client_id = callback.from_user.id
    client = client_service.get(client_id)
    tz = client.zoneinfo if client is not None else config.timezone
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
    client_service: ClientService,
    booking_service: BookingService,
) -> None:
    """``/mybookings`` — активные брони клиента во времени клиента."""
    user = message.from_user
    if user is None:
        return
    client = client_service.get(user.id)
    tz = client.zoneinfo if client is not None else config.timezone
    bookings = booking_service.list_active_for_client(user.id)
    if not bookings:
        await bot.send_message(message.chat.id, "У вас нет активных записей.")
        return
    ordered = sorted(bookings, key=lambda booking: booking.start)
    await bot.send_message(
        message.chat.id,
        "Ваши записи (нажмите, чтобы отменить):",
        reply_markup=bookings_keyboard(ordered, tz),
    )


async def handle_cancel_request(
    callback: CallbackQuery,
    *,
    bot: Bot,
    config: Config,
    client_service: ClientService,
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
    client = client_service.get(callback.from_user.id)
    tz = client.zoneinfo if client is not None else config.timezone
    await bot.send_message(
        callback.from_user.id,
        "Отменить запись на "
        f"{format_slot_range(booking.start, booking.end, tz)}?",
        reply_markup=cancel_confirm_keyboard(booking_id),
    )


async def handle_cancel_confirm(
    callback: CallbackQuery,
    *,
    bot: Bot,
    booking_service: BookingService,
) -> None:
    """``cancelok:<id>`` — выполнить отмену через доменный сервис."""
    if callback.data is None:
        return
    _, booking_id = unpack(callback.data)
    booking_service.cancel(booking_id)
    await callback.answer()
    await bot.send_message(callback.from_user.id, "Запись отменена.")


def build_client_router() -> Router:
    """Собрать свежий роутер клиентского потока (команды + колбэки).

    Новый экземпляр на каждый вызов: один роутер нельзя привязать к диспетчеру
    дважды, а фабрика диспетчера может вызываться многократно.
    """
    router = Router(name="client")
    router.message.register(handle_start, CommandStart())
    router.message.register(handle_timezone, Command("timezone"))
    router.message.register(handle_book, Command("book"))
    router.message.register(handle_my_bookings, Command("mybookings"))
    router.callback_query.register(
        handle_set_timezone, F.data.startswith(f"{ACTION_TZ}:")
    )
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
