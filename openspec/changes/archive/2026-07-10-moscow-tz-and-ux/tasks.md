## 1. Фиксированная таймзона Europe/Moscow (bot-config)

- [x] 1.1 Обновить `tests/test_config.py`: конфиг грузится без `TIMEZONE`; `Config.timezone == ZoneInfo("Europe/Moscow")`; переменная `TIMEZONE` игнорируется/не требуется (падающий тест)
- [x] 1.2 В `app/config.py` убрать поле/валидатор `TIMEZONE`, сделать `timezone` фиксированным свойством `ZoneInfo("Europe/Moscow")`
- [x] 1.3 Убрать `TIMEZONE` из `.env.example`

## 2. Удаление профиля клиента и ClientService (client-profile)

Полностью убрать `ClientService`, домен `Client` и таблицу `clients` из всей кодовой базы; всё, что раньше брало таймзону клиента, использует фиксированную `Europe/Moscow` (`config.timezone`).

- [x] 2.1 Обновить `tests/test_reminder_service.py`: `ReminderService` строится и форматирует время в `Europe/Moscow` без `ClientService`/`Client` (падающий тест); убрать импорт `Client`/`ClientService` и проверки таймзоны клиента
- [x] 2.2 В `app/services/reminder_service.py` убрать параметр `client_service` и `_get_client_timezone`; форматировать по фиксированной таймзоне (`config.timezone`)
- [x] 2.3 Обновить `tests/test_notify.py` (убрать `patch("app.notify.ClientService")` и связанные ожидания); в `app/notify.py` убрать импорт/создание `ClientService` и его передачу в `ReminderService`
- [x] 2.4 Обновить `tests/test_bot.py` (DI больше не содержит `client_service`); в `app/bot/__init__.py` убрать параметр `client_service` и его запись в `workflow_data`; в `app/handler.py` убрать импорт и `client_service=ClientService(pool)`
- [x] 2.5 В `app/bot/handlers/client.py` и `app/bot/handlers/admin.py` убрать параметр `client_service` из сигнатур и все вызовы `client_service.get(...)`/`set_timezone(...)`; где бралась таймзона клиента — использовать `config.timezone`; обновить `tests/test_client_handlers.py`/`tests/test_admin_handlers.py` (убрать моки `client_service` и `Client`)
- [x] 2.6 В `app/migrations.py` убрать `CREATE TABLE clients` (без `DROP`); обновить `tests/test_migrations.py`
- [x] 2.7 Удалить файлы `app/domain/client.py`, `app/services/client_service.py`, `tests/test_client.py`, `tests/test_client_service.py`
- [x] 2.8 Grep-проверка: `ClientService`, `client_service`, `from app.domain.client` не встречаются в `app/` и `tests/`

## 3. Диапазонный формат слота (client-booking-flow)

- [x] 3.1 Обновить `tests/test_keyboards.py`: текст кнопки слота — диапазон «14:00-14:20» (`format_slot_range`) (падающий тест)
- [x] 3.2 В `app/bot/keyboards.py` `slots_keyboard` формировать текст через `format_slot_range` (start-end), `callback_data` не менять

## 4. Reply-меню главного меню (main-menu)

- [x] 4.1 Добавить в `tests/test_keyboards.py` тесты `main_menu_keyboard(is_admin)`: 3 кнопки для админа (вкл. «📘 Показать все брони»), 2 кнопки для не-админа (падающий тест)
- [x] 4.2 В `app/bot/keyboards.py` реализовать `main_menu_keyboard(is_admin: bool)` и вынести тексты кнопок в именованные константы
- [x] 4.3 Добавить в `tests/test_client_handlers.py`/`tests/test_admin_handlers.py` тесты маршрутизации по тексту кнопок → `handle_book`/`handle_my_bookings`/`handle_admin_list` (падающий тест)
- [x] 4.4 Зарегистрировать в роутерах message-хендлеры с фильтром по тексту кнопок, вызывающие соответствующие команды

## 5. Поток /start (client-booking-flow)

- [x] 5.1 Обновить `tests/test_client_handlers.py` для `handle_start`: при наличии слотов — `WELCOME_MESSAGE` + слоты; без слотов — `BOOKING_UNAVAILABLE_MESSAGE`; ответ несёт reply-меню (падающий тест)
- [x] 5.2 Переписать `handle_start`: внедрить `slot_service`/`config`, зов `list_free_slots`, ветвление приветствие+слоты / сообщение о невозможности, прикрепить `main_menu_keyboard`
- [x] 5.3 Удалить `/timezone`: команду, `handle_set_timezone`, `timezone_keyboard`, `COMMON_TIMEZONES` и их тесты; `handle_book` сразу показывает слоты, без шага запроса таймзоны (удаление `client_service`-проводки и переход на `Europe/Moscow` — в группе 2)

## 6. Человекочитаемое имя клиента (admin-flow)

- [x] 6.1 Добавить тесты `resolve_client_name(bot, client_id)`: `Имя Фамилия (@username)` / `@username` / `telegram_id`; деградация до `telegram_id` при исключении `bot.get_chat` (падающий тест)
- [x] 6.2 Реализовать асинхронный `resolve_client_name` (формат по приоритету, try/except → `telegram_id`)
- [x] 6.3 Обновить `tests/test_keyboards.py` и `tests/test_admin_handlers.py`: `admin_bookings_keyboard(bookings, tz, names)` ставит имя после диапазона без обрамляющих скобок; `handle_admin_list` строит словарь имён по уникальным `client_id` (падающий тест)
- [x] 6.4 В `app/bot/keyboards.py` принять `names: dict[int,str]` в `admin_bookings_keyboard`; в `handle_admin_list` резолвить имена через `resolve_client_name` (дедупликация) и передавать в клавиатуру

## 7. Уведомление админа об отмене клиентом (client-booking-flow)

- [x] 7.1 Обновить `tests/test_client_handlers.py`: `handle_cancel_confirm` шлёт `ADMIN_TELEGRAM_ID` «Пользователь <имя> отменил запись на <диапазон>»; сбой доставки не ломает отмену (падающий тест)
- [x] 7.2 В `handle_cancel_confirm` после `cancel(...)` сформировать имя через `resolve_client_name` и отправить админу уведомление (диапазон в `Europe/Moscow`), обёрнутое в `try/except`

## 8. Документация

- [x] 8.1 Обновить `CLAUDE.md`: фиксированная таймзона `Europe/Moscow` (убрать «таймзону из env»/«не хардкодить таймзону»), отсутствие профиля клиента, reply-меню, диапазонный формат слота, имена клиента через `bot.get_chat`
- [x] 8.2 Обновить `README.md`: убрать `TIMEZONE` и `/timezone` из таблиц, убрать таблицу `clients`/`client.py`/`client_service.py` из структуры, описать меню, стартовый поток, имена клиента и уведомление админа об отмене

## 9. Зелёные ворота

- [x] 9.1 `make test` — зелёный, покрытие ≥ 80%
- [x] 9.2 `make validate` — линтер + форматтер + mypy(strict) без `# type: ignore`
