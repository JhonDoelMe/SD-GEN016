# Релізні нотатки SD-GEN016 v5.7.4 (`14 листопада 2026 року`)

Версія **v5.7.4** консолідує всі продуктові, інфраструктурні й інтерфейсні зміни покоління `v5.4.1–v5.7.3` та проводить повну синхронізацію вбудованих політик у продукті (`frontend/views/modals-legal.html`), метаданих API (`backend/app/main.py`) і всієї проєктної документації (`docs/`, `README.md`, `AGENT.md`, `CHANGELOG.md`).

---

## 🚀 Ключові нововведення покоління `v5.5.0 – v5.7.4`

### 1. Справжній Offline-режим PWA (`IndexedDB` + Ідемпотентність, `v5.5.0`)
- Локальне сховище `sd_gen016_offline` (`read_cache` + `mutation_queue` у [`frontend/js/offline-queue.js`](frontend/js/offline-queue.js)) для перегляду об'єктів та виконання операцій без зв'язку.
- Серверна таблиця `idempotency_records` (міграція [`012_offline_idempotency.py`](backend/alembic/versions/012_offline_idempotency.py)) з перевіркою `Idempotency-Key` + SHA-256 тіла запиту (`X-Idempotency-Replayed: true`, `HTTP 409 Conflict`) та модальним ручним вирішенням конфліктів (`#modalOfflineQueue`).

### 2. Режим вимірювання витрат палива («від повного до повного», `v5.6.0–v5.6.1`)
- Таблиця `fuel_measurements` (міграція [`013_fuel_measurements.py`](backend/alembic/versions/013_fuel_measurements.py)) із машиною станів `MEASURING → PENDING_INVENTORY → PENDING_APPROVAL → APPROVED / CANCELLED`.
- Старт (`SuperAdmin`) при зупиненому генераторі й 100% повному баку, фіксація заливки мінімум 100 л (`POST /api/v1/measurement/{id}/finish-full`), безперебійний допуск `start`/`stop`/`manual-run` при блекауті, інвентаризація комісією (≥ 3 особи), генерація **PDF А4 альбомного формату** (`fpdf2`) та **6-й аркуш Excel** «Заміри та інвентаризація».

### 3. Пули каністр (`CanisterPool`) та єдиний блок запасу палива (`v5.4.2–v5.4.4`)
- Поштучний облік тари (`011_canister_pools.py`) із першочерговим списанням наземної резервної ємності (`reserve_liters < canister_volume_l`), уніфікованою формою прийому палива та єдиною панеллю оцінки запасу на дашборді (`#fuelAssessmentPanel`).

### 4. Android Capacitor APK, OTA-сервер (`/ota/`) та Firebase Cloud Messaging (`v5.6.3–v5.6.6`)
- Підписаний мобільний додаток Android (`android/`) з Edge-to-Edge `WindowInsets`.
- Автономний FastAPI сервіс оновлень [`ota-server/`](ota-server/) за проксі `/ota/` із клієнтським модулем [`ota-updater.js`](frontend/js/ota-updater.js).
- Нативні мобільні push-сповіщення через **FCM HTTP v1** (`fcm_service.py`) паралельно з браузерним Web Push (`VAPID`).

### 5. Модульний Service Desk інтерфейс та Профілі користувачів з аватарами (`v5.6.7–v5.6.10`)
- Фронтенд реорганізовано у **14 HTML-фрагментів** (`frontend/views/`), **16 ES-модулів** (`frontend/js/`) та **4 таблиці стилів** (`frontend/css/`) зі sticky-шапкою, бічним меню навігації (`Drawer`) та кнопкою оновлення кешу PWA.
- Особистий профіль користувача та `.webp` аватари (`014_user_avatar.py`, [`avatar_service.py`](backend/app/services/avatar_service.py)) із захищеним роутом `/uploads/avatars/*`.

### 6. Центр сповіщень (`🔔`), Фірмові Email + 1-Click відписка та Повна українізація аудиту (`v5.7.0–v5.7.3`)
- Верхній дзвоник `#headerBellBtn` із лічильником непрочитаних повідомлень (`notification_reads`) та паралельною синхронізацією (`v5.7.1`).
- Фірмовий адаптивний HTML-шаблон листів із круглим логотипом продукту та заголовками **RFC 8058** (`List-Unsubscribe`, `/api/v1/email/unsubscribe`, `/resubscribe`).
- Повна українізація назв дій, сутностей та деталей операцій у журналі аудиту й 2-аркушевому Excel-експорті.

### 7. Синхронізація документації, політик та виправлення Bump-скрипта (`v5.7.4`)
- Оновлено 4 вбудовані модальні документи у [`frontend/views/modals-legal.html`](frontend/views/modals-legal.html) та опис FastAPI у [`backend/app/main.py`](backend/app/main.py).
- Виправлено [`scripts/bump-version.js`](scripts/bump-version.js) для автоматичного оновлення мітки версії у футері навігаційного меню (`frontend/index.html`).
- Оновлено всі **13 файлів** у `docs/`, [`README.md`](README.md), [`AGENT.md`](AGENT.md) та [`CHANGELOG.md`](CHANGELOG.md).

---

## 🧪 Верифікація
- **Backend (`backend/tests/`):** `193` тести, 100% успіх.
- **OTA Server (`ota-server/tests/`):** `3` тести, 100% успіх.
