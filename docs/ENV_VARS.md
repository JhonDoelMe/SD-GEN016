# Змінні середовища та Конфігурація (Environment Variables)

**Версія документа:** 5.4.0 (Dual-Provider Alert Fusion, WebPush Alerts, Weather & Security Hardening)  
**Дата набрання чинності:** 11 листопада 2026 року

Конфігурація системи **SD-GEN016 v5.4.0** розділена на два чітких рівні:
1. **Статичні інфраструктурні параметри** — зберігаються у файлі `.env` на сервері та зчитуються під час запуску бекенду (підключення до БД, секрети шифрування, базові системні шляхи).
2. **Динамічні бізнес-налаштування (Runtime Settings)** — зберігаються в реляційній базі даних (таблиця `system_settings`), змінюються на льоту через веб-панель або REST API без потреби перезавантаження контейнерів або сервісів.

---

## 1. Статичні змінні середовища (`.env`)

| Змінна | Призначення | Значення за замовчуванням | Рекомендації для Production |
|---|---|---|---|
| `APP_ENV` | Режим оточення додатку (`production`, `development`) | `production` | Встановлювати `production` для блокування налагоджувальних деталей |
| `PRIMARY_DOMAIN` | Основний робочий домен системи (підставляється в Nginx та PWA) | `sdgen.pp.ua` | Ваш реальний робочий FQDN домен |
| `APP_SECRET_KEY` | Секретний ключ для підпису JWT токенів та сесій (HMAC-SHA256) | `change_this_to_a_secure_random_secret_key...` | Випадковий криптографічний ключ довжиною від 32 до 64 символів |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Час дії JWT токена доступу у хвилинах | `1440` (24 години) | Рекомендовано від `480` (8 годин) до `1440` (доба) |
| `INITIAL_ADMIN_LOGIN` | Логін первинного облікового запису SuperAdmin | `superadmin` | Змінити на унікальний логін організації |
| `INITIAL_ADMIN_PASSWORD` | Початковий пароль облікового запису SuperAdmin | `SuperAdminSecretPass123!` | Складний пароль (від 12 символів, спецсимволи, цифри) |
| `INITIAL_ADMIN_EMAIL` | Контактний email системного адміністратора | `admin@example.com` | Реальна робоча адреса відповідальної особи |
| `INITIAL_ADMIN_FULL_NAME` | ПІБ первинного системного адміністратора | `Головний Системний Адміністратор` | Реальне ПІБ відповідального адміністратора |
| `DATABASE_URL` | Асинхронний рядок з'єднання SQLAlchemy | `sqlite+aiosqlite:///./service_desk.db` | Для Docker/Production: `postgresql+asyncpg://sd_user:password@db:5432/sd_gen016` |
| `UPLOAD_DIR` | Каталог для збереження файлів, чеків та фото дефектів | `./uploads` | Абсолютний шлях до постійного тому (наприклад, `/app/uploads`) |
| `BACKUP_DIR` | Каталог збереження локальних архівів резервних копій | `./backups` | Шлях до постійного тому резервних копій (наприклад, `/app/backups`) |
| `CORS_ORIGINS` | Дозволені джерела (Cross-Origin Resource Sharing) | `http://localhost:8000,http://127.0.0.1:8000` | Реальний домен сайту, наприклад `https://gen.mycompany.ua` |
| `FORWARDED_ALLOW_IPS` | Довірені IP-адреси або підмережі зворотних проксі (Nginx/Docker) для передачі клієнтських IP | `127.0.0.1,172.16.0.0/12` | Безпечний список довірених проксі для Uvicorn |
| `ALLOWED_HOSTS` | Дозволені HTTP хости (TrustedHostMiddleware) | `localhost,127.0.0.1` | Домен сайту та локальні адреси |
| `POSTGRES_USER` | Користувач бази даних PostgreSQL (для Docker Compose) | `sd_user` | Унікальне системне ім'я користувача СУБД |
| `POSTGRES_PASSWORD` | Пароль користувача бази даних PostgreSQL | `sd_password` | Складний згенерований пароль СУБД |
| `POSTGRES_DB` | Назва робочої бази даних PostgreSQL | `sd_gen016` | Найменування виробничої бази даних |
| `OPENWEATHER_API_KEY` | Ключ доступу до OpenWeatherMap API | `""` (пустий) | Робочий API-ключ OpenWeather для поточної погоди та 5-денного прогнозу |
| `WEATHER_CACHE_MINUTES` | Період кешування погодних даних у пам'яті | `20` | Інтервал від 10 до 30 хв для мінімізації запитів |
| `ALERTS_IN_UA_TOKEN` | API-токен офіційного сервісу alerts.in.ua | `""` (пустий) | Провайдер №1 тривог (паралельна взаємна верифікація та типи ракетних/БПЛА загроз) |
| `UKRAINE_ALARM_API_KEY` | API-ключ сервісу api.ukrainealarm.com (Stfalcon / Ajax) | `""` (пустий) | Провайдер №2 тривог (паралельна взаємна верифікація сирен ДСНС та страхування відбою) |
| `ALERTS_CACHE_SECONDS` | Період кешування статусу тривог (та глобального кешу alerts.in.ua) | `15` | Від 15 до 30 секунд (з підтримкою HTTP 304 `If-Modified-Since`) |
| `UKRAINE_ALARM_CACHE_SECONDS` | Період глобального кешування запитів до api.ukrainealarm.com | `60` | Не менше `60` секунд згідно з лімітом 1 запит/хв API UkraineAlarm |

> [!IMPORTANT]
> **Незмінність пароля SuperAdmin при рестартах**:
> Параметри `INITIAL_ADMIN_*` зчитуються сервером **виключно під час першого запуску на порожній базі даних** для створення облікового запису SuperAdmin. Надалі зміна пароля здійснюється через інтерфейс користувача (`POST /api/v1/auth/change-password`) або адміністративне скидання. Навіть якщо змінити `INITIAL_ADMIN_PASSWORD` у `.env`, пароль у базі даних не перезапишеться, що захищає від випадкової втрати доступу.
>
> **Блокування запуску з дефолтними секретами у Production (`check_security_warnings`)**:
> При кожному старті система перевіряє значення `APP_SECRET_KEY` та `INITIAL_ADMIN_PASSWORD`. Якщо виявлено використання дефолтних або тестових значень у режимі `APP_ENV=production`, сервер негайно припиняє запуск із фатальною помилкою `RuntimeError` для захисту від випадкового розгортання вразливої конфігурації. У режимі `development` виводиться попередження високого пріоритету з вимогою заміни перед релізом.

---

## 2. Динамічні бізнес-налаштування в базі даних (Runtime Settings)

Бізнес-параметри винесені в базу даних (таблиця `system_settings`), що дає змогу змінювати їх у реальному часі через інтерфейс **«Адміністрування» -> «Системні налаштування»** без перезапуску сервісів:

- **`organization_name`**: Офіційне найменування організації або підприємства для друкованих форм і звітів (наприклад, *«ТОВ „Енерго-Резерв Захід“»*).
- **`facility_timezone`**: Робочий часовий пояс системи (за замовчуванням `Europe/Kyiv`, з автоматичним урахуванням літнього/зимового часу в Україні).
- **`work_schedule_start` / `work_schedule_end`**: Дозволений добовий інтервал роботи генераторів (наприклад, `08:00`–`20:00`).
- **`enforce_work_schedule`**: Прапорець суворого контролю дотримання графіка (True/False).
- **`fuel_price_wog_a95`, `fuel_price_wog_dp`, `fuel_price_okko_a95`, `fuel_price_okko_dp` (та базові `fuel_price_*`)**: Власні договірні ціни на пальне для мереж WOG та OKKO (0 = автоматичне використання актуальної ціни парсера обраної АЗК).
- **`auto_fetch_fuel_prices`**: Прапорець фонового оновлення роздрібних цін мереж WOG та OKKO.
- **`default_maintenance_interval_hours`**: Стандартний інтервал регламентного ТО (за замовчуванням `300.0 год`).
- **`backup_last_auto_run_date`**: Системна дата останнього успішного автобекапу за розкладом (`YYYY-MM-DD`), яка виключає повторні хибні спрацювання планувальника при перезавантаженні контейнера.
- **`backup_auto_enabled`, `backup_schedule_time`, `backup_frequency`, `backup_retention_count`, `backup_default_type`**: Параметри автоматичного резервного копіювання за розкладом.
- **`default_facility_id`, `default_generator_id`, `default_fuel_stock_id`**: Стартовий ланцюжок за замовчуванням (`Об'єкт ➔ Генератор ➔ Склад ГСМ`).
- **`max_continuous_run_hours`, `auto_stop_on_schedule_end`, `notify_running_heartbeat`, `heartbeat_interval_hours`**: Параметри операційних запобіжників (`12.0 год`, автостоп після зміни, пульс-нагадування кожні `4.0 год`).
- **`fuel_receipt_max_liters_warning`, `fuel_receipt_min_price`, `fuel_receipt_max_price`**: Поріг контролю аномальних чеків (`1000.0 л`, `15.0–250.0 грн/л`).
- **`notifications_enabled`, `notify_generator_start`, `notify_generator_stop`, `notify_low_fuel`, `low_fuel_threshold_l`, `notify_maintenance`, `max_maintenance_notifications_per_day`, `notify_critical_faults`, `notify_yasno_outages`, `notify_air_alerts`, `notify_air_alert_end`**: Правила Web Push сповіщень (включно з тривогами, відбоями та відключеннями YASNO).
- **`smtp_enabled`, `smtp_primary_*`, `smtp_fallback_*`, `email_notify_*`, `email_weekly_*`, `last_weekly_digest_date`**: Конфігурація SMTP Failover (Gmail / Ukr.net) та щотижневої розсилки Excel-дайджесту.

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
