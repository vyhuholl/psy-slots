"""Инлайн-клавиатуры, главное меню и единая (де)сериализация ``callback_data``.

Навигация без серверного состояния: каждая инлайн-кнопка несёт полный контекст
шага в ``callback_data`` (``slot:<epoch>``, ``confirm:<epoch>``, ``cancel:<id>``,
``cancelok:<id>``, ``admincancel:<id>``). Хендлер восстанавливает выбор из
``callback_data`` и заново зовёт сервисы — это единственная точка кодирования,
что корректно для эфемерной serverless-функции.

Главное меню — постоянная reply-клавиатура (:func:`main_menu_keyboard`); её
кнопки шлют свой текст обычным сообщением, а роутеры сопоставляют этот текст с
командами. Админ-кнопка добавляется только администратору.

Бюджет Telegram — 64 байта на ``callback_data``: epoch-seconds (~10) и UUID (36)
укладываются с запасом; :func:`pack` это проверяет.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.bot.formatting import format_slot_range
from app.domain.booking import Booking
from app.domain.slots import Slot

# Префиксы действий в callback_data.
ACTION_SLOT = "slot"
ACTION_CONFIRM = "confirm"
ACTION_CANCEL = "cancel"
ACTION_CANCEL_CONFIRM = "cancelok"
ACTION_ADMIN_CANCEL = "admincancel"

# Тексты кнопок главного меню (reply-клавиатура). Они же — маркеры маршрутизации
# в роутерах: нажатие шлёт этот текст, хендлер сопоставляет его с командой.
BUTTON_BOOK = "✏️ Записаться"
BUTTON_MY_BOOKINGS = "🗓️ Мои записи"
BUTTON_ADMIN = "📘 Показать все брони"

# Лимит Telegram на callback_data.
CALLBACK_MAX_BYTES = 64

_SEP = ":"

# Слотов в ряду клавиатуры выбора времени.
_SLOTS_PER_ROW = 3


def pack(action: str, value: str) -> str:
    """Собрать ``callback_data`` из действия и значения, проверив бюджет."""
    data = f"{action}{_SEP}{value}"
    if len(data.encode("utf-8")) > CALLBACK_MAX_BYTES:
        raise ValueError(f"callback_data exceeds {CALLBACK_MAX_BYTES} bytes")
    return data


def unpack(data: str) -> tuple[str, str]:
    """Разобрать ``callback_data`` в ``(action, value)`` по первому ``:``."""
    action, _, value = data.partition(_SEP)
    return action, value


def _epoch(start_utc: datetime) -> str:
    return str(int(start_utc.timestamp()))


def start_from_value(value: str) -> datetime:
    """Восстановить UTC-момент слота из значения ``callback_data``."""
    return datetime.fromtimestamp(int(value), tz=UTC)


def _rows(
    buttons: Sequence[InlineKeyboardButton], per_row: int
) -> list[list[InlineKeyboardButton]]:
    return [
        list(buttons[i : i + per_row]) for i in range(0, len(buttons), per_row)
    ]


def main_menu_keyboard(is_admin: bool) -> ReplyKeyboardMarkup:
    """Постоянное главное меню; админ-кнопка видна только администратору."""
    rows = [
        [KeyboardButton(text=BUTTON_BOOK)],
        [KeyboardButton(text=BUTTON_MY_BOOKINGS)],
    ]
    if is_admin:
        rows.append([KeyboardButton(text=BUTTON_ADMIN)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def slots_keyboard(
    slots: Sequence[Slot], tz: ZoneInfo
) -> InlineKeyboardMarkup:
    """Клавиатура сегодняшних свободных слотов диапазоном (время в ``tz``)."""
    buttons = [
        InlineKeyboardButton(
            text=format_slot_range(slot.start, slot.end, tz),
            callback_data=pack(ACTION_SLOT, _epoch(slot.start)),
        )
        for slot in slots
    ]
    return InlineKeyboardMarkup(inline_keyboard=_rows(buttons, _SLOTS_PER_ROW))


def confirm_keyboard(start_utc: datetime) -> InlineKeyboardMarkup:
    """Клавиатура подтверждения записи на выбранный слот."""
    button = InlineKeyboardButton(
        text="✅ Подтвердить",
        callback_data=pack(ACTION_CONFIRM, _epoch(start_utc)),
    )
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


def bookings_keyboard(
    bookings: Sequence[Booking], tz: ZoneInfo
) -> InlineKeyboardMarkup:
    """Клавиатура активных броней клиента с кнопкой отмены на каждой."""
    buttons = [
        InlineKeyboardButton(
            text=f"{format_slot_range(b.start, b.end, tz)} (Африка) ❌",
            callback_data=pack(ACTION_CANCEL, b.id),
        )
        for b in bookings
    ]
    return InlineKeyboardMarkup(inline_keyboard=_rows(buttons, 1))


def cancel_confirm_keyboard(booking_id: str) -> InlineKeyboardMarkup:
    """Клавиатура подтверждения отмены брони (лёгкий confirm-шаг)."""
    button = InlineKeyboardButton(
        text="Да, отменить",
        callback_data=pack(ACTION_CANCEL_CONFIRM, booking_id),
    )
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


def admin_bookings_keyboard(
    bookings: Sequence[Booking],
    tz: ZoneInfo,
    names: Mapping[int, str],
) -> InlineKeyboardMarkup:
    """Клавиатура активных броней для админа: диапазон + человекочитаемое имя.

    Имя клиента (``names[client_id]``, fallback — ``telegram_id``) ставится
    после диапазона без обрамляющих скобок, напр. «14:20-14:40 Иван (@ivan) ❌».
    """
    buttons = [
        InlineKeyboardButton(
            text=(
                f"{format_slot_range(b.start, b.end, tz)} "
                f"{names.get(b.client_id, str(b.client_id))} ❌"
            ),
            callback_data=pack(ACTION_ADMIN_CANCEL, b.id),
        )
        for b in bookings
    ]
    return InlineKeyboardMarkup(inline_keyboard=_rows(buttons, 1))
