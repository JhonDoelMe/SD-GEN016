# Змінні середовища та Конфігурація (Environment Variables)

**Версія документа:** 5.7.8 (Dual-Provider Alerts, FCM HTTP v1 Push, Branded Email & Production Hardening)  
**Дата набрання чинності:** 14 листопада 2026 року

Конфігурація системи **SD-GEN016 v5.7.8** розділена на два чітких рівні:
1. **Статичні інфраструктурні параметри** — зберігаються у файлі `.env` на сервері та зчитуються під час запуску бекенду (`backend/app/config.py`).
2. **Динамічні бізнес-налаштування (Runtime Settings)** — зберігаються в реляційній базі даних (таблиця `system_settings`), змінюються на льоту через веб-панель або REST API без перезавантаження сервісів.

---

## 1. Статичні змінні середовища (`.env`, `Settings`)

| Змінна | Призначення | Значення за замовчуванням | Рекомендації для Production |
|---|---|---|---|
| `APP_ENV` | Режим оточення додатку (`production`, `development`, `testing`) | `development` | Встановлювати `production` (включає Production Boot-Lock та HTTPS-захист) |
| `PRIMARY_DOMAIN` | Основний робочий домен системи (підставляється в Nginx, `/` та PWA) | `sdgen.pp.ua` | Ваш реальний робочий FQDN домен |
| `APP_SECRET_KEY` | Секретний ключ для підпису JWT токенів та RFC 8058 відписки (HMAC-SHA256) | `sd_gen016_default_secret_key_needs_override_32_chars` | Випадковий криптографічний ключ довжиною від 32 до 64 символів |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Час дії стандартного JWT токена доступу у хвилинах | `1440` (24 години) | Рекомендовано від `480` до `1440` (при `remember_me=True` — 60 діб) |
| `FACILITY_TIMEZONE` | Базовий часовий пояс додатку за замовчуванням | `Europe/Kyiv` | Залишати `Europe/Kyiv` |
| `INITIAL_ADMIN_LOGIN` | Логін первинного облікового запису SuperAdmin | `superadmin` | Змінити на унікальний логін організації |
| `INITIAL_ADMIN_PASSWORD` | Початковий пароль облікового запису SuperAdmin | `SuperAdminPass123!` | Складний пароль (від 12 символів, спецсимволи, цифри) |
| `INITIAL_ADMIN_EMAIL` | Контактний email системного адміністратора | `admin@facility.local` | Реальна робоча адреса відповідальної особи |
| `INITIAL_ADMIN_FULL_NAME` | ПІБ первинного системного адміністратора | `Головний Системний Адміністратор` | Реальне ПІБ відповідального адміністратора |
| `DATABASE_URL` | Асинхронний рядок з'єднання SQLAlchemy | `sqlite+aiosqlite:///./service_desk.db` | Для Docker/Production: `postgresql+asyncpg://sd_user:password@db:5432/sd_gen016` |
| `UPLOAD_DIR` | Каталог збереження файлів, чеків, дефектів та `.webp` аватарів | `./uploads` | Абсолютний шлях до постійного тому (наприклад, `/app/uploads`) |
| `BACKUP_DIR` | Каталог збереження локальних архівів резервних копій | `./backups` | Шлях до постійного тому резервних копій (наприклад, `/app/backups`) |
| `CORS_ORIGINS` | Дозволені джерела (Cross-Origin Resource Sharing) через кому | `""` (порожній; вмикає CORS для дев/APK) | Домен сайту та Capacitor-схеми (`https://sdgen.pp.ua,https://localhost,capacitor://localhost`) |
| `FORWARDED_ALLOW_IPS` | Довірені IP-адреси або підмережі проксі для Uvicorn | `127.0.0.1,172.16.0.0/12` | Безпечний список довірених проксі для Uvicorn |
| `ALLOWED_HOSTS` | Дозволені HTTP хости (`TrustedHostMiddleware`) | `""` (додає `PRIMARY_DOMAIN`) | Домен сайту та локальні адреси |
| `LOGIN_MAX_ATTEMPTS` | Максимум невдалих спроб логіну до тимчасового блокування (`auth_attempts`) | `5` | `5` спроб |
| `LOGIN_LOCKOUT_SECONDS` | Тривалість блокування при переборі пароля в секундах | `300` | `300` сек (5 хвилин) |
| `POSTGRES_USER` | Користувач бази даних PostgreSQL (для Docker Compose) | `sd_user` | Унікальне системне ім'я користувача СУБД |
| `POSTGRES_PASSWORD` | Пароль користувача бази даних PostgreSQL | `sd_password` | Складний згенерований пароль СУБД |
| `POSTGRES_DB` | Назва робочої бази даних PostgreSQL | `sd_gen016` | Найменування виробничої бази даних |
| `OPENWEATHER_API_KEY` | Ключ доступу до OpenWeatherMap API | `""` (пустий) | Робочий API-ключ OpenWeather для поточної погоди та 5-денного прогнозу |
| `WEATHER_CACHE_MINUTES` | Період кешування погодних даних у пам'яті | `20` | Інтервал від 10 до 30 хв |
| `ALERTS_IN_UA_TOKEN` | API-токен офіційного сервісу `alerts.in.ua` | `""` (пустий) | Провайдер №1 тривог (взаємна верифікація та типи загроз) |
| `UKRAINE_ALARM_API_KEY` | API-ключ сервісу `api.ukrainealarm.com` (Stfalcon / Ajax) | `""` (пустий) | Провайдер №2 тривог та страхування відбою |
| `ALERTS_CACHE_SECONDS` | Період кешування `alerts.in.ua` (із підтримкою HTTP 304) | `15` | Від 15 до 30 секунд |
| `UKRAINE_ALARM_CACHE_SECONDS` | Період глобального кешування запитів до `api.ukrainealarm.com` | `60` | Не менше `60` секунд згідно з лімітом API UkraineAlarm |
| `FIREBASE_SERVICE_ACCOUNT_PATH` | Шлях до JSON-ключа сервісного акаунта Firebase (FCM HTTP v1) | `/app/firebase/firebase-service-account.json` | Змонтований read-only файл `./docker/firebase/firebase-service-account.json` |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | Альтернативний спосіб передачі Firebase Service Account у вигляді JSON-рядка | `""` (пустий) | Використовувати у хмарних оточеннях без файлового монтування |

> [!IMPORTANT]
> **Незмінність пароля SuperAdmin при рестартах**:
> Параметри `INITIAL_ADMIN_*` зчитуються сервером **виключно під час першого запуску на порожній базі даних** для створення облікового запису SuperAdmin. Надалі зміна пароля здійснюється через інтерфейс користувача (`POST /api/v1/auth/change-password`) або адміністративне скидання. Навіть якщо змінити `INITIAL_ADMIN_PASSWORD` у `.env`, пароль у базі даних не перезапишеться, що захищає від випадкової втрати доступу.
>
> **Блокування запуску з дефолтними секретами у Production (`check_security_warnings`)**:
> При кожному старті система перевіряє значення `APP_SECRET_KEY` та `INITIAL_ADMIN_PASSWORD`. Якщо виявлено використання дефолтних або тестових значень у режимі `APP_ENV=production`, сервер негайно припиняє запуск із фатальною помилкою `RuntimeError` для захисту від випадкового розгортання вразливої конфігурації. У режимі `development` виводиться попередження високого пріоритету з вимогою заміни перед релізом.

---

## 2. Динамічні бізнес-налаштування в базі даних (Runtime Settings)

Бізнес-параметри винесені в базу даних (таблиця `system_settings`), що дає змогу змінювати їх у реальному часі через інтерфейс **«Адміністрування» -> «Системні налаштування»** без перезапуску сервісів:

- **`organization_name`**: Офіційне найменування організації або підприємства для друкованих форм, листів та звітів (наприклад, *«MAXI-UA LLC»*).
- **`facility_timezone`**: Робочий часовий пояс системи (за замовчуванням `Europe/Kyiv`, з автоматичним урахуванням літнього/зимового часу в Україні).
- **`work_schedule_start` / `work_schedule_end`**: Дозволений добовий інтервал роботи генераторів (наприклад, `08:00`–`20:00`).
- **`enforce_work_schedule` / `apply_to_all_generators`**: Суворий контроль графіка (`True/False`) та поширення на всі генератори мережі.
- **`login_max_attempts` / `login_lockout_seconds`**: Пороги захисту від підбору пароля в БД (`5` спроб / `300` сек).
- **`fuel_price_a95`, `fuel_price_a92`, `fuel_price_dp`, `internet_price_*`, `okko_price_*`, `wog_lineup`, `okko_lineup`**: Власні договірні ціни та живі/кешовані прайс-табло мереж АЗК WOG та OKKO.
- **`auto_fetch_fuel_prices`**: Прапорець фонового оновлення роздрібних цін мереж WOG та OKKO.
- **`default_maintenance_interval_hours`**: Стандартний інтервал регламентного ТО (за замовчуванням `300.0 год`).
- **`backup_last_auto_run_date`**: Системна дата останнього успішного автобекапу за розкладом (`YYYY-MM-DD`), яка виключає повторні хибні спрацювання планувальника при перезавантаженні контейнера.
- **`backup_auto_enabled`, `backup_schedule_time`, `backup_frequency`, `backup_retention_count`, `backup_default_type`**: Параметри автоматичного резервного копіювання за розкладом.
- **`default_facility_id`, `default_generator_id`, `default_fuel_stock_id`**: Стартовий ланцюжок за замовчуванням (`Об'єкт ➔ Генератор ➔ Склад ГСМ`).
- **`max_continuous_run_hours`, `auto_stop_on_schedule_end`, `notify_running_heartbeat`, `heartbeat_interval_hours`**: Параметри операційних запобіжників (`12.0 год`, автостоп після зміни, пульс-нагадування кожні `4.0 год`).
- **`fuel_receipt_max_liters_warning`, `fuel_receipt_min_price`, `fuel_receipt_max_price`**: Поріг контролю аномальних чеків (`1000.0 л`, `15.0–250.0 грн/л`).
- **`notifications_enabled`, `notify_generator_start`, `notify_generator_stop`, `notify_low_fuel`, `low_fuel_threshold_l`, `notify_maintenance`, `max_maintenance_notifications_per_day`, `notify_critical_faults`, `notify_outside_schedule`, `notify_yasno_outages`, `notify_air_alerts`, `notify_air_alert_end`, `vapid_claims_sub`**: Правила Web Push / Android FCM / Центру сповіщень (включно з тривогами, відбоями, роботою поза графіком та відключеннями YASNO).
- **`smtp_enabled`, `smtp_primary_*`, `smtp_fallback_*`, `email_notify_password_change`, `email_notify_safety_stop`, `email_notify_empty_tank`, `email_notify_low_fuel`, `email_notify_outside_schedule`, `email_notify_critical_fault`, `email_notify_maintenance_due`, `email_weekly_report_enabled`, `email_weekly_recipients`, `email_weekly_send_day`, `email_weekly_send_time`, `email_weekly_facility_id`, `email_weekly_generator_id`, `last_weekly_digest_date`**: Конфігурація SMTP Failover (Gmail / Ukr.net), тригерів оперативних листів та щотижневої розсилки 6-аркушевого Excel-дайджесту.

---

## 3. Рекомендації з безпеки для Production (v4.2 Hardened)

1. **Заборона зберігання `.env` та SSL-ключів у репозиторії**:
   - Файл `.env`, а також приватні ключі `docker/ssl/*.pem` та `docker/ssl-fallback/*.pem` внесені до `.gitignore`.
   - Вбудований fallback у `docker-compose.yml` генерує тимчасовий self-signed сертифікат на льоту, якщо користувацькі сертифікати не змонтовані.
2. **Права доступу на сервері Linux/Docker**:
   ```bash
   chmod 600 .env
   chown root:root .env
   ```
3. **Генерація безпечного APP_SECRET_KEY**:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(64))"
   ```
4. **Обмеження довірених проксі у Dockerfile**:
   - Запуск Uvicorn налаштовано з прапорцем:
     `--forwarded-allow-ips='127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16'`
   - Це запобігає маніпуляціям заголовками `X-Forwarded-*` з публічних зовнішніх мереж.
5. **Маскування у бекапах**:
   - При формуванні резервної копії файл `.env` автоматично знеособлюється (паролі замінюються на `***REDACTED***`).
