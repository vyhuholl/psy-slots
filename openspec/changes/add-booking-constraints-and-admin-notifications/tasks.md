## 1. Ограничение «одна активная бронь на клиента» (домен + сервис)

- [x] 1.1 Добавить доменную ошибку `ClientAlreadyBooked(BookingError)` в `app/domain/booking.py`
- [x] 1.2 Тест (падающий) в `tests/test_booking_service.py`: `create` для клиента с активной бронью → `ClientAlreadyBooked`, вторая строка не создана
- [x] 1.3 Тест: после `cancel` единственной активной брони `create` того же клиента проходит
- [x] 1.4 Тест: активная бронь другого клиента не мешает создать бронь этому клиенту
- [x] 1.5 Тест: конкурентное создание двух броней одним клиентом (эмуляция `Aborted`/lock invalidation) — ровно одна успешна, вторая — доменная ошибка
- [x] 1.6 Реализация: в `_insert(tx)` в `BookingService.create` добавить `SELECT` активных броней клиента (`status='booked' AND client_id=$client_id`) до `UPSERT`; при непустом результате — `raise ClientAlreadyBooked`. Проверку слота (`SlotTaken`) оставить первой
- [x] 1.7 Прогнать `make test` для booking_service — тесты 1.2–1.5 зелёные

## 2. Уведомление администратора о новой броне (клиентский хендлер)

- [x] 2.1 Тест (падающий) в `tests/test_client_handlers.py`: успешный `handle_confirm` шлёт админу (`ADMIN_TELEGRAM_ID`) «Пользователь <имя> забронировал слот на <диапазон>.» с именем из `resolve_client_name` и временем в `Europe/Moscow`
- [x] 2.2 Тест: сбой `send_message` админу (raise) не роняет хендлер, клиент всё равно получает подтверждение
- [x] 2.3 Тест: при отклонённом создании (`SlotTaken`/`ClientAlreadyBooked`) уведомление админу о новой броне НЕ отправляется
- [x] 2.4 Реализация: в `handle_confirm` после успешного `create` добавить блок уведомления админа (`resolve_client_name` + `format_slot_range`, `bot.send_message(config.admin_telegram_id, ...)` в `try/except: pass`) по образцу уведомления об отмене
- [x] 2.5 Реализация: обработать `ClientAlreadyBooked` в `handle_confirm` отдельным сообщением клиенту («можно иметь только одну активную запись»), отличным от «слот занят»
- [x] 2.6 Тест: `handle_confirm` при `ClientAlreadyBooked` шлёт клиенту сообщение об ограничении и не шлёт админу уведомление о брони

## 3. Напоминание администратору за 5 минут (reminder-сервис)

- [x] 3.1 Тест (падающий) в `tests/test_reminder_service.py`: при созревшем напоминании админу (`admin_telegram_id`) уходит «❗️ Через 5 минут начнётся сессия с пользователем <имя>» с именем из `resolve_client_name`
- [x] 3.2 Тест: сбой отправки админу не снимает claim и не приводит к повторной отправке клиенту; обработка остальных броней продолжается
- [x] 3.3 Тест: отменённые/прошедшие брони не порождают админского напоминания
- [x] 3.4 Реализация: добавить в `ReminderService.__init__` параметр `admin_telegram_id: int`
- [x] 3.5 Реализация: в `_try_send_reminder` после успешной отправки клиенту отправить админу (`resolve_client_name` + `send_message`) в отдельном `try/except`, логирующем ошибку и НЕ снимающем claim; поддержать sync/awaitable через `asyncio.run` как в `_send_reminder`

## 4. Проброс конфигурации в точку входа

- [x] 4.1 Тест (падающий/обновить) в `tests/test_notify.py`: `ReminderService` создаётся с `admin_telegram_id = config.admin_telegram_id`
- [x] 4.2 Реализация: в `app/notify.py` (`_get_reminder_service`) передать `config.admin_telegram_id` в `ReminderService`

## 5. Финальная проверка

- [x] 5.1 `make test` — все тесты зелёные, покрытие ≥ 80%
- [x] 5.2 `make validate` — линтер + форматтер + тайп-чекер без ошибок и без `# type: ignore`
- [x] 5.3 `openspec validate add-booking-constraints-and-admin-notifications --strict` — без ошибок
