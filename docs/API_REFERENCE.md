# Документація REST API (/api/v1)

Усі маршрути API згруповані за доменними областями та захищені за допомогою JWT Bearer токенів або HTTP-only Cookie.
Інтерактивна документація Swagger доступна за адресою: `http://localhost:8000/docs`.

---

## 1. Автентифікація (`/api/v1/auth`)

### `POST /auth/login`
- **Опис**: Вхід у систему, генерація токена.
- **Тіло запиту**:
```json
{
  "login": "superadmin",
  "password": "SuperAdminPass123!"
}
```
- **Відповідь (200 OK)**:
```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "user": {
    "id": 1,
    "login": "superadmin",
    "full_name": "Головний Системний Адміністратор",
    "is_superadmin": true,
    "roles": ["superadmin"],
    "permissions": ["generator:start", "system:adjust", "..."]
  }
}
```

### `GET /auth/me`
- **Опис**: Інформація про поточного авторизованого користувача та його дозволи.

### `POST /auth/logout`
- **Опис**: Вихід із системи, очищення сесійних cookies та запис в аудит.

---

## 2. Генератор (`/api/v1/generator`)

### `GET /generator`
- **Опис**: Отримання поточного стану, параметрів, накопичувальних мотогодин та рівня бака.

### `POST /generator/wizard`
- **Опис**: Майстер початкового налаштування параметрів та графіка.
- **Потрібен дозвіл**: `generator:configure`

### `POST /generator/start`
- **Опис**: Запуск генератора. Перевіряє графік роботи (Europe/Kyiv) та стан.
- **Потрібен дозвіл**: `generator:start`
- **Тіло запиту**: `{"fuel_level_l": 15.0}`

### `POST /generator/stop`
- **Опис**: Зупинка генератора. Розраховує тривалість та витрату палива.
- **Потрібен дозвіл**: `generator:stop`
- **Тіло запиту**: `{"end_hours": 104.5, "end_fuel_level_l": null, "note": "Планова зупинка"}`

### `GET /generator/runs`
- **Опис**: Історія запусків та зупинок генератора (query: `limit=50`).

---

## 3. Паливо (`/api/v1/fuel`)

### `GET /fuel/summary`
- **Опис**: Зведений баланс: склад ГСМ, бак, закуплено всього, витрати в грн, сер. вартість літра.

### `POST /fuel/receipt`
- **Опис**: Оприбуткування палива на склад ГСМ від бензовоза.
- **Потрібен дозвіл**: `fuel:receipt`
- **Тіло запиту**:
```json
{
  "liters": 100.0,
  "cost_total": 5800.0,
  "driver_name": "Коваленко О.В.",
  "receipt_number": "ЧЕК-12345",
  "fuel_type": "А-95"
}
```

### `POST /fuel/transfer`
- **Опис**: Заправка бака генератора зі складу ГСМ.
- **Потрібен дозвіл**: `fuel:transfer`
- **Тіло запиту**: `{"liters": 20.0, "comment": "Заправка перед роботою"}`

---

## 4. Технічне обслуговування (`/api/v1/maintenance`)

### `GET /maintenance/schedule`
- **Опис**: Поточний стан графіка регламентного ТО (інтервал, виконано, наступне, залишок мотогодин).

### `POST /maintenance/record`
- **Опис**: Фіксація проведеного ТО (регламентне або проміжне).
- **Потрібен дозвіл**: `maintenance:perform_scheduled` або `maintenance:create_intermediate`
- **Тіло запиту**:
```json
{
  "maintenance_type": "INTERMEDIATE",
  "work_description": "Заміна свічки запалювання",
  "consumables_used": "Свічка NGK",
  "cost": 350.0
}
```

---

## 5. Несправності (`/api/v1/faults`)

### `GET /faults`
- **Опис**: Список несправностей генератора (фільтр за статусом: `?status_filter=NEW`).

### `POST /faults`
- **Опис**: Реєстрація дефекту/аварії (пріоритети: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
- **Потрібен дозвіл**: `faults:create`

### `PUT /faults/{id}/status`
- **Опис**: Зміна статусу несправності (`NEW`, `ACCEPTED`, `IN_PROGRESS`, `PENDING`, `RESOLVED`, `CLOSED`).
- **Потрібен дозвіл**: `faults:manage`

---

## 6. Аудит та Системні коригування (`/api/v1/audit`, `/api/v1/adjustments`)

### `GET /audit`
- **Опис**: Журнал дій користувачів та системних подій.
- **Потрібен дозвіл**: `audit:view`

### `POST /adjustments`
- **Опис**: Ручне коригування мотогодин або залишків системним адміністратором.
- **Потрібен дозвіл**: **Тільки SuperAdmin** (`system:adjust`)
- **Тіло запиту**:
```json
{
  "entity_type": "Generator",
  "entity_id": 1,
  "field_name": "current_operating_hours",
  "new_value": "105.0",
  "reason": "Коригування за актом звірки лічильника №42"
}
```

---

## 7. Звітність (`/api/v1/reports`)

### `GET /reports/summary`
- **Опис**: Зведений аналітичний звіт за обраний період (`?start_date=2026-09-01&end_date=2026-10-01`).
- **Потрібен дозвіл**: `reports:view`

### `GET /reports/export`
- **Опис**: Завантаження звіту у форматі CSV з UTF-8 BOM для Excel.
- **Потрібен дозвіл**: `reports:export`
