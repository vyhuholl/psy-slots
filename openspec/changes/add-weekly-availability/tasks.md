## 1. Доменная модель интервала

- [ ] 1.1 Тест: `AvailabilityInterval` создаётся с валидными полями (specialist_id, weekday 0–6, start_minute, end_minute) и неизменяем (падающий)
- [ ] 1.2 Тест: день недели вне 0–6 → доменная ошибка валидации
- [ ] 1.3 Тест: время вне пределов суток (0–1440) или начало ≥ конец → доменная ошибка валидации
- [ ] 1.4 Реализовать `app/domain/availability.py`: frozen `AvailabilityInterval`, валидация дня недели/границ/начало<конец, ошибки (`ValidationError`, `IntervalOverlap`)
- [ ] 1.5 Зелёные тесты 1.1–1.3

## 2. Таблица availability_intervals

- [ ] 2.1 Тест: раннер миграций создаёт `availability_intervals`; повторный прогон идемпотентен (падающий, сессия YDB замокана)
- [ ] 2.2 Добавить `CREATE TABLE IF NOT EXISTS availability_intervals (id, specialist_id, weekday, start_minute, end_minute)` в `app/migrations.py`
- [ ] 2.3 Зелёный тест 2.1

## 3. Доменный сервис

- [ ] 3.1 Тест: `add_interval(...)` создаёт строку с UUID; интервал появляется в `list(specialist_id)` (падающий, пул YDB и лукап специалиста замоканы)
- [ ] 3.2 Тест: `add_interval` для несуществующего специалиста → `SpecialistNotFound`, интервал не сохраняется
- [ ] 3.3 Тест: пересекающийся интервал в тот же день недели → `IntervalOverlap`, не сохраняется
- [ ] 3.4 Тест: смежный интервал (конец == начало соседнего) сохраняется успешно
- [ ] 3.5 Тест: `remove_interval(id)` убирает интервал из списка
- [ ] 3.6 Тест: `list(specialist_id)` возвращает пусто при отсутствии интервалов и не возвращает интервалы других специалистов
- [ ] 3.7 Реализовать `app/services/availability_service.py`: `add_interval`, `remove_interval`, `list`; проверка существования специалиста, проверка пересечений `[start,end)`, генерация `uuid4`, маппинг строка⇄модель
- [ ] 3.8 Зелёные тесты 3.1–3.6

## 4. Проверка и завершение

- [ ] 4.1 `make test` зелёный, покрытие ≥ 80%
- [ ] 4.2 `make validate` зелёный (ruff + format + mypy, без `# type: ignore`)