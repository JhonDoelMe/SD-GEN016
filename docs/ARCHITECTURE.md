# Архітектура системи: Service Desk Генератора (SD-GEN016)

**Версія архітектури:** 5.7.4 (Modular Service Desk UI, Offline IndexedDB Queue, Measurement Mode, Android APK/OTA, FCM HTTP v1, Notification Bell, Branded Email & Full UA Audit)  
**Дата оновлення:** 14 листопада 2026 року  
**Розробник комплексу:** ТОВ «МАКСІ-ЮА» (MAXI-UA LLC)  

---

## 1. Загальний огляд системи

Програмний комплекс **SD-GEN016** спроектовано як високопродуктивну, відмовостійку, модульну багаторівневу систему промислового класу для оперативного обліку фактичної експлуатації бензинових та дизельних генераторів критичної інфраструктури (АЗС, склади, медичні заклади, філії, автономні виробництва).

Система працює за гібридною напівавтоматичною моделлю (онлайн + офлайн): оператор або сервісний технік фіксує фактичні події (пуск, стоп, прийом/переміщення палива, рух каністр, ТО, дефекти), а бекенд-сервіси забезпечують валідацію, ідемпотентність, криптографічну безпеку, сувору ізоляцію об'єктів (Варіант Б), захист інваріантів мотогодин і паливних залишків, повністю українізований незмінний аудит, багатоканальні сповіщення (Web Push, Android FCM, Центр сповіщень `🔔`, Email з 1-click відпискою RFC 8058) та звітність за стандартами **ДСТУ 4163:2020**.

---

## 2. Діаграма архітектурних рівнів (High-Level Architecture)

```
+------------------------------------------------------------------------------------+
|                                    КЛІЄНТИ                                         |
|  - ПК та смартфони (Chrome, Edge, Firefox, Safari) — Модульний UI (14 views/16 js) |
|  - Встановлений автономний PWA додаток (Standalone PWA v5.7.4 + IndexedDB Offline) |
|  - Нативний мобільний клієнт Android APK (Capacitor + FCM HTTP v1 + OTA Updater)   |
|  - Live Browser Watcher + pushsubscriptionchange + Центр сповіщень («🔔»)         |
+------------------------------------------------------------------------------------+
                                          │
                                          ▼ HTTPS / TLS 1.2–1.3
+------------------------------------------------------------------------------------+
|                                NGINX REVERSE PROXY                                 |
|  - Термінація SSL/TLS (користувацькі сертифікати або автогенерація fallback)       |
|  - Gzip (level 5) + кешування версіонованої статики /frontend/ (max-age=604800)    |
|  - Повна заборона кешування Service Worker (sw.js)                                 |
|  - Проксі /ota/ -> ota_server (порт 8090) для дистрибуції та оновлення Android APK |
|  - Заголовки безпеки (HSTS, CSP, X-Frame-Options: DENY, Referrer-Policy)           |
|  - Обмеження тіла запитів (client_max_body_size 100M для бекапів та APK)           |
|  - Передача надійного IP-клієнта (X-Real-IP)                                       |
+------------------------------------------------------------------------------------+
                                          │
                                          ▼ Внутрішня мережа Docker (порт 8000)
+------------------------------------------------------------------------------------+
|                        BACKEND (FastAPI / Python 3.14+ / ASGI)                     |
|                                                                                    |
|  +-------------------------------------------------------------------------------+ |
|  |                         15 API ROUTERS (/api/v1)                              | |
|  |  /auth         - Логін, профіль, .webp аватар, зміна/скидання пароля, logout  | |
|  |  /users        - Список ролей/юзерів, CRUD (SuperAdmin), керування аватарами  | |
|  |  /facilities   - Об'єкти, YASNO, OpenWeather 5-day, Dual-Provider Alerts      | |
|  |  /generator    - Генератори, архів, перенесення, reconcile, пакетний cooldown | |
|  |  /fuel         - Склади, чеки (WOG/OKKO/інше), заправки, пули каністр         | |
|  |  /maintenance  - Регламентне та проміжне ТО, графіки, перерахунок              | |
|  |  /faults       - Журнал аварій та дефектів, автостоп при CRITICAL             | |
|  |  /measurement  - Режим вимірювання витрат «від повного до повного», PDF А4    | |
|  |  /notifications- Web Push VAPID, Android FCM v1, налаштування, 🔔 feed/read   | |
|  |  /email        - Публічна 1-click відписка/поновлення розсилки (RFC 8058)     | |
|  |  /backups      - Бекап-центр (маскування секретів, Zip Slip/Bomb, SHA-256)    | |
|  |  /system       - Динамічні налаштування, парсер WOG/OKKO, SMTP, Clean DB      | |
|  |  /adjustments  - Офіційні системні коригування залишків та пулів каністр      | |
|  |  /audit        - Незмінний українізований аудит + SuperAdmin Excel експорт    | |
|  |  /reports      - Зведення показників, експорт 6-сторінкового Excel (.xlsx)    | |
|  +-------------------------------------------------------------------------------+ |
|                                         │                                          |
|  +-------------------------------------------------------------------------------+ |
|  |                              SECURITY & MIDDLEWARE                            | |
|  |  - Fail-Closed SMTP TLS: обов'язкове STARTTLS, відмова від відкритого логіну| |
|  |  - Audit Log Redaction: sanitize_audit_details + startup historical scrub   | |
|  |  - Production Boot-Lock: фатальна помилка при дефолтних секретах у production| |
|  |  - Strict Multi-site Lockdown: 403 Forbidden для незакріплених операторів    | |
|  |  - Auth Protected Media (/uploads/*): перевірка JWT та revoked_tokens у БД    | |
|  |  - Persistent Security (010): revoked_tokens & auth_attempts у PostgreSQL     | |
|  |  - Idempotency Guard (012): idempotency_records + SHA-256 перевірка payload   | |
|  |  - Dual-Key Rate Limiter & X-Forwarded-For Anti-Spoofing                      | |
|  |  - Web Push SSRF Allowlist & RFC 8058 HMAC Email Unsubscribe Tokens           | |
|  |  - Захист від SQLi (SQLAlchemy ORM), XSS (escapeHtml), Formula Injection      | |
|  +-------------------------------------------------------------------------------+ |
|                                         │                                          |
|  +-------------------------------------------------------------------------------+ |
|  |                            22 БІЗНЕС-СЕРВІСИ                                  | |
|  |  Facility, Generator, Fuel, Canister, Measurement, Idempotency, Avatar,       | |
|  |  OperationalGuard, Email, FCM, Notification, Weather, Alert, Yasno,           | |
|  |  Maintenance, Fault, Backup, Settings, Report (6 аркушів), Audit (UA),        | |
|  |  AuthSecurity, InitService (25 RBAC дозволів)                                 | |
|  +-------------------------------------------------------------------------------+ |
|                                         │                                          |
|  +-------------------------------------------------------------------------------+ |
|  |                           ORM & DATABASE ACCESS                               | |
|  |  SQLAlchemy 2.0 (AsyncSession) + Alembic Migrations (001–014)                 | |
|  +-------------------------------------------------------------------------------+ |
+------------------------------------------------------------------------------------+
                                          │
                                          ▼
+------------------------------------------------------------------------------------+
|                                    БАЗА ДАНИХ                                      |
|  - Розробка / Тестування: SQLite (aiosqlite)                                       |
|  - Виробниче середовище (Production / VPS): PostgreSQL 16 (asyncpg)                |
+------------------------------------------------------------------------------------+
```

---

## 3. Сутності та реляційні зв'язки (ORM Data Models)

1. **Facility (`facilities`)**: об'єкт інфраструктури (філія, АЗС, склад, медичний пункт) із власною адресою, часовим поясом, основною закріпленою мережею АЗС (`default_fuel_provider`: WOG або OKKO), реквізитами графіків YASNO та прив'язаними ресурсами.
2. **User (`users`)**: обліковий запис співробітника, що має прив'язку до об'єкта (`facility_id`), хеш пароля, статус активності та зв'язок з ролями.
3. **Generator (`generators`)**: генераторна установка, прив'язана до об'єкта (`facility_id`), із зазначенням місткості бака, нормативного розходу, потужності, поточних накопичувальних мотогодин та статусу.
4. **GeneratorRun (`generator_runs`)**: історія сеансів роботи (пуск, стоп, тривалість у секундах, початкові/кінцеві мотогодини, розрахунковий розхід палива, оператор).
5. **GeneratorSchedule (`generator_schedules`)**: добовий графік дозволеного часу запуску (наприклад 08:00–20:00 у зоні `Europe/Kyiv`).
6. **FuelStock (`fuel_stocks`)**: склад або резервуар палива, обов'язково закріплений за об'єктом (`facility_id`).
7. **FuelReceipt (`fuel_receipts`)**: надходження палива за чеком/накладною на конкретний склад із фіксацією мережі АЗС (`fuel_provider`: WOG або OKKO), водія та накладної.
8. **FuelTransfer (`fuel_transfers`)**: внутрішнє переміщення (заправка бака генератора зі складу того ж самого об'єкта).
9. **MaintenanceSchedule (`maintenance_schedules`)**: регламентний інтервал ТО генератора та контрольні лічильники напрацювання.
10. **MaintenanceRecord (`maintenance_records`)**: журнал проведеного обслуговування (регламентне або проміжне).
11. **Fault (`faults`)**: інциденти та дефекти обладнання.
12. **PushSubscription (`push_subscriptions`), FcmSubscription (`fcm_subscriptions`), NotificationLog (`notification_logs`) та NotificationRead (`notification_reads`)**: підписки Web Push (VAPID) і Android FCM, журнал сповіщень та персональні відмітки прочитання в Центрі сповіщень (`🔔`).
13. **CanisterPool (`canister_pools`) та CanisterTransaction (`canister_transactions`)**: поштучний облік пулів каністр об'єктів, резервна ємність та аудит переміщень тари (міграція `011`).
14. **IdempotencyRecord (`idempotency_records`)**: реєстр ідемпотентних записів для безпечної офлайн-синхронізації без дублювання (міграція `012`).
15. **FuelMeasurement (`fuel_measurements`)**: життєвий цикл вимірювання витрат палива «від повного до повного» та комісійних інвентаризацій (міграція `013`).
16. **AuditLog (`audit_logs`)**, **SystemAdjustment (`system_adjustments`)**, **PasswordResetToken (`password_resets`)**, **RevokedToken (`revoked_tokens`)**, **AuthAttempt (`auth_attempts`)**: незмінні реєстри українізованого аудиту, коригувань, відновлення паролів та персистентної безпеки (`010`).
17. **Міграції Alembic (`001`–`014`)**: включаючи `010_security_persistence`, `011_canister_pools`, `012_offline_idempotency`, `013_fuel_measurements` та `014_user_avatar` (`User.avatar_url` + `.webp` аватари).

## 4. Фонові служби, інтеграції та оптимізації продуктивності (v5.7.4)

- **`settings_service.py` (парсери WOG/OKKO)**: асинхронні `httpx` парсери роздрібних цін мереж WOG та OKKO з автоматичним фоновим кешуванням (TTL 12 годин), ручним оновленням через API та аварійним Fallback-кешем.
- **`backup_service.py` та `run_backup_scheduler`**: автобекапи із 15-хвилинним вікном (`0 <= diff_minutes <= 15`) та `backup_last_auto_run_date`, контрольними сумами `.sha256` та pre-restore snapshot.
- **`operational_guard_service.py` (`run_operational_guard_loop`)**: контроль 12-годинного безперервного прогону, автостоп наприкінці зміни, 4-годинне пульс-нагадування, живий моніторинг низького палива й наближення ТО (із урахуванням режиму заміру палива).
- **`yasno_service.py` та `run_yasno_checker_loop`**: графіки відключень YASNO (`15 хв` кеш), блок «Паливо в баку ↔ YASNO» у всіх станах і сповіщення за 20–35 хв.
- **`alert_service.py` та `run_air_alert_checker_loop`**: паралельний dual-provider моніторинг (`alerts.in.ua` HTTP 304 + `api.ukrainealarm.com` 60s кеш), Worst-Case Hold, переходи `GREEN ↔ YELLOW/RED` кожні 45 с.
- **`weather_service.py`**: поточна погода + 5-денний прогноз OpenWeatherMap (`20 хв` кеш) та проактивні заморозкові рекомендації для ДП.
- **`fcm_service.py`, `email_service.py`, `notification_service.py`**: мультиканальна доставка (Web Push VAPID, Firebase Cloud Messaging HTTP v1 для Android APK, фірмові HTML-листи з RFC 8058 1-click відпискою).
- **Модульний фронтенд & Продуктивність (`frontend/views/`, `frontend/css/`, `frontend/js/`)**: 14 HTML-парціалів, 4 CSS-файли, 16 JS-модулів, динамічний `view-loader.js`, паралелізація API (`Promise.all`), пакетний cooldown (`get_generators_cooldown_map`), `bcrypt` у `asyncio.to_thread`, Gzip + кеш Nginx, пагінація по 10 записів.
- **Експорт звітності та аудиту**: `GET /api/v1/reports/export-excel` формує **6-аркушеву книгу Excel** (вкл. «Заміри та інвентаризація»); `GET /api/v1/audit/export-excel` (SuperAdmin) формує окремий **2-аркушевий українізований звіт** («Журнал дій аудиту» та «Системні коригування»).

---

## 5. Безпека інфраструктури, Контейнеризація та OTA-дистрибуція Android APK

1. **Непривілейований режим (Non-root user `appuser`)**:
   - Контейнер виконується під виділеним непривілейованим системним користувачем `appuser` (UID: 10001, GID: 10001);
   - Каталоги з вихідним кодом бекенду (`/app/backend`) монтуються без прав запису для процесів додатку;
   - Права на запис обмежені робочими підкаталогами сховищ: `/app/data`, `/app/uploads` (включно з `avatars/`), `/app/backups`, `/app/alembic/versions`; секрети Firebase монтуються read-only у `/app/firebase`.
2. **Graceful Process Management (`exec uvicorn`)**:
   - Точка входу `docker-entrypoint.sh` заміщує процес оболонки через `exec uvicorn`, коректно обробляючи `SIGTERM`/`SIGINT`.
3. **Двоетапні Healthcheck-зонди**:
   - `/api/health/liveness` (та `/health/live`) і `/api/health/readiness` (та `/health/ready`, `/api/health`).
4. **Автономний OTA-сервер (`ota-server/`) та Android APK (`android/`)**:
   - Підписаний Capacitor APK взаємодіє з Nginx `/api/` та перевіряє оновлення через проксі `/ota/api/latest` (`ota-updater.js`);
   - На сервері розгорнуто ізольований FastAPI сервіс [`ota-server/`](../ota-server/app.py) на порту `8090` (`upstream ota_server` у `docker/nginx.conf`), який віддає APK-білди, метадані версій (`version_code`, `force_update`) та адмін-панель релізів `/ota/admin` (доступ до адмін-API захищено токеном `OTA_ADMIN_TOKEN`).

---

## 6. Автономна робота PWA та синхронізація конфліктів (Етап 4)

1. **Офлайн-сховище (`IndexedDB` `sd_gen016_offline_db`)**:
   - Таблиця `read_cache` зберігає останні успішні відповіді ключових довідникових та станових GET-запитів (`/auth/me`, `/facilities`, `/generator*`, `/fuel/*`, `/maintenance/schedule`), забезпечуючи роботу інтерфейсу при зникненні зв'язку чи повторному запуску PWA без мережі.
   - Таблиця `mutation_queue` зберігає офлайн-операції у порядку створення (`created_at`) з унікальним `idempotency_key` (`UUID`) та оптимістично оновлює локальний кеш.
2. **Ідемпотентність бекенду (`idempotency_records`, Alembic `012`)**:
   - Усі підтримувані офлайн-ендпоінти приймають `idempotency_key` (у тілі JSON або в заголовку `Idempotency-Key`), зберігають серіалізований результат і SHA-256 хеш запиту та повертають збережену відповідь при повторі без дублювання транзакцій (або `HTTP 409` при підміні параметрів).
3. **Ручне вирішення конфліктів (`#modalOfflineQueue`)**:
   - Якщо під час фонової або ручної синхронізації сервер відхиляє операцію через зміну стану (`HTTP 400/404/409/422`), запис переходить у статус `conflict` без блокування інших операцій у черзі.
   - Оператор бачить точну причину відмови, актуальний стан об'єкта із сервера і може вручну відредагувати параметри (з новим `idempotency_key`), повторити запит або відхилити застарілу дію.

---

## 7. Контрольний замір витрат палива («від повного до повного») та PDF-інвентаризація (v5.6.1)

1. **Машина станів (`FuelMeasurement`, Alembic `013`)**:
   - Таблиця `fuel_measurements` зберігає повний життєвий цикл контрольного заміру на рівні `(facility_id, generator_id)`: `MEASURING` → `PENDING_INVENTORY` → `PENDING_APPROVAL` → `APPROVED` (або `CANCELLED` через аварійне скасування SuperAdmin).
2. **Сервісний захист інваріантів (`measurement_service.py`)**:
   - Під час `MEASURING` лічильник підраховує виключно заправки в бак (допускаючи долив до `tank_capacity_l`), придушуються сповіщення низького залишку/розбіжності пального (`allow_system_clamp=True`), а ручні корекції паливного обліку й норми витрати відхиляються (`HTTP 423`).
   - Під час `PENDING_INVENTORY` та `PENDING_APPROVAL` функція `ensure_facility_not_locked_by_measurement()` **залишає розблокованим `generator_run` (`start`/`stop`/`manual-run`)** для безперебійної роботи при блекаутах і опечатує (`HTTP 423`) лише операції зі складом ГСМ, дозаправки, каністри та коригування.
3. **Авторозрахунок каністр, А4 Landscape PDF та звітності (`fpdf2` + кириличний TTF + Excel 6-й аркуш)**:
   - Внесений комісією залишок складу автоматично розкладається функцією `compute_stock_canister_breakdown()` на повні каністри та резерв, формує незмінну PDF-відомість А4 альбомної орієнтації (`fonts-dejavu-core` у Docker/CI); при погодженні оновлюються норма й залишки без перезапису проміжної роботи генератора, а підсумки потрапляють у звіти й 6-й аркуш Excel («Заміри та інвентаризація»).
