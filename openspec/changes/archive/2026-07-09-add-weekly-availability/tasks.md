## 1. Доменная модель интервала

- [x] 1.1 Тест: `AvailabilityInterval` создаётся с валидными полями (specialist_id, weekday 0–6, start_minute, end_minute) и неизменяем (падающий)
- [x] 1.2 Тест: день недели вне 0–6 → доменная ошибка валидации
- [x] 1.3 Тест: время вне пределов суток (0–1440) или начало ≥ конец → доменная ошибка валидации
- [x] 1.4 Реализовать `app/domain/availability.py`: frozen `AvailabilityInterval`, валидация дня недели/границ/начало<конец, ошибки (`ValidationError`, `IntervalOverlap`)
- [x] 1.5 Зелёные тесты 1.1–1.3

## 2. Таблица availability_intervals

- [x] 2.1 Тест: раннер миграций создаёт `availability_intervals`; повторный прогон идемпотентен (падающий, сессия YDB замокана)
- [x] 2.2 Добавить `CREATE TABLE IF NOT EXISTS availability_intervals (id, specialist_id, weekday, start_minute, end_minute)` в `app/migrations.py`
- [x] 2.3 Зелёный тест 2.1

## 3. Доменный сервис

- [x] 3.1 Тест: `add_interval(...)` создаёт строку с UUID; интервал появляется в `list(specialist_id)` (падающий, пул YDB и лукап специалиста замоканы)
- [x] 3.2 Тест: `add_interval` для несуществующего специалиста → `SpecialistNotFound`, интервал не сохраняется
- [x] 3.3 Тест: пересекающийся интервал в тот же день недели → `IntervalOverlap`, не сохраняется
- [x] 3.4 Тест: смежный интервал (конец == начало соседнего) сохраняется успешно
- [x] 3.5 Тест: `remove_interval(id)` убирает интервал из списка
- [x] 3.6 Тест: `list(specialist_id)` возвращает пусто при отсутствии интервалов и не возвращает интервалы других специалистов
- [x] 3.7 Реализовать `app/services/availability_service.py`: `add_interval`, `remove_interval`, `list`; проверка существования специалиста, проверка пересечений `[start,end)`, генерация `uuid4`, маппинг строка⇄модель
- [x] 3.8 Зелёные тесты 3.1–3.6

## 4. Проверка и завершение

- [x] 4.1 `make test` зелёный, покрытие ≥ 80%
- [x] 4.2 `make validate` зелёный (ruff + format + mypy, без `# type: ignore`)