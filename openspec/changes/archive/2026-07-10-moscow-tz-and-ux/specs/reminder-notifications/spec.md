## MODIFIED Requirements

### Requirement: Текст напоминания во времени получателя

Напоминание клиенту SHALL показывать время брони, сконвертированное из UTC в таймзону `Europe/Moscow`.

#### Scenario: Время в Europe/Moscow

- **WHEN** клиенту отправляется напоминание о брони
- **THEN** время в тексте отображается в `Europe/Moscow`, а не в UTC
