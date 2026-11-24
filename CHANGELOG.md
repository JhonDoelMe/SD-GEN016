# Журнал змін (Changelog)

Усі помітні зміни у цьому проєкті документуються у цьому файлі.
Формат ведення базується на [Keep a Changelog](https://keepachangelog.com/uk/1.0.0/), а версіонування відповідає стандарту [Semantic Versioning (SemVer 2.0.0)](https://semver.org/).

---

## [v5.9.6] — 2026-11-24
### ⛽ Актуальні парсери цін WOG та OKKO + 🧪 Режим тестових пусків генератора
- **Парсери цін АЗК WOG та OKKO ([`settings_service.py`](backend/app/services/settings_service.py), [`system.py`](backend/app/api/v1/system.py), [`main.py`](backend/app/main.py))**:
  - **WOG:** переведено на повний JSON-парсинг `<script id="__NEXT_DATA__">` з опціональним полем `brand` (виправлено пропуск **ГАЗ** і **AdBlue**) та додано мапінг для **А-100 Mustang** і **AdBlue**.
  - **OKKO:** додано семантичне розкриття таблиці символів `window.__NUXT__` за `fuel_code` / `title` / `type` (стійке до зміни порядку карток на сайті) з позиційним і DOM-фолбеками.
  - **Автоматична актуальність цін:** додано перевірку TTL (`3 години`, `is_fuel_prices_stale`) та фоновий планувальник `run_fuel_prices_refresh_loop` у `main.py` для регулярного оновлення цін обох мереж без ручного втручання.
- **Тестові / хибні пуски генератора ([`generator.py`](backend/app/models/generator.py), [`generator_service.py`](backend/app/services/generator_service.py), [`report_service.py`](backend/app/services/report_service.py), [`fuel_service.py`](backend/app/services/fuel_service.py), [`dashboard.js`](frontend/js/dashboard.js), [`operations.js`](frontend/js/operations.js))**:
  - Додано поле `is_test` (`status="TEST"`) у `GeneratorRun` і системне налаштування `test_run_threshold_seconds` (за замовчуванням `120 с` = 2 хв).
  - У модалці зупинки генератора додано галочку **«🧪 Тестовий / хибний пуск»**, яка автоматично вмикається для пусків коротших за поріг (можна зняти або поставити вручну). Тестові пуски не змінюють мотогодини, не списують паливо, не надсилають зайвих push-сповіщень і повністю виключені з усіх звітів (Excel, PDF, аналітика, баланс ПММ).
  - У журналі циклів (`Журнал циклів`) тестові пуски приховані за замовчуванням із перемикачем **«🧪 Показати тестові»**, а для адміністратора додано дії: позначити/повернути пуск (`toggle-test`), видалити тестовий пуск (`DELETE /runs/{id}`) та масове очищення коротких пусків (`🧹 Очистити короткі`).

## [v5.9.4] — 2026-11-24
### ⚡ Комплексна оптимізація швидкодії, виправлення багів і очищення мертвого коду
- **Прискорення завантаження та зниження навантаження API (Frontend + Backend)**:
  - Оптимізовано фоновий полінг ([`notifications.js`](frontend/js/notifications.js)): інтервал переведено з `10 с` на `30 с`, графік YASNO опитується раз на `5 хв` замість щодесять секунд, `visibilitychange` отримав дебаунс `15 с` без примусового обходу кешу (`force=false`).
  - Прибрано дублювання `/notifications/feed` при старті/логіні ([`auth-nav.js`](frontend/js/auth-nav.js)) та подвійні виклики у `manualRunForm` ([`dashboard.js`](frontend/js/dashboard.js)) і `openAllNotificationsLog()` ([`notifications.js`](frontend/js/notifications.js)).
  - На бекенді прибрано каскади `selectin` (`noload`) у `/notifications/feed`, `/notifications/logs`, `get_fuel_balances_summary()` та при старті в `sanitize_historical_audit_logs()`, прибрано зайвий запит `MaintenanceSchedule` у `/facilities/overview`, пакетовано `DELETE` у `delete_facility()` та винесено перевірку/хешування ZIP бекапів у `asyncio.to_thread()`.
- **Виправлені реальні баги (Backend + Frontend)**:
  - **Firebase Test (`ImportError`):** виправлено `_get_fcm_access_token` → `_get_access_token(sa)` у [`system.py`](backend/app/api/v1/system.py).
  - **Тривалість тривог та час MeteoAlarm:** виправлено `now_utc()` → `now_utc(naive=False)` у [`alert_service.py`](backend/app/services/alert_service.py) та [`weather_service.py`](backend/app/services/weather_service.py).
  - **Безпека `AsyncSession`:** усунено конкурентний `asyncio.gather` поверх однієї сесії в `GET /facilities/{id}/status-indicators` ([`facilities.py`](backend/app/api/v1/facilities.py)).
  - **Windows ZipFile cleanup та видалення дефолтного об'єкта:** винесено `unlink()` поза блок `with zipfile.ZipFile(...)` ([`backups.py`](backend/app/api/v1/backups.py), [`backup_service.py`](backend/app/services/backup_service.py)) і збережено очищення `default_facility_id` у БД ([`facility_service.py`](backend/app/services/facility_service.py)).
  - **Фронтенд-баги:** усунено race condition при перемиканні об'єкта/генератора (`_genDataSeq` / `_genListSeq`), ізольовано 60-секундний таймер охолодження за `generatorId`, виправлено парсинг UTC (`parseUTCDate`) у запобіжниках зупинки, кнопку «Оновити зараз» у модалках погоди/тривог ([`weather-alerts.js`](frontend/js/weather-alerts.js)), статуси `FAULTY`/`BLOCKED` і ключ `localStorage` у [`network.js`](frontend/js/network.js), колбеки `loadAllData`/`showToast`/`loadRunsData` ([`backups.js`](frontend/js/backups.js), [`core.js`](frontend/js/core.js), [`dashboard.js`](frontend/js/dashboard.js)), додано очищення форм (`#maintForm`, `#userCreateForm`, `#newStockForm`, `#adjustmentForm`) та стилі бейджів `.badge-success/.badge-warning/.badge-danger/.badge-blocked`.
- **Очищення мертвого коду**:
  - Видалено 9 невикористовуваних legacy-функцій in-memory rate-limit/revocation у [`security.py`](backend/app/core/security.py) (~145 рядків), невикористовувані імпорти, мертвий `updateKyivClock()` ([`theme-format.js`](frontend/js/theme-format.js)) та неіснуючу перевірку `modalWizard` ([`core.js`](frontend/js/core.js)).

## [v5.9.3] — 2026-11-24
### 🎨 Виправлення стилю `.btn-danger` у модалці несправностей та критичних діалогах
- **CSS-система кнопок ([`base.css`](frontend/css/base.css))**:
  - Додано відсутній клас `.btn-danger` (спільна геометрія з `.btn-primary` + червоний градієнт і тінь) — виправлено відображення кнопки «Надіслати заявку» у модалці `#modalFault` («Повідомити про несправність»), а також кнопок підтвердження у `#modalSystemReset` та `#modalMeasurementCancel` на Web, PWA і Android APK.
- **Скидання форми несправності ([`core.js`](frontend/js/core.js), [`operations.js`](frontend/js/operations.js))**:
  - Форма `#faultForm` автоматично очищується при відкритті та після успішного надсилання заявки.

## [v5.9.2] — 2026-11-24
### 🛠️ Виправлення збереження залишку палива при зупинці генератора та скидання полів модалок
- **Критичне виправлення модалки зупинки генератора ([`dashboard.js`](frontend/js/dashboard.js), [`modals-ops.html`](frontend/views/modals-ops.html))**:
  - Усунуто баг, за якого поле `#stopEndFuel` («Фактичний рівень палива в баку») та `#stopNote` не очищувалися при відкритті/відправці `#modalStopGen`. У результаті введений одного разу залишок (напр. `0`) залишався у прихованому DOM та мовчки перезаписував заправлений бак у `0` при кожній наступній зупинці у тій самій сесії.
  - Тепер `#stopGenForm` примусово очищується і перед відкриттям модалки, і після успішної зупинки; виправлено перевірку права `generator:stop`, текст кнопки та додано **запобіжник розбіжності палива** (підтвердження перед перезаписом, якщо введений залишок відрізняється від розрахункового більш ніж на `10 л`).
- **Очищення полів паливних модалок ([`fuel.js`](frontend/js/fuel.js))**:
  - Форми прийому (`setupReceiptModal`) та заправки бака (`setupTransferModal` / `#transferForm`) тепер гарантовано очищують попередні суми, літри та примітки між повторними відкриттями.
- **Аудит розбіжності палива ([`generator_service.py`](backend/app/services/generator_service.py))**:
  - Поле `fuel_discrepancy` у події аудиту `GENERATOR_STOP` тепер коректно фіксує будь-яку розбіжність між розрахунковим та фактичним залишком пального (навіть якщо розрахунковий баланс ще був додатнім).

## [v5.9.1] — 2026-11-20
### 📘 Посібник користувача, Серверні інсталяційні ZIP на `/ota/` та Повна синхронізація політик
- **Дистрибуція серверних інсталяційних ZIP-пакетів через OTA-портал ([`ota-server/app.py`](ota-server/app.py), [`ota-server/storage.py`](ota-server/storage.py), [`ota-server/templates.py`](ota-server/templates.py), [`scripts/release_server_zip.ps1`](scripts/release_server_zip.ps1))**:
  - На публічну сторінку `/ota/` та в адмінку `/ota/admin` додано 3-й канал релізів — **«Серверний пакет • Zero-.env ZIP»** (`/ota/api/server/latest`, `/ota/download/server/latest.zip`, `/ota/download/server/{version_code}.zip`) із SHA-256 перевіркою та архівом попередніх збірок, що дозволяє оновлювати серверні інсталяційні архіви в 1 команду (`scripts/release_server_zip.ps1` або `release_web_ota.ps1 -WithServerZip`) без дублювання релізів на Git-хостингах.
- **Новий посібник із налаштування та експлуатації ([`docs/USER_AND_ADMIN_MANUAL.md`](docs/USER_AND_ADMIN_MANUAL.md))**:
  - Додано покроковий мануал для нових адміністраторів та операторів: від першого запуску (`/setup`), налаштування інтеграцій і об'єктів/генераторів/каністр до щоденного пуску/стопу, роботи офлайн, вимірювання витрат, зведення «🏢 Об'єкти мережі», звітності `₴/год`, Web-OTA та FAQ.
- **Внутрішньосистемна інструкція та актуалізація політик у застосунку ([`modals-legal.html`](frontend/views/modals-legal.html), [`index.html`](frontend/index.html), [`view-loader.js`](frontend/js/view-loader.js))**:
  - Додано модальне вікно **«📖 Короткий посібник користувача»** (`#modalUserManual`) з доступом із меню профілю та підвалу сайту/APK.
  - Оновлено до редакції **`v5.9.1`** вбудовані модальні документи: Політику конфіденційності, Умови використання, Безпеку праці (вкл. реагування на небезпечні явища УкрГМЦ для відкритих майданчиків) та Управління даними й SLA.
- **Повна синхронізація документації репозиторіїв**:
  - Актуалізовано [`README.md`](README.md), [`AGENT.md`](AGENT.md), [`API_REFERENCE.md`](docs/API_REFERENCE.md), [`ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`BUSINESS_RULES.md`](docs/BUSINESS_RULES.md), [`RBAC_PERMISSIONS.md`](docs/RBAC_PERMISSIONS.md), [`PRIVACY_POLICY.md`](docs/PRIVACY_POLICY.md), [`TERMS_OF_SERVICE.md`](docs/TERMS_OF_SERVICE.md), [`OPERATIONAL_SAFETY_POLICY.md`](docs/OPERATIONAL_SAFETY_POLICY.md), [`DATA_GOVERNANCE_AND_AUDIT.md`](docs/DATA_GOVERNANCE_AND_AUDIT.md) та [`SLA_AND_SUPPORT.md`](docs/SLA_AND_SUPPORT.md).

## [v5.9.0] — 2026-11-20
### 📊 Вартість мотогодини, «🏢 Об'єкти мережі» та Push про погодні явища УкрГМЦ
- **Фінансова аналітика у звітах ([`report.py` (схеми)](backend/app/schemas/report.py), [`report_service.py`](backend/app/services/report_service.py), [`audit-reports.js`](frontend/js/audit-reports.js))**:
  - У підсумку операційного звіту та Excel-експорті додано **собівартість 1 мотогодини роботи (`₴/год`)** з розбивкою на паливну складову (`витрачені літри × середньозважена ціна ПММ`) і сервісні витрати на ТО (`cost_per_operating_hour_uah`, `fuel_cost_per_hour_uah`, `maintenance_cost_per_hour_uah`).
- **Мульти-об'єктне зведення «🏢 Об'єкти мережі» ([`facilities.py`](backend/app/api/v1/facilities.py), [`network.html`](frontend/views/network.html), [`network.js`](frontend/js/network.js), [`index.html`](frontend/index.html), [`core.js`](frontend/js/core.js))**:
  - Додано окремий пункт бокового меню для керівників (`Admin`, `SuperAdmin`, `Viewer` або користувачів із доступом до кількох об'єктів) та агрегований ендпоінт `GET /api/v1/facilities/overview`.
  - На одному екрані відображаються KPI мережі та картки всіх об'єктів (генератори, мотогодини, бак, склад ПММ і каністри, запас до ТО, дефекти, повітряні тривоги й погодні попередження) з переходом у 1 клік.
- **Фонові Push-сповіщення про небезпечні погодні явища УкрГМЦ ([`weather_service.py`](backend/app/services/weather_service.py), [`notification_service.py`](backend/app/services/notification_service.py), [`main.py`](backend/app/main.py), [`admin.html`](frontend/views/admin.html), [`notifications.js`](frontend/js/notifications.js))**:
  - Запущено фоновий цикл перевірки попереджень MeteoAlarm (раз на 15 хв) із прив'язкою до відкритих майданчиків генераторів, вибором мінімального рівня небезпеки (`II Помаранчевий` за замовчуванням / `I Жовтий` / `III Червоний`) та двошаровою дедуплікацією.
- **Тести**: додано [`test_network_cost_and_weather_push.py`](backend/tests/test_network_cost_and_weather_push.py) (разом 238 тестів).

## [v5.8.4] — 2026-11-20
### 🌩️ Офіційні метеопопередження УкрГМЦ (MeteoAlarm Україна)
- **Бекенд ([`weather_service.py`](backend/app/services/weather_service.py))**:
  - Інтегровано безкоштовний офіційний JSON/CAP фід **УкрГМЦ через MeteoAlarm** (`https://feeds.meteoalarm.org/api/v1/warnings/feeds-ukraine`) із 15-хвилинним кешуванням.
  - Реалізовано фільтрацію активних (`expires > now`) попереджень українською мовою (`uk-UA`), зіставлення за областю та координатами полігона (`point-in-polygon`), дедуплікацію та класифікацію рівнів небезпеки (Жовтий I, Помаранчевий II, Червоний III).
- **Інтерфейс ([`modals-utility.html`](frontend/views/modals-utility.html), [`weather-alerts.js`](frontend/js/weather-alerts.js), [`views.css`](frontend/css/views.css))**:
  - Індикатор погоди в шапці візуально підсвічує активний рівень штормового попередження.
  - У модалці **«Погода на об'єкті»** виводяться картки активних небезпечних погодних явищ із періодом дії, описом та джерелом `УкрГМЦ · MeteoAlarm`.
- **Тести**: додано тест парсингу та гео-фільтрації попереджень УкрГМЦ у [`test_weather_and_alerts.py`](backend/tests/test_weather_and_alerts.py) (`235` тестів).

## [v5.8.3] — 2026-11-20
### 🔧 Узгодження інтервалу ТО генераторів та індивідуальне редагування регламенту
- **Редагування інтервалу ТО на рівні генератора ([`generator.py` (схеми)](backend/app/schemas/generator.py), [`generator.py`](backend/app/api/v1/generator.py), [`generator_service.py`](backend/app/services/generator_service.py), [`modals-admin.html`](frontend/views/modals-admin.html), [`admin.js`](frontend/js/admin.js))**:
  - Додано поле `maintenance_interval_hours` (мін. 10 год) у модалку редагування генератора (`#modalQuickEditGenerator`), схему `GeneratorUpdate`/`GeneratorOut` та `PUT /api/v1/generator/{id}` з автоматичним перерахунком `next_due_hours` і статусу ТО.
- **Усунення захардкодженого `300.0` та прозорість масової синхронізації ([`maintenance_service.py`](backend/app/services/maintenance_service.py), [`admin.js`](frontend/js/admin.js))**:
  - `maintenance_service.py` та форма створення генератора беруть `default_maintenance_interval_hours` із системних налаштувань замість `300.0`.
  - При збереженні розділу «Робочий регламент, ТО та Прогрів» із вимкненою галкою масової синхронізації інтерфейс явно запитує підтвердження застосування змін до існуючих генераторів і повідомляє точну кількість оновлених генераторів.
- **Мобільний відступ ([`layout.css`](frontend/css/layout.css))**: збільшено нижній безпечний відступ футера для комфортної прокрутки над 3-кнопковою навігацією Android.
- **Тести**: додано тест перерахунку графіка ТО при зміні інтервалу генератора в [`test_maintenance.py`](backend/tests/test_maintenance.py) (`234` тести).

## [v5.8.2] — 2026-11-20
### 🧹 Автоматичне скидання кешу WebView при оновленні та локальне завантаження модулів Web-OTA
- **Автоочищення HTTP-кешу WebView у Java ([`WebOtaManager.java`](android/app/src/main/java/ua/pp/sdgen/app/WebOtaManager.java), [`OtaUpdaterPlugin.java`](android/app/src/main/java/ua/pp/sdgen/app/OtaUpdaterPlugin.java), [`MainActivity.java`](android/app/src/main/java/ua/pp/sdgen/app/MainActivity.java))**:
  - Додано автоматичне очищення дискового кешу Chromium (`WebView.clearCache(true)`) під час застосування Web-OTA бандлу, при оновленні нативного APK та при авто-відкаті — без видалення токенів авторизації та офлайн-черги.
- **Локальне завантаження view/JS усередині Web-OTA ([`view-loader.js`](frontend/js/view-loader.js))**:
  - У режимі Capacitor lazy-модулі (`views/*.html`, `js/*.js`) тепер завантажуються виключно з локального бандлу (`https://localhost/frontend/...` із `cache: 'no-store'`) замість мережевого `getApiBaseUrl()`, що виключає розсинхрон між версією APK/Web-OTA та сервером.
- **Автоочищення застарілого CacheStorage / SW ([`ota-updater.js`](frontend/js/ota-updater.js))**:
  - На старті та перед Web-OTA автоматично видаляються застарілі реєстрації Service Worker і `caches` із попередніх збірок, щоб користувачам не доводилося вручну очищати кеш або дані додатка в Android.

## [v5.8.1] — 2026-11-20
### ✨ Усунення дублювання кнопки оновлення в Android UI (перший реліз через Web-OTA)
- **Меню профілю ([`index.html`](frontend/index.html), [`ota-updater.js`](frontend/js/ota-updater.js))**:
  - У пункті **«🔄 Оновити застосунок»** додано індикатор поточної версії (`#accountAppVersionLabel`, напр. `v5.8.1`), оформлений у стилі перемикача теми.
- **Налаштування сервера ([`modals-account.html`](frontend/views/modals-account.html))**:
  - Прибрано дублюючу кнопку **«Перевірити оновлення»** з модального вікна «Налаштування сервера»; залишено лише інформаційний рядок із версією Android-додатка та Web-збірки.
- **Дистрибуція**: реліз доставляється на Android-пристрої миттєво через **Web-OTA** (`web_build 28`, `min_native_version_code 27`) без перевстановлення APK.

## [v5.8.0] — 2026-11-20
### 🛡️ Web-OTA (Capacitor `setServerBasePath`) та видалення `REQUEST_INSTALL_PACKAGES`
- **Повне видалення дозволу `REQUEST_INSTALL_PACKAGES` ([`AndroidManifest.xml`](android/app/src/main/AndroidManifest.xml))**:
  - Додано директиву `tools:node="remove"` для примусового виключення `REQUEST_INSTALL_PACKAGES` із фінального маніфесту Android, що прибирає евристичні попередження Play Protect про самоінсталяцію пакетів.
- **Двоканальне OTA-оновлення ([`WebOtaManager.java`](android/app/src/main/java/ua/pp/sdgen/app/WebOtaManager.java), [`OtaUpdaterPlugin.java`](android/app/src/main/java/ua/pp/sdgen/app/OtaUpdaterPlugin.java), [`MainActivity.java`](android/app/src/main/java/ua/pp/sdgen/app/MainActivity.java), [`ota-updater.js`](frontend/js/ota-updater.js))**:
  - **Web-Bundle OTA (основний канал)**: клієнт завантажує ZIP-архів `frontend/` по HTTPS, перевіряє **SHA-256** та безпеку шляхів (захист від Zip-Slip), застосовує його через `Bridge.setServerBasePath(...)` і підтверджує запуск (`confirmWebBundle()`). У разі збою завантаження або білого екрана спрацьовує автоматичний відкат (`Auto-Rollback`) до попереднього робочого бандлу чи вбудованих асетів APK.
  - **Нативні оновлення APK (резервний канал)**: замість системного інсталятора зсередини додатка клієнт відкриває `https://sdgen.pp.ua/ota/` у зовнішньому браузері (`openBrowserUrl()`).
- **OTA-сервер ([`app.py`](ota-server/app.py), [`storage.py`](ota-server/storage.py), [`templates.py`](ota-server/templates.py), [`release_web_ota.ps1`](scripts/release_web_ota.ps1))**:
  - Додано ендпоінти Web-OTA (`/ota/api/web/latest`, `/ota/download/web/latest.zip`, `/ota/api/web/releases`, `/ota/api/web/policy`, `/ota/api/web/releases/{web_build}`) із контролем `min_native_version_code`, веб-секцією в `/ota/admin` та автотестами.

## [v5.7.27] — 2026-11-20
### ✏️ Редагування надходжень ПММ (72-годинне вікно, автосинхронізація пулу каністр, аудит)
- **Backend API (`PUT /api/v1/fuel/receipt/{receipt_id}`)**:
  - Додано захищений ендпоінт редагування надходження ПММ виключно для ролей **Admin** та **SuperAdmin** (`get_current_admin`).
  - Суворе серверне 72-годинне вікно від моменту створення запису (`403 Forbidden` після 72 год) та перевірка блокування інвентаризації (`423 Locked`).
  - Редаговані поля: мережа АЗС (`wog`, `okko`, `other`), кількість літрів, загальна вартість або ціна за літр, водій, номер чека/накладної, коментар та обов'язкова причина коригування (`edit_reason`, мінімум 3 символи).
  - Транзакційна корекція залишку складу ПММ (із захистом від від'ємного балансу `400`) та автоматична синхронізація пов'язаного пулу каністр (`adjust_stock_canisters_to_balance` із записом транзакції `RECEIPT_EDIT` і перевіркою максимальної місткості пулу).
  - Запобіжники аномального об'єму/ціни (з підтримкою `force_confirm`) та незмінний запис аудиту `FUEL_RECEIPT_UPDATED` зі знімками `before` → `after`, дельтою літрів і причиною.
- **Frontend UI ([`fuel.html`](frontend/views/fuel.html), [`modals-ops.html`](frontend/views/modals-ops.html), [`fuel.js`](frontend/js/fuel.js))**:
  - У таблиці надходжень додано колонку `Дії` з кнопкою `✏️` (відображається лише адміністраторам у межах 72 год від створення), модальне вікно `#modalEditReceipt` із таймером залишку вікна редагування та взаємним автоперерахунком суми й ціни за літр.
  - Підтримка бейджа `Інша АЗС` та підпису операції каністр `RECEIPT_EDIT`.
- **Автотести**: додано [`test_fuel_receipt_edit.py`](backend/tests/test_fuel_receipt_edit.py) (RBAC, 72 год, захист від мінуса, запобіжник ціни, автосинхронізація пулу каністр та перевірка місткості; усього 232 тести).

## [v5.7.26] — 2026-11-20
### 🇺🇦 Повна лінгвістична чистка та українська термінологія (Web, Backend, Android APK, Звіти та Документація)
- **Заміна русизмів по всьому проєкту (40+ файлів)**:
  - `ГСМ` → `ПММ` (*пально-мастильні матеріали*) у вебі, бекенді, Excel-аркуші («Рух палива та Склад ПММ»), PDF-відомості інвентаризації, журналі аудиту, початковому наповненні БД та документації (`191` заміна).
  - Узгоджено українську термінологію з правильними відмінками та родом: `розхід` → `витрата`, `опечатка` → `помилка вводу`, `пустий/пусті` → `порожній/порожні`, `скачати/скачування` → `завантажити/завантаження`, `папка` → `тека/каталог`, `співпадає/співпадають` → `збігається/збігаються`, `прихід/приход` → `надходження`, `масло` → `олива`.
- **Android APK (`v5.7.26`, `versionCode 26`)**: оновлено тексти в `FileDownloadPlugin.java`, `OtaUpdaterPlugin.java` та синхронізовані Web-асети; зібрано й опубліковано в OTA.

## [v5.7.25] — 2026-11-16
### 📚 Документація, релізний Android APK (`versionCode 25`) та інсталяційний ZIP-пакет
- **Оновлення веб- та репозитарної документації ([`modals-legal.html`](frontend/views/modals-legal.html), [`README.md`](README.md), [`AGENT.md`](AGENT.md), [`RELEASE_NOTES_v5.7.25.md`](RELEASE_NOTES_v5.7.25.md), [`docs/`](docs/))**:
  - Синхронізовано до версії `5.7.25` політики конфіденційності, умови використання, регламенти SLA/безпеки та довідники `ENV_VARS.md`, `DEPLOYMENT_VPS.md`, `ARCHITECTURE.md`, `API_REFERENCE.md`, `BACKUP_AND_RESTORE.md`.
  - Задокументовано CMS-конфігурацію (`🖥️ Сервер та Інтеграції`, `Fernet enc:v1:`), Zero-`.env` bootstrap (`data/instance.config.json`), Web Setup Wizard (`/setup`), Android `WorkManager` + SQLite + `AndroidKeyStore`, `FileDownloadPlugin` та 229 автотестів.
- **Збірка дистрибутива ([`scripts/build_install_zip.py`](scripts/build_install_zip.py)) та Android APK (`v5.7.25`, `versionCode 25`)**:
  - Додано скрипт генерації чистого інсталяційного архіву `dist/sd-gen016-v5.7.25-install.zip` (з контрольною сумою `.sha256` без жодних `.env`, секретів, локальних БД та кешів збірки).
  - Зібрано й опубліковано в OTA оновлений підписаний Android APK (`versionCode 25`).

## [v5.7.24] — 2026-11-16
### 🧙 Етап 3 CMS-архітектури: Web Setup Wizard (`/setup`) та міграція існуючих серверів у Zero-`.env`
- **Одноразовий майстер першого запуску ([`setup.py`](backend/app/api/v1/setup.py), [`setup.html`](frontend/setup.html), [`main.py`](backend/app/main.py), [`bootstrap.py`](backend/app/core/bootstrap.py))**:
  - На чистій інсталяції без `.env` та користувачів у БД (`user_count == 0`) система не створює обліковий запис зі слабким дефолтним паролем, а відкриває захищений 4-кроковий майстер за адресою `/setup` (з автоматичним редиректом із `/`).
  - Підтримує налаштування організації/домену/часового поясу, вибір `SQLite` або `PostgreSQL` із live-тестом підключення (`POST /api/v1/setup/test-db`), створення `SuperAdmin` та опційний ввід API-ключів (шифруються у БД).
  - Одразу після завершення (`POST /api/v1/setup/complete`) майстер незворотно блокується (`403 Forbidden`), а `DynamicTrustedHostMiddleware` вмикає сувору перевірку доменів.
- **Міграція існуючого сервера від `.env` та безпечне перемикання БД ([`system.py`](backend/app/api/v1/system.py), [`database.py`](backend/app/database.py), [`init_service.py`](backend/app/services/init_service.py), [`docker-compose.yml`](docker-compose.yml), [`admin.html`](frontend/views/admin.html), [`admin.js`](frontend/js/admin.js), [`test_setup_wizard.py`](backend/tests/test_setup_wizard.py))**:
  - Додано `POST /api/v1/system/server-config/migrate-zero-env` та кнопку в **Інфраструктурі**, яка фіксує всі активні параметри в зашифровану БД і `data/instance.config.json`; `env_file` у Docker Compose зроблено необов'язковим (`required: false`).
  - Додано `get_engine()` для коректного оновлення активного рушія БД після `reinit_database_engine()`.

## [v5.7.23] — 2026-11-16
### 🌱 Етап 2 CMS-архітектури: Zero-`.env` Bootstrap (`instance.config.json`) та динамічна БД
- **Автономний bootstrap-конфіг ([`bootstrap.py`](backend/app/core/bootstrap.py), [`config.py`](backend/app/config.py), [`.gitignore`](.gitignore))**:
  - Додано підтримку `data/instance.config.json` (атомарний запис з правами `0o600`, виключено з Git): за відсутності `.env` чи `APP_SECRET_KEY` система автоматично генерує й зберігає криптостійкий 64-символьний `app_secret_key` без порушення Production Boot-Lock (`check_security_warnings(has_initialized_admin=...)`).
  - Явні змінні `.env` та середовища завжди зберігають пріоритет над `instance.config.json`, гарантуючи 100% сумісність з існуючими інсталяціями.
- **Динамічний рушій БД та тестування підключення ([`database.py`](backend/app/database.py))**:
  - Додано `build_async_engine()`, `reinit_database_engine()` (перепідключення пулу SQLite/PostgreSQL без перезапуску інтерпретатора) і `probe_database_connection()` (перевірка DSN з автоматичним приховуванням пароля в помилках).
- **Docker та інфраструктурна готовність ([`Dockerfile`](Dockerfile), [`docker-compose.yml`](docker-compose.yml), [`system.py`](backend/app/api/v1/system.py), [`admin.js`](frontend/js/admin.js), [`test_bootstrap.py`](backend/tests/test_bootstrap.py))**:
  - У Docker додано постійний том `data_storage:/app/data` (права `700` для `appuser`), а у вкладці `🖥️ Сервер та Інтеграції` відображається режим конфігурації (`env` або `instance_config`).

## [v5.7.22] — 2026-11-16
### 🖥️ Етап 1 CMS-архітектури: розділ «Сервер та Інтеграції» + шифрування ключів у БД
- **Прибрано «Адреса сервера» у Web/PWA ([`index.html`](frontend/index.html), [`core.js`](frontend/js/core.js))**:
  - На звичайних браузерах та PWA кнопка «Адреса сервера» на екрані входу та у меню профілю прихована; вона залишається доступною лише всередині нативного Android APK (Capacitor).
- **Шифрування секретів у БД та пріоритет `БД -> .env -> default` ([`secrets.py`](backend/app/core/secrets.py), [`settings_service.py`](backend/app/services/settings_service.py), [`audit_service.py`](backend/app/services/audit_service.py), [`report_service.py`](backend/app/services/report_service.py))**:
  - Додано симетричне шифрування секретних ключів (`Fernet` із префіксом `enc:v1:`) при збереженні в таблицю `system_settings`, із автоматичною міграцією `.env`-секретів та застарілих відкритих значень без переривання роботи.
  - Посилено редагування аудит-логів і Excel-експортів для `api_key`, `service_account` і `firebase_service_account`.
- **Динамічні runtime-налаштування без перезапуску ([`weather_service.py`](backend/app/services/weather_service.py), [`alert_service.py`](backend/app/services/alert_service.py), [`fcm_service.py`](backend/app/services/fcm_service.py), [`security.py`](backend/app/core/security.py), [`auth_security_service.py`](backend/app/services/auth_security_service.py), [`auth.py`](backend/app/api/v1/auth.py), [`email_service.py`](backend/app/services/email_service.py), [`main.py`](backend/app/main.py))**:
  - Погода, мапа тривог, Firebase Push (FCM v1), домен (`PRIMARY_DOMAIN`), `ALLOWED_HOSTS`, CORS, JWT TTL та ліміти блокування входу зчитують активні значення з БД з прозорим fallback на `.env`.
- **Новий пункт адміністрування (тільки `SuperAdmin`) ([`system.py`](backend/app/api/v1/system.py), [`admin.html`](frontend/views/admin.html), [`admin.js`](frontend/js/admin.js), [`auth-nav.js`](frontend/js/auth-nav.js), [`test_server_config.py`](backend/tests/test_server_config.py))**:
  - Додано API `GET/PUT /api/v1/system/server-config` та `POST /api/v1/system/server-config/test-integration` (захищені `get_current_superadmin`, маскування `"********"`), а також вкладку `🖥️ Сервер та Інтеграції` із живим тестуванням API та завантаженням Firebase JSON.

## [v5.7.21] — 2026-11-16
### 🤖 Офлайн-стійкість (Етап 2): фонова синхронізація Android `WorkManager` + SQLite
- **Нативна фонова черга в APK ([`OfflineQueueStore.java`](android/app/src/main/java/ua/pp/sdgen/app/OfflineQueueStore.java), [`OfflineAuthVault.java`](android/app/src/main/java/ua/pp/sdgen/app/OfflineAuthVault.java), [`OfflineSyncEngine.java`](android/app/src/main/java/ua/pp/sdgen/app/OfflineSyncEngine.java), [`OfflineSyncWorker.java`](android/app/src/main/java/ua/pp/sdgen/app/OfflineSyncWorker.java), [`OfflineSyncPlugin.java`](android/app/src/main/java/ua/pp/sdgen/app/OfflineSyncPlugin.java), [`MainActivity.java`](android/app/src/main/java/ua/pp/sdgen/app/MainActivity.java), [`build.gradle`](android/app/build.gradle))**:
  - Усередині Android APK черга мутацій (`mutation_queue`) зберігається в SQLite і синхронізується єдиним потокобезпечним рушієм `OfflineSyncEngine` під замком разом із `WorkManager` (`androidx.work:work-runtime:2.10.0`).
  - Якщо оператор поставив дії в чергу без зв'язку й повністю закрив додаток, Android `WorkManager` автоматично прокинеться у фоні при появі мережі та доставить події на сервер (із системним сповіщенням про доставку, конфлікт або закінчення сесії).
  - Токен доступу шифрується через `AndroidKeyStore` (`AES/GCM/NoPadding`).
- **Єдиний адаптер черги та міграція ([`offline-queue.js`](frontend/js/offline-queue.js), [`auth-nav.js`](frontend/js/auth-nav.js), [`core.js`](frontend/js/core.js))**:
  - На вебі/PWA черга продовжує працювати через `IndexedDB`, а в Android APK прозоро перемикається на нативний `OfflineSync` (з автоматичною міграцією попередніх `IndexedDB`-записів у SQLite при першому запуску).

## [v5.7.20] — 2026-11-16
### 🔄 Офлайн-стійкість (Етап 1): захист черги, автоповтор, таймаути та чесний час подій
- **Захист черги, таймаути та авто-синхронізація ([`core.js`](frontend/js/core.js), [`offline-queue.js`](frontend/js/offline-queue.js), [`auth-nav.js`](frontend/js/auth-nav.js), [`notifications.js`](frontend/js/notifications.js))**:
  - При закінченні сесії (`401`) очищується лише кеш читання (`OfflineQueue.clearCacheOnly()`), а локальна черга невідправлених подій `mutation_queue` зберігається до повторного входу; при ручному виході з несинхронізованою чергою показується підтвердження.
  - Додано `AbortController` таймаут (`15 с`) у `api()` та `_sendSingleQueueItem()`, щоб «завислий» сервер чи провайдер миттєво переводили дію в офлайн-чергу замість вічного очікування.
  - Додано періодичний backoff retry (`15 с → 30 с → 60 с`), відновлення завислих `syncing`-елементів при старті (`_recoverStuckSyncingItems()`), автосинхронізацію при поверненні у вкладку (`visibilitychange`) та розгортанні Android APK (`__onNativeResume`).
- **Точний час офлайн-події на бекенді ([`generator.py`](backend/app/schemas/generator.py), [`api/v1/generator.py`](backend/app/api/v1/generator.py), [`generator_service.py`](backend/app/services/generator_service.py), [`test_offline_idempotency.py`](backend/tests/test_offline_idempotency.py))**:
  - `api()` фіксує `event_timestamp` у момент натискання кнопки до постановки в чергу; `start_generator()` і `stop_generator()` приймають і валідують `event_timestamp` (захист від дати в майбутньому, старіше `72 год`, та порушення хронології запуск/стоп), рахуючи тривалість, мотогодини й витрату палива за реальним часом події.

## [v5.7.19] — 2026-11-16
### 📂 Надійне збереження Excel у `Download/` та системний вибір папки (SAF)
- **Виправлено збереження `.xlsx` у файловій системі Android ([`FileDownloadPlugin.java`](android/app/src/main/java/ua/pp/sdgen/app/FileDownloadPlugin.java))**:
  - Файли тепер зберігаються прямо в корінь системної папки `Download/` («Завантаження») з передачею `SIZE` та резервною MIME-спробою `application/octet-stream`, якщо `MediaStore.Downloads` на прошивці відхиляє довгий Office-MIME для `.xlsx`.
  - Якщо автоматичне збереження в `Download/` неможливе, відкривається системний діалог `Intent.ACTION_CREATE_DOCUMENT` (Storage Access Framework) для вибору будь-якої теки без зайвих прав доступу.
- **Прозорий статус збереження і точне ім'я файлу ([`core.js`](frontend/js/core.js), [`audit-reports.js`](frontend/js/audit-reports.js), [`measurement.js`](frontend/js/measurement.js), [`backups.js`](frontend/js/backups.js), [`main.py`](backend/app/main.py))**:
  - Додано `showDownloadResultToast()`, який повідомляє реальний шлях збереження або скасування/помилку (без оманливого статусу при невдачі запису), перевірку непорожнього файлу та CORS `expose_headers=["Content-Disposition"]`.

## [v5.7.18] — 2026-11-16
### 📥 Нативне скачування та відкриття звітів у Android-додатку
- **Нативний Capacitor-плагін `FileDownload` ([`FileDownloadPlugin.java`](android/app/src/main/java/ua/pp/sdgen/app/FileDownloadPlugin.java), [`MainActivity.java`](android/app/src/main/java/ua/pp/sdgen/app/MainActivity.java), [`AndroidManifest.xml`](android/app/src/main/AndroidManifest.xml), [`file_paths.xml`](android/app/src/main/res/xml/file_paths.xml))**:
  - Усунуто обмеження Android WebView, через яке `<a download>` із `blob:` URL не зберігав файли на пристрій.
  - На Android 10+ (API 29+) файли зберігаються напряму в публічну папку `Downloads/SD-GEN016` через `MediaStore.Downloads` без запиту зайвих дозволів; для Android 7–9 додано `WRITE_EXTERNAL_STORAGE` (`maxSdkVersion="28"`) із безпечним fallback через `FileProvider` (`cacheDir/exports/`).
  - Після збереження автоматично запускається перегляд (`Intent.ACTION_VIEW`), а за відсутності переглядача — системне меню «Відкрити / Поділитися» (`Intent.ACTION_SEND`).
- **Спільний JS-модуль завантаження ([`core.js`](frontend/js/core.js), [`audit-reports.js`](frontend/js/audit-reports.js), [`measurement.js`](frontend/js/measurement.js), [`backups.js`](frontend/js/backups.js))**:
  - Додано `window.downloadAuthorizedFile()` та `window.saveDownloadedBlob()` для динамічних та аудиторських Excel-звітів (`.xlsx`), PDF-відомостей інвентаризації (`.pdf`) й архівів бекапів (`.zip`) із прозорим перемиканням між нативним Android-містком та веб-браузером.

## [v5.7.17] — 2026-11-15
### 📱 Адаптація спойлерів на мобільних та виправлення світлої теми в Адмінці
- **Світла тема та мобільний touch-hover ([`views.css`](frontend/css/views.css), [`admin.html`](frontend/views/admin.html))**:
  - Додано `[data-theme="light"] .settings-toggle-item:hover` зі світлим фоном `#f1f5f9` та правило `@media (hover: none)` для усунення «прилипання» темно-сірого hover-фону `rgba(51, 65, 85, 0.65)` на сенсорних екранах.
  - Замінено зашиті світлі кольори заголовків (`#38bdf8`, `#fb923c`) на тематичні класи `.settings-title-cyan` / `.settings-title-amber` (із контрастними `#0284c7` / `#c2410c` у світлій темі) та знято зайвий клас `.smtp-container-block` зі спойлера `#spoilerSmtpGateways`.
- **Мобільна розкладка спойлерів (`<= 768px`) ([`views.css`](frontend/css/views.css))**:
  - На вузьких екранах `.admin-spoiler-summary` перебудовано вертикально: заголовок і опис займають 100% ширини картки (`padding-right: 2.35rem`), стрілка `.admin-spoiler-chevron` закріплена у правому верхньому куті, а статусний бейдж виноситься окремим рядком нижче.
  - Кнопки збереження `.btn-primary` усередині `.settings-card-actions` на мобільному розтягуються на повну ширину `100%`.

## [v5.7.16] — 2026-11-15
### ⚙️ Реорганізація параметрів Адмін-панелі за доменами, частотою змін та спойлерами
- **Модульна архітектура Адмін-панелі ([`admin.html`](frontend/views/admin.html), [`views.css`](frontend/css/views.css))**:
  - Скасовано монолітну 6-екранну форму `#systemSettingsForm` із єдиною кнопкою збереження внизу: тепер кожна картка та спойлер мають власну кнопку збереження без побічних записів у сусідні розділи.
  - **🏢 Об'єкти та Генератори** (`facilities`): додано згорнутий спойлер `#spoilerDefaultChain` («Стартовий ланцюжок за замовчуванням») з живим бейджем `#badgeDefaultChain` та кнопкою `#btnSaveDefaultChain`.
  - **🛢️ ГСМ і Тарифи** (`fuel-admin`): перенесено табло цін АЗК WOG / OKKO, фіксовані ціни пального (`#sysPriceA95`, `#sysPriceDP`, `#sysPriceA92`) та автооновлення `#sysAutoFetchPrices` у картку `#fuelTariffsAdminCard` із кнопкою `#btnSaveFuelTariffs`.
  - **🔔 Сповіщення та Пошта** (`notifications`): поруч із Push-правилами винесено картку `#emailReportsAdminCard` (компактна 2-колонкова сітка `.settings-toggle-grid-2` та параметри щотижневого Excel-звіту) і згорнутий спойлер `#spoilerSmtpGateways` («Поштові шлюзи Primary & Fallback SMTP») із живим статусом `#badgeSmtpStatus`.
  - **⚙️ Регламент та Система** (`system`): залишено розгорнуту картку `#regulationSettingsCard` (графік зміни, інтервал ТО, режим 24/7 та налаштування профілактичного прогріву) і згорнутий спойлер `#spoilerOrgPassport` («Паспорт підприємства та Часовий пояс») із бейджем `#badgeOrgPassport`.
  - Додано стилі `.admin-spoiler`, `.admin-spoiler-badge`, `.settings-toggle-grid-2` та `.settings-card-actions` для темної й світлої тем.
- **Незалежне часткове збереження та RBAC ([`admin.js`](frontend/js/admin.js), [`auth-nav.js`](frontend/js/auth-nav.js), [`core.js`](frontend/js/core.js))**:
  - Замінено загальний `submit`-обробник `#systemSettingsForm` на `saveSystemSection(sectionKey, btnEl)`, що надсилає часткові `PUT /api/v1/system/settings` лише для відповідної секції та оновлює живі бейджі через `updateAdminSpoilerBadges()`.
  - Оновлено `switchAdminSubtab()` для завантаження системних налаштувань на підвкладках `facilities`, `fuel-admin`, `notifications` і `system` (лише за наявності адмін-прав), а `applyRolePermissionsUI()` тепер приховує адмін-картки `#spoilerDefaultChain`, `#fuelTariffsAdminCard`, `#emailReportsAdminCard`, `#spoilerSmtpGateways` від користувачів без `settings:manage`.

## [v5.7.15] — 2026-11-15
### 📱 Мобільна сітка прогріву (50%/50%) та умовний показ по простою / морозу
- **Мобільний та десктопний макет блоку дій ([`dashboard.html`](frontend/views/dashboard.html), [`views.css`](frontend/css/views.css))**:
  - Замінено `.btn-action` для кнопок `#btnWarmupStart` та `#btnOpenManualRun` на окремий компактний клас `.btn-hero-sec` у контейнері `#heroSecondaryActions` (`.hero-secondary-actions`).
  - На мобільних екранах (`<= 640px`), коли видимі обидві кнопки, блок автоматично перемикається на рівну 2-колонкову сітку `50% / 50%` в один рядок (`.has-warmup`), усуваючи перекіс «сходинкою».
- **Умовне відображення та авто-зникнення після прогріву ([`settings_service.py`](backend/app/services/settings_service.py), [`system.py`](backend/app/api/v1/system.py), [`generator.py`](backend/app/schemas/generator.py), [`generator_service.py`](backend/app/services/generator_service.py), [`api/v1/generator.py`](backend/app/api/v1/generator.py), [`operational_guard_service.py`](backend/app/services/operational_guard_service.py), [`dashboard.js`](frontend/js/dashboard.js), [`weather-alerts.js`](frontend/js/weather-alerts.js), [`admin.html`](frontend/views/admin.html), [`admin.js`](frontend/js/admin.js), [`test_operational_safeguards.py`](backend/tests/test_operational_safeguards.py))**:
  - Додано налаштування `warmup_cold_temp_c` (за замовчуванням `-10.0°C`) та `warmup_trigger_mode` (`any` — «Простій або мороз», `idle`, `cold`, `both`) у Блоці 4 Адмін-панелі та системних налаштуваннях.
  - Кнопка `#btnWarmupStart` і банер `#genWarmupDueBanner` з'являються виключно за обраною умовою (простій або мороз ≤ порогу) та автоматично приховуються на 12 годин (`warmup_recently_done`) одразу після виконаного прогріву або робочого циклу.
  - Фонова перевірка `GENERATOR_WARMUP_DUE` враховує погоду об'єкта та обраний режим тригера, а також поважає 12-годинну паузу після запуску.

## [v5.7.14] — 2026-11-15
### 🔥 Профілактичний прогрів генератора та виправлення калькулятора автономності YASNO
- **Виправлено розрахунок плану відключень YASNO та витрати пального ([`dashboard.js`](frontend/js/dashboard.js))**:
  - У функціях `_sumYasnoTodayRemMinutes()` і `_sumYasnoTomorrowMinutes()`, а також у резервному пошуку слота в `updateFuelAssessmentBlock()` додано фільтрацію слотів строго за типами відключень (`Definite` / `Probable`). Раніше враховувалися й зелені інтервали `"NotPlanned"`, що завищувало добовий план до 24–38 год.
  - Поточний час доби для слотів YASNO тепер обчислюється у таймзоні об'єкта/генератора (`Europe/Kyiv` через `Intl.DateTimeFormat`), а не за локальним годинником браузера.
  - Замінено `|| 2.2` у калькуляторі автономності та таймері на `_getNominalConsumption()`, щоб явне нульове значення номінальної витрати не підмінялося на `2,2 л/год`.
- **Новий функціонал «Профілактичний прогрів» ([`settings_service.py`](backend/app/services/settings_service.py), [`system.py`](backend/app/api/v1/system.py), [`generator.py`](backend/app/api/v1/generator.py), [`generator_service.py`](backend/app/services/generator_service.py), [`operational_guard_service.py`](backend/app/services/operational_guard_service.py), [`notification_service.py`](backend/app/services/notification_service.py), [`dashboard.html`](frontend/views/dashboard.html), [`admin.html`](frontend/views/admin.html), [`admin.js`](frontend/js/admin.js), [`views.css`](frontend/css/views.css), [`test_operational_safeguards.py`](backend/tests/test_operational_safeguards.py))**:
  - Відстеження днів простою (`days_since_last_run`, `last_run_at`, `warmup_recommended`, `warmup_duration_minutes` у `GeneratorOut`) без зміни структури БД (`ALTER TABLE` не виконувався).
  - Кнопка запуску профілактичного прогріву (`#btnWarmupStart`), банер рекомендації при простої (`#genWarmupDueBanner`), бейдж активного прогріву (`#activeRunWarmupBadge`) та збереження тегу `Профілактичний прогрів` у примітці робочого циклу після зупинки.
  - Налаштування в Адмін-панелі Блок 4 (`warmup_reminder_enabled`, `warmup_idle_days`, `warmup_duration_minutes`) + push-сповіщення `GENERATOR_WARMUP_DONE` (по завершенні заданих хвилин) і `GENERATOR_WARMUP_DUE` (при простої з 7-денним захистом від спаму).

## [v5.7.13] — 2026-11-15
### 🛠️ Узгодження часового поясу в Email/експорті, єдиний розрахунок живого пального та `--no-code` версіонування
- **Локальний час (`now_facility()`) замість сирого UTC ([`email_service.py`](backend/app/services/email_service.py), [`audit.py`](backend/app/api/v1/audit.py), [`backups.py`](backend/app/api/v1/backups.py), [`reports.py`](backend/app/api/v1/reports.py), [`system.py`](backend/app/api/v1/system.py), [`test_email_system.py`](backend/tests/test_email_system.py))**:
  - У всіх системних email-сповіщеннях (зміна пароля, автостоп, порожній/низький бак, критична несправність тощо) додано єдиний хелпер `_now_email_str()` через `now_facility()`, щоб листи завжди показували локальний час об'єкта (`Europe/Kyiv`) незалежно від таймзони Docker-контейнера.
  - Мітки часу у назвах завантажуваних Excel-звітів, бекапів та періоді ручного щотижневого звіту переведено на `now_facility()`.
- **Єдина функція живого розрахунку пального ([`fuel_service.py`](backend/app/services/fuel_service.py), [`operational_guard_service.py`](backend/app/services/operational_guard_service.py))**:
  - Винесено спільний хелпер `compute_generator_live_fuel_l()` (з уніфікованою UTC-нормалізацією naive/aware datetime і врахуванням `start_fuel_level_l`), який використовується як для API залишків (`compute_live_tank_levels_map()`), так і для фонових перевірок (`check_operational_guardrails()`).
- **Інструмент версіонування ([`bump-version.js`](scripts/bump-version.js))**:
  - Додано прапорець `--no-code` для чисто серверних/веб патчів без інкременту Android `versionCode`.

## [v5.7.12] — 2026-11-15
### ⏱️ Коректний час запуску та живий залишок пального у сповіщенні heartbeat (`operational_guard_service`)
- **Локальний час запуску та живий розрахунковий залишок ([`operational_guard_service.py`](backend/app/services/operational_guard_service.py), [`test_operational_safeguards.py`](backend/tests/test_operational_safeguards.py))**:
  - У періодичному сповіщенні `⚠️ Генератор ... досі працює` час старту тепер форматується через `to_facility_time(run.start_time, tz_name=gen.timezone)` у часовому поясі об'єкта/генератора (`Europe/Kyiv`) замість сирого UTC.
  - Залишок пального в тексті сповіщення тепер показує живий розрахунковий залишок `live_fuel_l` (з урахуванням витрат за фактичний час роботи), узгоджений із дашбордом і вкладкою «Паливо», а не статичне значення на момент запуску.

## [v5.7.11] — 2026-11-15
### ⛽ Живий залишок пального у «Паливо» та блокування заправки під час роботи (`versionCode 18`)
- **Узгоджений розрахунок залишку в баку ([`fuel_service.py`](backend/app/services/fuel_service.py), [`schemas/fuel.py`](backend/app/schemas/fuel.py), [`schemas/generator.py`](backend/app/schemas/generator.py), [`api/v1/generator.py`](backend/app/api/v1/generator.py), [`frontend/views/fuel.html`](frontend/views/fuel.html), [`frontend/js/dashboard.js`](frontend/js/dashboard.js))**:
  - Додано функцію `compute_live_tank_levels_map()`, яка для генераторів зі статусом `RUNNING` розраховує живий залишок пального у реальному часі без передчасного псування облікового стовпця в БД.
  - `GET /api/v1/fuel/summary` повертає живий `tank_balance_l`, синхронний з дашбордом оператора, разом із `tank_accounting_balance_l` та `has_running_generators` (на картці вкладки «Паливо» відображається також рівень на старті циклу); `GET /api/v1/generator` і `/list` передають `live_fuel_tank_level_l`.
- **Категорична заборона заправки під час роботи генератора ([`fuel_service.py`](backend/app/services/fuel_service.py), [`frontend/js/fuel.js`](frontend/js/fuel.js), [`test_fuel_management.py`](backend/tests/test_fuel_management.py))**:
  - На бекенді (`POST /api/v1/fuel/transfer`) та в інтерфейсі модалки «Заправити бак» заправка генератора у статусі `RUNNING` блокується з чітким попередженням про небезпеку та вимогою спочатку зупинити генератор для фіксації витрати.

## [v5.7.10] — 2026-11-15
### 🪟 «Розумний трей» індикаторів у мобільній шапці (`versionCode 17`)
- **Розвантаження верхньої панелі на смартфонах ([`frontend/index.html`](frontend/index.html), [`frontend/css/layout.css`](frontend/css/layout.css), [`frontend/js/auth-nav.js`](frontend/js/auth-nav.js), [`frontend/js/weather-alerts.js`](frontend/js/weather-alerts.js), [`frontend/js/offline-queue.js`](frontend/js/offline-queue.js))**:
  - На екранах `<= 768px` приховано кнопку `#headerInstallBtn` у шапці (встановлення PWA / APK доступне з бокового меню `#navDrawer`) та захищено `.header-brand` (`overflow: hidden` + `text-overflow: ellipsis`) від перекриття тексту `SD-GEN016`.
  - Додано системний трей індикаторів (`#headerTrayWrap` / `window.syncHeaderTray()`): спокійні/довідкові стани (`☀️` Погода, `🟢` Відбій тривоги, `📶` Онлайн) згортаються в розгортаємий поповер трею з повними підписами, тоді як **активні або критичні події** (`🔴`/`🟡` Тривога/БПЛА, `🟠`/`🔄`/`⚠️` Офлайн/Черга/Конфлікт, `📏` Активний замір, `🔔` Дзвіночок) залишаються видимими безпосередньо в шапці.

## [v5.7.9] — 2026-11-15
### 📲 Встановлення з браузера, іконка Wi-Fi, швидке оновлення Android та сповіщення (`versionCode 16`)
- **Пункт встановлення застосунку в боковому меню ([`frontend/index.html`](frontend/index.html), [`frontend/views/modals-utility.html`](frontend/views/modals-utility.html), [`frontend/js/notifications.js`](frontend/js/notifications.js), [`frontend/js/view-loader.js`](frontend/js/view-loader.js))**:
  - У боковому меню навігації (`#navDrawer`) додано кнопку **«📲 Встановити застосунок»** (`#navDrawerInstallApp`), видиму лише у веббраузері (приховано в нативному APK та standalone PWA).
  - Додано універсальне модальне вікно `#modalAppInstall` з двома варіантами: швидке встановлення веб-додатку (PWA через `beforeinstallprompt` або покрокові інструкції для iOS/Chrome/Edge) та пряме завантаження офіційного Android APK (`/ota/download/latest.apk`).
- **Тематична іконка Wi-Fi замість зеленої крапки онлайн-режиму ([`frontend/index.html`](frontend/index.html), [`frontend/js/offline-queue.js`](frontend/js/offline-queue.js), [`frontend/css/components.css`](frontend/css/components.css))**:
  - Іконку статусу підключення (`#offlinePillIcon`) замінено на тематичний векторний SVG-значок Wi-Fi (активний сигнал для онлайн, перекреслений Wi-Fi для офлайну) з контрастним оформленням для світлої й темної тем — тепер статус мережі чітко відрізняється від зеленого індикатора відбою тривоги.
- **Швидше оновлення UI та подій в Android APK ([`MainActivity.java`](android/app/src/main/java/ua/pp/sdgen/app/MainActivity.java), [`frontend/js/notifications.js`](frontend/js/notifications.js))**:
  - У `MainActivity` додано виклик `window.__onNativeResume()` у `onResume()` та `onNewIntent()` (відкриття з фону або за натисканням push-сповіщення).
  - Розширено обробник `fcmPushReceived` для всіх типів оперативних подій та створено `window.refreshActiveAppState()`, що оновлює дзвіночок сповіщень, індикатори об'єкта, дані генератора й поточну активну оперативну вкладку без ручного оновлення (фоновий інтервал скорочено до `10 с`, поріг `visibilitychange` — до `1 с`).
- **Монохромна та кольорова іконки для сповіщень Android ([`ic_stat_sdgen.xml`](android/app/src/main/res/drawable/ic_stat_sdgen.xml), [`colors.xml`](android/app/src/main/res/values/colors.xml), [`AndroidManifest.xml`](android/app/src/main/AndroidManifest.xml), [`SdgenFirebaseMessagingService.java`](android/app/src/main/java/ua/pp/sdgen/app/SdgenFirebaseMessagingService.java))**:
  - Додано векторний монохромний силует `ic_stat_sdgen` для системного статус-бару та `default_notification_icon` / `default_notification_color` у маніфесті.
  - У картці сповіщення Android налаштовано кольорову круглу емблему `SD-GEN016` (`setLargeIcon(ic_launcher_round)`) разом із тематичним акцентним кольором (`#EF4444` для тривог/аварій, `#38BDF8` для звичайних подій).
- **Конфігурація GitGuardian ([`.gitguardian.yml`](.gitguardian.yml))**:
  - Додано `.gitguardian.yml` з виключенням синтетичних тестових фікстур (`backend/tests/**`, `ota-server/tests/**`), щоб уникнути хибних спрацьовувань на тестових паролях.

## [v5.7.8] — 2026-11-14
### 🔙 Нативна навігація кнопкою «Назад» на Android (`versionCode 15`)
- **Нативне перехоплення системної кнопки/жесту «Назад» ([`MainActivity.java`](android/app/src/main/java/ua/pp/sdgen/app/MainActivity.java))**:
  - Зареєстровано `OnBackPressedCallback`, який передає подію у WebView через `window.__handleNativeBack()` з fallback на `webView.goBack()` та нативний вихід.
- **Пріоритетна навігація інтерфейсу ([`frontend/js/auth-nav.js`](frontend/js/auth-nav.js), [`frontend/js/core.js`](frontend/js/core.js), [`frontend/js/audit-reports.js`](frontend/js/audit-reports.js))**:
  - Пріоритет 1: закриття відкритого бокового меню (`#navDrawer`), меню профілю (`#accountDropdown`) та стрічки сповіщень (`#notificationsDropdown`).
  - Пріоритет 2: закриття найвищого відкритого модального вікна (`window.getTopOpenModalId()` із урахуванням `z-index` і стеку `_openModalStack`), не зачіпаючи `#authOverlay` та обов'язкове оновлення `#modalAppUpdate`; додатково підтримано закриття верхньої модалки клавішею `Escape`.
  - Пріоритет 3: покрокове повернення за історією переходів (`window._navHistory`) між розділами (`switchTab`), підвкладками адміністрування (`switchAdminSubtab`) та підвкладками звітів (`switchReportSubtab`), а з порожнім стеком — повернення на Головну (`tab-dashboard`).
  - Пріоритет 4: захист від випадкового закриття — подвійне натискання «Назад» на кореневому екрані протягом `2.2 с` із підказкою-тостом.

## [v5.7.7] — 2026-11-14
### 🔄 Виправлення OTA-оновлень Android та заправки бака до повної ємності (`versionCode 14`)
- **Ініціалізація та ручний запуск OTA в Android ([`frontend/js/ota-updater.js`](frontend/js/ota-updater.js), [`frontend/js/core.js`](frontend/js/core.js), [`frontend/js/auth-nav.js`](frontend/js/auth-nav.js))**:
  - Виправлено життєвий цикл `ota-updater.js`: оскільки модуль підвантажується ліниво через `view-loader.js` уже після `DOMContentLoaded`, ініціалізацію переведено на `initOtaUpdater()`, яка запускається негайно при `document.readyState !== 'loading'`.
  - Функцію `showUpdateModal()` переведено на `async` із гарантованим довантаженням `await ViewLoader.ensureModal('modalAppUpdate')`.
  - У вікні налаштувань сервера (`openServerSettingsModal()`) підвантажується `ota-updater.js` на нативному Android і оновлюється бейдж поточної версії (`window.refreshOtaVersionBadge()`), а пункт меню **«🔄 Оновити застосунок»** (`hardRefreshApp()`) на Android запускає перевірку OTA (`window.checkForAppUpdates({ manual: true })`).
- **Усунення обмеження `59,9 л` при заправці 60-літрового бака ([`backend/app/services/fuel_service.py`](backend/app/services/fuel_service.py), [`frontend/js/fuel.js`](frontend/js/fuel.js), [`frontend/views/modals-ops.html`](frontend/views/modals-ops.html), [`backend/tests/test_fuel_management.py`](backend/tests/test_fuel_management.py))**:
  - Усунено конфлікт між точністю БД (`0.001 л`) та округленням UI (`0.1 л`), через який при залишку на зразок `59.944 л` долив `0.1 л` відхилявся сервером із `HTTP 400`.
  - Додано допуск округлення `rounding_slack = Decimal("0.050")` на сервері (`tank_before < tank_cap` і `tank_after <= tank_cap + 0.050` ➔ фіксація `tank_after = tank_cap`), переведено `#transLiters` на `step="any" min="0.01"` і уніфіковано клієнтські розрахунки меж через `_computeTransferBounds()`.

## [v5.7.6] — 2026-11-14
### ⌨️ Виправлення відступів клавіатури IME на Android (`versionCode 13`)
- **Усунення подвійного блоку над клавіатурою ([`capacitor.config.json`](capacitor.config.json), [`MainActivity.java`](android/app/src/main/java/ua/pp/sdgen/app/MainActivity.java), [`AndroidManifest.xml`](android/app/src/main/AndroidManifest.xml), [`styles.xml`](android/app/src/main/res/values/styles.xml), [`frontend/css/layout.css`](frontend/css/layout.css))**:
  - Налаштовано плагін `SystemBars` (`insetsHandling: "css"`, `style: "DARK"`, `initialViewportFitValueHint: "cover"`) та прибрано дублюючий слухач IME на `android.R.id.content` у `MainActivity.java`, щоб відступ клавіатури не застосовувався двічі.

## [v5.7.5] — 2026-11-14
### 🛡️ Посилення безпеки, Production-жорсткість, SW Cache-Busting та Фірмові іконки Android
- **Production & Nginx Hardening ([`backend/app/main.py`](backend/app/main.py), [`backend/app/config.py`](backend/app/config.py), [`docker/nginx.conf`](docker/nginx.conf))**:
  - Вимкнено `/docs`, `/redoc` та `/openapi.json` коли `APP_ENV=production`.
  - Додано `server_tokens off` у всі блоки Nginx і прибрано дублювання безпекових/CSP заголовків між FastAPI та Nginx.
- **Аудит безпеки, цілісності й тестування (`backend/`, `ota-server/`, `android/`, `frontend/`, **203 backend + 5 OTA тестів**)**:
  - Посилено захист автентифікації, SSRF (поштовий/webhook/URL перевірки), OTA-завантажень і перевірки підпису/SHA-256 (`OtaUpdaterPlugin.java`, `ota-server/storage.py`), безпеку архівів бекапів, фронтенд-PWA/XSS санітизацію та доменні інваріанти (`canister_service.py`, `measurement_service.py`, `offline-queue.js`).
  - Додано автоматичний релоад клієнтів PWA при зміні контролера Service Worker (`controllerchange` у `frontend/index.html`) і автоматичний bump версії cache-busting у `scripts/bump-version.js`.
- **Фірмова айдентика Android (`scripts/generate-android-icons.py`, `android/app/src/main/res/`)**:
  - Згенеровано та встановлено брендовані іконки запуску (`ic_launcher`, адаптивні та round) і splash-екрани `SD-GEN016` для всіх щільностей екрана.

## [v5.7.4] — 2026-11-14
### 📚 Повна синхронізація документації, політик та вбудованих правил продукту
- **Вбудовані юридичні й експлуатаційні модалки та API-метадані ([`frontend/views/modals-legal.html`](frontend/views/modals-legal.html), [`backend/app/main.py`](backend/app/main.py), [`scripts/bump-version.js`](scripts/bump-version.js))**:
  - Актуалізовано всі 4 вбудовані модальні документи (`modalPrivacyPolicy`, `modalTermsOfService`, `modalOperationalSafety`, `modalDataGovernance`) до версії **`v5.7.4`** (`14 листопада 2026 року`): додано опис Offline IndexedDB черги + `idempotency_records`, Android Capacitor APK + OTA (`/ota/`) + FCM HTTP v1, Центру сповіщень (`🔔`) + `notification_reads`, фірмових Email з 1-click відпискою (RFC 8058), профілів/аватарів (`.webp`), Режиму вимірювання витрат «від повного до повного», пулів каністр (`CanisterPool`), 6-аркушевих звітів Excel, А4 PDF та повної українізації аудиту.
  - Оновлено `description` FastAPI додатку у `backend/app/main.py` для мультиоб'єктного флоту бензинових та дизельних генераторів.
  - Виправлено `scripts/bump-version.js`, щоб автоматично оновлювати також мітку `SD-GEN016 • vX.Y.Z` у футері навігаційного меню (`frontend/index.html`).
- **Репозитарна та експлуатаційна документація ([`README.md`](README.md), [`AGENT.md`](AGENT.md), `docs/*`, [`RELEASE_NOTES_v5.7.4.md`](RELEASE_NOTES_v5.7.4.md))**:
  - Оновлено всі **13 документів** у `docs/` (`API_REFERENCE.md`, `ARCHITECTURE.md`, `BACKUP_AND_RESTORE.md`, `BUSINESS_RULES.md`, `CANISTER_FUEL_ARCHITECTURE.md`, `DATA_GOVERNANCE_AND_AUDIT.md`, `DEPLOYMENT_VPS.md`, `ENV_VARS.md`, `OPERATIONAL_SAFETY_POLICY.md`, `PRIVACY_POLICY.md`, `RBAC_PERMISSIONS.md`, `SLA_AND_SUPPORT.md`, `TERMS_OF_SERVICE.md`), `CHANGELOG.md`, `README.md` та `AGENT.md` відповідно до фактичного коду (`014` міграцій Alembic, 15 роутерів v1, 22 сервісів, 14 views / 16 js / 4 css, `ota-server/`, `android/`, 193 бекенд + 3 OTA тести).

## [v5.7.0 — v5.7.3] — 2026-11-13 — 2026-11-14
### 🔔 Центр сповіщень у шапці, фірмовий Email + 1-Click відписка та Повна українізація аудиту
- **Центр сповіщень у верхній панелі (`#headerBellBtn`, `frontend/js/notifications.js`, `GET /api/v1/notifications/feed`, `POST /api/v1/notifications/read`)**:
  - Додано іконку дзвоника в шапці з бейджем непрочитаних сповіщень, випадаючою стрічкою, персистентною таблицею `notification_reads`, дедуплікацією емодзі та паралельним завантаженням (`v5.7.1`).
- **Фірмовий Email та RFC 8058 відписка (`email_service.py`, `api/v1/email_public.py`)**:
  - Усі операційні та дайджест-листи переведено на адаптивний HTML-шаблон із круглим логотипом продукту `SD-GEN016`; додано заголовки `List-Unsubscribe` / `List-Unsubscribe-Post` та 1-click ендпоінти `/api/v1/email/unsubscribe`, `/resubscribe`.
- **Повна українізація журналу аудиту (`v5.6.11`, `v5.7.3`)**:
  - Перекладено всі англомовні назви дій, сутностей, `snake_case`-ключів деталей та значень у журналі аудиту і 2-аркушевому Excel-експорті.
- **Виправлення стабільності (`v5.7.2`)**:
  - Усунено нескінченну рекурсію `openModal` при експорті аудиту / системних коригуваннях та виправлено ORM-запит `Facility` у фоновому циклі повітряних тривог.

## [v5.6.7 — v5.6.10] — 2026-11-13
### 🧩 Модульний Service Desk інтерфейс, Профілі та Аватари (`014_user_avatar.py`)
- **Модульна архітектура фронтенду (`frontend/views/`, `frontend/css/`, `frontend/js/view-loader.js`)**:
  - Розбито монолітний HTML/CSS на 14 HTML-парціалів (`views/*.html`), 4 CSS-файли (`css/*.css`) та динамічний завантажувач представлень; додано `sticky` верхню панель, бічний навігаційний ящик (`Drawer`), уніфіковану панель налаштувань адміністратора та кнопку примусового очищення кешу PWA (`v5.6.8`–`v5.6.10`).
- **Профіль користувача та `.webp` аватари (`services/avatar_service.py`, `014_user_avatar.py`)**:
  - Додано особистий профіль (`PUT /api/v1/auth/me`, `POST/DELETE /api/v1/auth/me/avatar`) та адміністративне керування аватарами (`/api/v1/users/{id}/avatar`) з оптимізацією у `.webp` (`Pillow`) та авторизованим доступом `/uploads/avatars/*`.

## [v5.6.2 — v5.6.6] — 2026-11-12 — 2026-11-13
### 📱 Android Capacitor APK, Автономний OTA-сервер (`/ota/`) та FCM HTTP v1 Push
- **Нативний мобільний клієнт (`android/`)**: зібрано підписаний Android Capacitor APK із підтримкою динамічної маршрутизації сервера та коректних системних відступів Edge-to-Edge (`WindowInsets`, `v5.6.4`).
- **Автономний OTA-сервіс (`ota-server/`, `frontend/js/ota-updater.js`)**: розгорнуто окремий FastAPI сервіс роздачі оновлень APK через Nginx `/ota/` із перевіркою мінімальної обов'язкової версії та адмін-керуванням релізами.
- **Native Android Push (`services/fcm_service.py`, `/api/v1/notifications/fcm/*`)**: інтегровано Firebase Cloud Messaging (HTTP v1 через `firebase-admin`) паралельно з браузерним Web Push VAPID.
- **Флагманська дизайн-система (`v5.6.2`)**: оновлено адаптивні сітки, контрастність і перенесення довгих кнопок `.btn-primary` на вузьких екранах.

## [v5.6.0 — v5.6.1] — 2026-11-12
### 📏 Режим вимірювання витрат палива («від повного до повного»)
- **Серверна логіка та міграція БД ([`models/measurement.py`](backend/app/models/measurement.py), [`alembic/versions/013_fuel_measurements.py`](backend/alembic/versions/013_fuel_measurements.py), [`services/measurement_service.py`](backend/app/services/measurement_service.py), [`api/v1/measurement.py`](backend/app/api/v1/measurement.py))**:
  - Додано таблицю `fuel_measurements` (машина станів `MEASURING` → `PENDING_INVENTORY` → `PENDING_APPROVAL` → `APPROVED` / `CANCELLED`), інтегровану з бекапами (`backup_service.py`) та очищенням БД (`settings_service.py`).
  - Метод **«від повного до повного»**: старт (`POST /api/v1/measurement/start`, **виключно SuperAdmin**) можливий при зупиненому генераторі і 100% повному баку.
  - Під час `MEASURING` лічильник заміру рахує виключно паливо, залите в бак (`POST /api/v1/fuel/transfer`); заправки дозволяються до повної ємності баку (`liters <= tank_capacity_l`) незалежно від книжкового залишку, ігноруються сповіщення низького залишку та розбіжності пального (`LOW_FUEL`, `FUEL_DISCREPANCY`, `allow_system_clamp=True`), а будь-які ручні корекції палива/каністр/норми витрат блокуються (`HTTP 423 Locked`).
  - Вихід кнопкою **«✅ Бак повний»** (`POST /api/v1/measurement/{id}/finish-full`) можливий після зупинки генератора й заливки в бак щонайменше **100 літрів** (`added_during_measurement_l >= 100`), одразу повертаючи рівень баку в 100%.
  - **Без блокування роботи генератора при блекауті:** після «Бак повний» (`PENDING_INVENTORY` / `PENDING_APPROVAL`) `start` / `stop` / `manual-run` залишаються повністю доступними, а блокуються лише склад ГСМ, дозаправка баку, рух каністр і ручні корекції (`HTTP 423`) до підписання й погодження.
  - **Спрощена інвентаризація та А4 PDF:** комісія (мін. **3 особи**) підтверджує повний бак і вводить лише фактичний залишок складу (л) — система сама розкладає його на повні каністри та резерв (напр. `53 л → 2 × 20 л + 13 л резерв`) через `compute_stock_canister_breakdown`, формує PDF-відомість формату **А4 альбомної орієнтації** (`fpdf2` + `fonts-dejavu-core`) та після обов'язкового скачування і натискання **«Погоджено»** (`POST /api/v1/measurement/{id}/approve`) оновлює `nominal_consumption_l_per_h`, залишки складу й тари (`INVENTORY_CORRECTION`) без стирання витрат проміжних запусків генератора, записує аудит та 6-й аркуш Excel-звіту «Заміри та інвентаризація».
- **PWA-інтерфейс (`sd-gen016-v5.6.1`, [`frontend/js/measurement.js`](frontend/js/measurement.js), [`frontend/js/fuel.js`](frontend/js/fuel.js), [`frontend/index.html`](frontend/index.html), [`core.js`](frontend/js/core.js), [`dashboard.js`](frontend/js/dashboard.js), [`audit-reports.js`](frontend/js/audit-reports.js), [`sw.js`](frontend/sw.js))**:
  - Додано кнопку меню «📏 Режим вимірювання» (лише для `SuperAdmin`), статус-пігулку `#headerMeasurementBadge`, банер `#measurementLockBanner`, модалку проміжних результатів `#modalMeasurementStatus`, авторозрахунок каністр на льоту, скачування PDF, погодження та підвкладку у «Звітах».

## [v5.5.0 — v5.5.1] — 2026-11-12
### 📡 Справжній Offline-режим PWA (`IndexedDB` + Ідемпотентність + Ручні конфлікти)
- **Універсальна ідемпотентність операцій на бекенді ([`models/idempotency.py`](backend/app/models/idempotency.py), [`alembic/versions/012_offline_idempotency.py`](backend/alembic/versions/012_offline_idempotency.py), [`services/idempotency_service.py`](backend/app/services/idempotency_service.py))**:
  - Додано таблицю `idempotency_records` (ключ `idempotency_key` через тіло запиту або заголовок `Idempotency-Key` + SHA-256 хеш тіла запиту).
  - Повторна відправка вже виконаної офлайн-операції повертає збережену відповідь із заголовком `X-Idempotency-Replayed: true` без дублювання (покрито `/generator/stop`, `/fuel/canisters/{id}/dispatch|return-empty|receive`, `/maintenance/record`, `/faults`, на додачу до `/generator/start`, `/generator/manual-run`, `/fuel/receipt`, `/fuel/transfer`); зміна даних при старому ключі відхиляється як `HTTP 409`.
- **Клієнтський офлайн-рушій `IndexedDB` ([`frontend/js/offline-queue.js`](frontend/js/offline-queue.js), [`core.js`](frontend/js/core.js), [`auth-nav.js`](frontend/js/auth-nav.js), [`sw.js`](frontend/sw.js))**:
  - Зберігає останній актуальний знімок даних у `read_cache` (зокрема `/auth/me`, об'єкти, генератори, склади, пули каністр, графіки ТО), щоб перезапуск PWA без інтернету не скидав сесію й дозволяв переглядати об'єкт і створювати операції.
  - Постановляє операції запуску/зупинки/ручного журналу, заправки, прийому/відправки/повернення каністр, ТО та несправностей у чергу `mutation_queue` з оптимістичним локальним перерахунком залишків у кеші та автоматичною FIFO-синхронізацією при відновленні зв'язку (`online` / автозапуск).
- **Індикатор зв'язку та ручне вирішення конфліктів ([`frontend/index.html`](frontend/index.html), [`frontend/styles.css`](frontend/styles.css))**:
  - У шапці додано статус-пігулку `#headerOfflineSyncBadge` та банер `#offlineSyncBanner`; у модалці `#modalOfflineQueue` реалізовано зведені плитки статусу, вирівняні кнопки дій (`.btn-secondary`, `.btn-oq-chip`), перегляд черги, завантаження актуального стану з сервера при конфлікті (`HTTP 400/404/409/422`), вбудоване редагування полів із генерацією нового `idempotency_key` і повторною відправкою, повтор «як є» або видалення застарілого запису (`sd-gen016-v5.5.1`).

## [v5.4.4] — 2026-11-11
### 🛢️ Уніфікація прийому палива в каністрах, коригування аудиту та виправлення UI форм
- **Єдина логіка оприбуткування палива ([`schemas/fuel.py`](backend/app/schemas/fuel.py), [`canister_service.py`](backend/app/services/canister_service.py), [`frontend/index.html`](frontend/index.html), [`frontend/js/fuel.js`](frontend/js/fuel.js))**:
  - Усунено дублювання «+ Оприбуткувати (Бензовоз)» vs «Привезли каністри»: усі кнопки прийому палива (Дашборд, вкладка «Паливо», рядок пулу каністр) відкривають єдину уніфіковану форму прийому каністр (`POST /api/v1/fuel/canisters/{id}/receive`, `source="auto"`).
  - Списання вільної тари при прийомі виконується автоматично: спершу каністри зі статусу «На АЗС», далі з «Порожніх»; система сама обчислює літри (`N × номінал`) та вартість (авторозрахунок WOG/OKKO або сума чека), залишаючи обов'язковими поля «Хто доставив» і «Номер чека» для звітності; при створенні нового пулу лічильники каністр автоматично попередньо заповнюються із поточного залишку складу.
- **Системні коригування аудиту для каністр ([`api/v1/adjustments.py`](backend/app/api/v1/adjustments.py), [`canister_service.py`](backend/app/services/canister_service.py), [`frontend/js/audit-reports.js`](frontend/js/audit-reports.js))**:
  - Коригування `FuelStock.current_balance_l` суперадміністратором автоматично розкладає новий залишок на повні каністри (`full_count`) та резерв (`reserve_liters`) з жорстким обмеженням фізичної місткості закріплених каністр і журналюванням операції `POOL_ADJUSTMENT`.
  - Додано сутність `CanisterPool` («Пул каністр») безпосередньо в `POST /api/v1/adjustments` та інтерфейс аудиту (`full_count`, `empty_count`, `away_refill_count`, `reserve_liters`) з автоматичною синхронізацією `FuelStock.current_balance_l`.
- **Виправлення верстки модальних вікон ([`frontend/styles.css`](frontend/styles.css), [`frontend/index.html`](frontend/index.html), [`frontend/sw.js`](frontend/sw.js))**:
  - Додано `.modal-compact`, вирівнювання `.form-row-2` / `.form-row-3` (`align-items: end`, колапс у 1 колонку на вузьких екранах), фіксований `.modal-header` при прокрутці, стилі `.checkbox-row` та оновлено Service Worker кеш до `sd-gen016-v5.4.4`.

## [v5.4.3] — 2026-11-11
### 📊 Етап 3: Єдиний блок оцінки та запасу палива на Дашборді
- **Виділений блок «⛽ Оцінка та запас палива» (`#fuelAssessmentPanel`, [`index.html`](frontend/index.html), [`dashboard.js`](frontend/js/dashboard.js), [`styles.css`](frontend/styles.css))**:
  - Відображає в одному місці автономність у баку генератора (`~год`), сукупний запас об'єкта (бак + повні каністри + резервна ємність / склад ГСМ) та готовність до поточного/найближчого відключення і сумарного добового навантаження YASNO (залишок сьогодні + завтра).
- **Усунення дублювання в інших картках ([`dashboard.js`](frontend/js/dashboard.js), [`yasno.js`](frontend/js/yasno.js), [`fuel.js`](frontend/js/fuel.js), [`sw.js`](frontend/sw.js))**:
  - У картці «Бак генератора» залишено лише фактичний рівень і відсоток заповнення (`#cardTankCapSub`) без повтору прогнозних годин;
  - З картки «Графік відключень YASNO» винесено банер оцінки палива до єдиного блоку `#fuelAssessmentPanel` (`sd-gen016-v5.4.3`).

## [v5.4.2] — 2026-11-11
### 🛢️ Етап 2: Облік пулів каністр та резервної ємності (`011_canister_pools.py`)
- **Модель пулів каністр та журнал руху ([`models/canister.py`](backend/app/models/canister.py), [`alembic/versions/011_canister_pools.py`](backend/alembic/versions/011_canister_pools.py))**:
  - Додано таблиці `canister_pools` (`total_count`, `full_count`, `empty_count`, `away_refill_count`, `reserve_liters < canister_volume_l`) та `canister_transactions` (історія кожної операції зі знімком до/після).
- **Бізнес-логіка резервування першим ([`services/canister_service.py`](backend/app/services/canister_service.py), [`services/fuel_service.py`](backend/app/services/fuel_service.py))**:
  - Залишок відкритої каністри переливається в наземну резервну ємність (`reserve_liters`), тож каністра одразу переходить у `empty_count` для відправки на АЗС.
  - При заправці бака генератора паливо з резерву списується першим (`min(reserve, liters)`), далі відкриваються повні каністри; `FuelStock.current_balance_l` автоматично синхронізується із пулами каністр.
  - Додано API-ендпоінти `/api/v1/fuel/canisters*` (`dispatch`, `receive` з опційним авто-чеком WOG/OKKO, `return-empty`, CRUD пулів, журнал транзакцій), підтримку в бекапах та очищенні БД.
- **PWA-інтерфейс каністр ([`frontend/index.html`](frontend/index.html), [`frontend/js/fuel.js`](frontend/js/fuel.js), [`frontend/sw.js`](frontend/sw.js))**:
  - У вкладці «Паливо» додано панель керування пулами каністр, кнопки швидких операцій (`📤 На АЗС`, `📥 Привезли`, `↩️ Повернути`), живий передперегляд списання резерву й каністр у модалці заправки бака та журнал руху каністр (`sd-gen016-v5.4.2`).

## [v5.4.1] — 2026-11-11
### 🔐 Етап 1 технічного фундаменту: Персистентна безпека, Async I/O та Модуляризація JS (`010_security_persistence.py`)
- **Персистентний захист сесій та brute-force у БД (`models/security.py`, `alembic/versions/010_security_persistence.py`, `auth_security_service.py`)**:
  - Відкликані JWT-токени (`/logout`, таблиця `revoked_tokens`) та лічильники невдалих спроб входу / відновлення пароля (таблиця `auth_attempts`) тепер зберігаються в PostgreSQL/SQLite, не скидаються при рестарті контейнера та перевіряються також на захищеному роуті `/uploads/{file_path:path}`.
- **Неблокуючий async I/O та усунення deprecation-попереджень Python 3.14**:
  - Переведено перевірку пароля при скиданні системи (`/system/reset`) у `asyncio.to_thread`;
  - Парсери цін АЗК WOG і OKKO (`settings_service.py`) переведено на асинхронний `httpx.AsyncClient` з єдиними парсерами `_parse_wog_fuel_html` / `_parse_okko_fuel_html`;
  - Уніфіковано `utc_now()` у `database.py` та замінено застарілий `datetime.datetime.utcnow` у `SystemSetting`, що усунуло ~12 705 `DeprecationWarning` під Python 3.14.
- **Прискорення тестів, CI/CD та UX-узгодження**:
  - Адаптивна вартість `bcrypt` (`rounds=4` у `APP_ENV=testing`, `rounds=12` у проді) скоротила час виконання `pytest` у ~3 рази;
  - Додано GitHub Actions workflow `.github/workflows/ci.yml` (Python 3.12 / 3.14 `pytest`, перевірка HTML/JS синтаксису та гігієни секретів);
  - Вирівняно ліміт UI нагадувань ТО (`#notifMaxMaintPerDay` `max="2"` згідно правил).
- **Модуляризація клієнтської логіки (`frontend/js/*.js`)**:
  - Монолітний `frontend/app.js` (7 530 рядків) розділено на 12 логічних модулів (`core.js`, `theme-format.js`, `auth-nav.js`, `dashboard.js`, `fuel.js`, `operations.js`, `audit-reports.js`, `admin.js`, `backups.js`, `notifications.js`, `yasno.js`, `weather-alerts.js`) із синхронізацією кешу Service Worker (`sd-gen016-v5.4.1`).

## [v5.4.0] — 2026-11-11

### 🔔 Надійні WebPush сповіщення, Live Watcher та Повітряні тривоги (`177eac5`)
- **Виправлення доставки WebPush (`notification_service.py`)**:
  - Підтримка PEM-ключів VAPID (`Vapid.from_pem`), параметри `ttl=14400`, `timeout=8.0`, заголовок `Urgency: high`;
  - Покращена фільтрація підписок за `facility_id` користувача/підписки та дедуплікація в `NotificationLog`.
- **Автосинхронізація та Live Browser Watcher (`sw.js`, `app.js`)**:
  - Обробка події `pushsubscriptionchange` у Service Worker для автоматичного оновлення підписки при ротації ключів;
  - Трансляція `PUSH_NOTIFICATION_RECEIVED` у відкриті вкладки та живий клієнтський моніторинг `GET /api/v1/notifications/logs` із дедуплікацією за тегом `sd-log-{id}`;
  - Підвищена вібрація та `requireInteraction: true` для критичних подій (`AIR_ALERT_START`, `CRITICAL_FAULT`, `LOW_FUEL`, `GENERATOR_SAFETY_STOP`).
- **Миттєві сповіщення про Повітряні тривоги та Відбої (`alert_service.py`)**:
  - Фоновий цикл `run_air_alert_checker_loop` (кожні 45 с) у `main.py` відстежує переходи `GREEN ↔ YELLOW/RED` із відновленням стану після рестарту сервера через `NotificationLog`;
  - Окремі сповіщення `AIR_ALERT_START` (із вказівкою працюючих генераторів) та `AIR_ALERT_END` (із тривалістю тривоги);
  - Нові перемикачі у вкладці сповіщень і API `/api/v1/notifications/settings`: `notify_yasno_outages`, `notify_air_alerts`, `notify_air_alert_end`.
- **Живий контроль палива та ТО під час роботи (`operational_guard_service.py`, `generator_service.py`)**:
  - Оцінка залишку палива в баку та наближення ТО під час активного робочого циклу та при автостопі.
- **Повна синхронізація документації, політик та правил на сайті (`v5.4.0`)**:
  - Оновлено всі 13 документів у `docs/`, `README.md`, `AGENT.md`, `RELEASE_NOTES_v5.4.0.md`, а також 4 модальні вікна політик і правил на сайті (`frontend/index.html`) та версію FastAPI/BackupManifest/тестів до `5.4.0`.

## [v5.3.1] — 2026-11-10
- **Стабільний блок готовності палива YASNO (`6724f9e`)**:
  - Блок «Паливо в баку ↔ YASNO» тепер відображається в картці YASNO в усіх станах (`DEFINITE`, `PROBABLE`, `NOT_PLANNED` / без відключень);
  - У відповідь `yasno_service.py` додано структуровані поля `is_outage_now` та `current_outage` (початок, кінець, залишок хвилин).

## [v5.3.0] — 2026-11-10
- **Alembic commit fix & Ops UX (`2ed685d`)**:
  - Виправлено фіксацію транзакцій міграцій у `backend/alembic/env.py` (`await connection.commit()`);
  - Додано розрахунок готовності палива до графіка YASNO, банер зимового ДП (`genDieselFrostBanner`, `< 0°C`), неблокуючий банер безпеки при червоній тривозі (`redAlertRunSafetyBanner`) та клієнтську пагінацію таблиць (10 записів на сторінку).

## [v5.1.0 – v5.2.0] — 2026-11-05 — 2026-11-10
- **Dual-Provider Alert Fusion та Worst-Case Insurance Hold (`377a56a`, `80a4852`)**:
  - Паралельна взаємна звірка `alerts.in.ua` (HTTP 304 `If-Modified-Since`, 15 с) та `api.ukrainealarm.com` (60 с, backoff при 429) за правилом найгіршого сценарію («Страхування відбою»);
  - Ієрархічне зіставлення громада/місто/район → область, синоніми міст (`CITY_SEARCH_ALIASES`), усунення дублювання міста й області (`8c10d35`), згортана легенда загроз.
- **5-денний прогноз OpenWeatherMap (`a886717`, `ffa56e4`)**:
  - Паралельне завантаження поточного прогнозу та `/data/2.5/forecast` на 5 днів, проактивні попередження про заморозки, виправлення `updated_at` у `Europe/Kyiv`.
- **Повностекова оптимізація продуктивності (`0e69772`)**:
  - Паралелізація API-водоспадів на фронтенді, пакетний запит `get_generators_cooldown_map`, винесення `bcrypt` у `asyncio.to_thread`, Gzip та кешування `/frontend/` у `docker/nginx.conf`, стиснення PNG-іконок PWA.

---

## [v5.0.0] — 2026-11-04

### 🚨 Повітряна безпека та раннє сповіщення (`BR-ALERT-01`, `alerts.in.ua`, `ukrainealarm.com`)
- **Каскадна інтеграція зовнішніх провайдерів тривог (`alert_service.py`)**:
  - Первинне опитування офіційного шлюзу `alerts.in.ua` з Bearer-токеном авторизації;
  - Автоматичне перемикання на вторинний резервний провайдер `api.ukrainealarm.com` при тайм-аутах чи збоях первинного;
  - Автономний детермінований `MockAlertProvider` для офлайн-роботи та локального тестування;
  - Кешування статусу тривоги в оперативній пам'яті (`ALERTS_CACHE_SECONDS`, за замовчуванням 30 с) для мінімізації навантаження на шлюзи.
- **Диференціація рівнів небезпеки та типів загроз**:
  - `green` (Відбій): штатний режим роботи, дозволені всі сервісні операції;
  - `yellow` (Підвищена готовність): загроза ударних БПЛА («Шахеди») або активність авіації;
  - `red` (Повітряна тривога): ракетний удар, балістичні ракети, зліт МіГ-31К («Кинджал»), скидання КАБ, артобстріл.
- **Високопомітна анімація на об'єкті**:
  - Додано стробоскопічний аварійний маяк (`alertEmergencyBeacon` / `alertEmergencyBeaconLight`) із пульсуючим багряно-червоним ареолом;
  - Анімація вібрації сирени (`alertSirenWiggle`) та пульсуюча червона точка статусу (`alertDotFlash`);
  - Інтерактивна модальна шторка цивільної безпеки з оперативним протоколом дій персоналу.

### 🌤️ Метеорологічна телеметрія та інженерні поради (`BR-WEATHER-01`, `OpenWeatherMap API`)
- **Автоматичне визначення локації та прогноз (`weather_service.py`)**:
  - Інтелектуальний парсинг назви населеного пункту з фізичної адреси об'єкта (`facility.address`) з геокодуванням координат (Дніпро, Самар, Київ, Буча, Львів, Харків, Одеса, Запоріжжя тощо);
  - Отримання поточної температури (°C), відчутної температури, вологості (%), швидкості вітру (м/с) та атмосферного тиску через OpenWeatherMap API;
  - In-memory кешування результатів (`WEATHER_CACHE_MINUTES`, за замовчуванням 15 хв).
- **Сезонні рекомендації для генератора**:
  - Мороз (< 0°C): використання зимового палива, прогрів 3–5 хв без електричного навантаження, перевірка АКБ;
  - Оптимально (0°C .. +25°C): штатний регламент експлуатації;
  - Спека (> +25°C): вільний приплив повітря, захист від сонця, скорочення інтервалу перевірки рівня оливи.

### 🛡️ Польове зміцнення та захист від дефектів (Field-tested Defect Hardening)
- **Запобіжник повторного пуску після зупинки (`BR-GEN-14`)**:
  - Впроваджено обов'язкову 60-секундну паузу охолодження після зупинки генератора;
  - Серверне відхилення пуску з кодом `400 Bad Request` («Двигун охолоджується, зачекайте...»);
  - Відображення лічильника зворотного відліку на кнопці запуску на фронтенді.
- **Уніфікований облік запасів пального (`BR-FUEL-09`)**:
  - Знято обмеження прив'язки виключно до брендів WOG та OKKO;
  - Повноцінна підтримка складів типу «Власні запаси / Каністри / Склад ГСМ» із можливістю оприбуткування від довільних постачальників за фактичними цінами.
- **Календарна безперервність звітів Excel (`BR-REPORT-05`)**:
  - Усі звітні періоди експортуються без пропусків дат: дні простою присутні з нульовими показниками мотогодин та коректним перенесенням залишків палива.
- **Структурований україномовний аудит**:
  - Людинозрозумілий переклад дій (`ua_action`, `ua_entity`) з відображенням літражу, типу палива, назви генератора та IP-адреси клієнта.

### 📱 Мобільна довершеність (Mobile Perfection v5.0.0 & Responsive UX)
- **Представницька 2-рядна шапка**: верхній рядок для логотипу, назви та профілю користувача; нижній рядок — для погодного віджета та індикатора повітряної тривоги.
- **Захист від горизонтального зсуву**: `max-width: 100vw; overflow-x: hidden; width: 100%`.
- **Повноекранні модальні Bottom Sheets на смартфонах**: ширина `100vw` без виходу за межі екрана.
- **WCAG AA контрастність**: оновлені колірні схеми для темної та світлої тем.

---

## [v4.7.0] — 2026-11-02

### Ядро часових поясів, налаштувань та Web Push (`TIME-01..06`, `INF-35..43`, `NOTIF-01..10`)
- **Математичне ядро розкладів (`backend/app/core/timezone.py`)**:
  - Підтримка як денних, так і перехідних через північ розкладів із напіввідкритими інтервалами `[start, end)` та fail-closed валідацією формату `HH:MM`;
  - Узгоджене обчислення локальних меж доби (`get_local_day_bounds_utc`) для кожного часового поясу об'єкта.
- **Безпека та атомарність налаштувань (`backend/app/services/settings_service.py`)**:
  - Збереження налаштувань не перезаписує індивідуальні розклади генераторів без явного прапорця `apply_to_all_generators=True`;
  - Повне відв'язування типу пального `ГАЗ` від `А-92`, валідація числових параметрів (`INF-43`), атомарність `settings_reset` та перерахунок `next_due_hours` при масовому оновленні міжсервісного інтервалу ТО.
- **Стійкість та безпека Web Push (`backend/app/services/notification_service.py`)**:
  - Автоматичне відновлення пошкоджених або неповних VAPID-ключів без дублювання рядків у БД;
  - IDOR-захист підписок (`PushSubscription`) та безпечна відписка пристроїв;
  - Добовий ліміт нагадувань про ТО за локальним часом об'єкта та 3-годинний інтервал між сповіщеннями `LOW_FUEL`.

### Транзакційне зміцнення паливного модуля (`FUEL-01..10`, Alembic `007`–`008`)
- **Точна фінансова та об'ємна арифметика (`Decimal` / `Numeric`)**:
  - Поля літрів переведено на `NUMERIC(10, 3)` (`0.001 л`), а грошові суми та ціни — на `NUMERIC(12, 2)` (`0.01 грн`) із округленням `ROUND_HALF_UP`.
- **Захист від гонок даних, ідемпотентність та ізоляція**:
  - Використання `SELECT ... FOR UPDATE` (`with_for_update()`) під час чеків, заправок і списань пального;
  - Унікальні ключі ідемпотентності `idempotency_key` для `fuel_receipts` та `fuel_transfers`;
  - Повна міжоб'єктна ізоляція складів ГСМ, чеків і заправок та м'яке архівування складів (`is_active = False`) зі збереженням історії.

### Комплексне зміцнення сервісу генераторів (`GEN-01..16`, Alembic `009`)
- **Атомарність життєвого циклу генератора (`backend/app/services/generator_service.py`)**:
  - Виключення дублювання активних сеансів `RUNNING`, перевірка пального на мінімальний цикл, блокування запуску при відкритих критичних аваріях та контроль простроченого ТО (`force_start_with_maintenance`);
  - Єдина транзакція зупинки та `manual-run` зі списанням пального через `consume_generator_fuel()` і фіксацією дефіциту (`FUEL_DEFICIT_DETECTED`).
- **М'яке архівування генераторів (`ARCHIVED`)**:
  - Додано поля `generators.is_active`, `generators.archived_at` та `generator_runs.idempotency_key`; генератори з історією переводяться в `ARCHIVED` замість фізичного видалення.

### Крос-модульний аудит безпеки, логіки та звітності
- **Несправності та ТО (`fault_service.py`, `maintenance_service.py`)**:
  - Автоматична аварійна зупинка працюючого генератора при реєстрації `CRITICAL` несправності;
  - Коректне відновлення статусу генератора з `FAULTY` у `STOPPED` / `MAINTENANCE_REQUIRED` при закритті критичних заявок (включно з прямим переходом `NEW -> RESOLVED`);
  - Жорстка прив'язка до `facility_id` при виборі генератора та новий ендпоінт `GET /api/v1/maintenance/schedules`.
- **Системні коригування (`adjustments.py`)**:
  - Усунено `AttributeError` при коригуванні `MaintenanceSchedule`, додано контроль верхньої межі `tank_capacity_l`, заборону ручного переходу в `RUNNING` та автоперерахунок статусу ТО.
- **Звітність та синхронізація версії (`v4.7.0`)**:
  - Мультигенераторна агрегація у зведених звітах (`GET /api/v1/reports/summary`) та експорті Excel (`GET /api/v1/reports/export-excel`) для об'єктів із кількома генераторами;
  - Обчислення меж дат звітів у локальному часовому поясі об'єкта;
  - Узгоджено версію системи до `v4.7.0`, а тестовий набір розширено до **159 автоматизованих тестів** (100% успіху).

---

## [v4.6.0] — 2026-11-02

### Аудит та зміцнення Docker-інфраструктури (INF-12 – INF-18)
- **Коректне розкриття `FORWARDED_ALLOW_IPS` (INF-12)**:
  - Виправлено передачу змінної оточення в `docker-entrypoint.sh` через подвійні лапки замість одинарних, усунувши передачу буквального рядка `${FORWARDED_ALLOW_IPS...}` в Uvicorn.
  - Налаштовано безпечне значення за замовчуванням `127.0.0.1,172.16.0.0/12` для взаємодії зі зворотним проксі Nginx.
- **Graceful Termination Uvicorn (INF-13)**:
  - Додано `exec` при запуску процесу Uvicorn в `docker-entrypoint.sh`, що гарантує статус PID 1 та негайну обробку сигналів SIGTERM/SIGINT без осиротілих процесів.
  - Забезпечено обов'язкове виконання міграцій Alembic до старту веб-сервера із зупинкою запуску при помилках міграції.
- **Мінімізація привілеїв контейнера (`appuser`, INF-14)**:
  - Переведено виконання контейнера на виділеного непривілейованого користувача `appuser` (UID: 10001, GID: 10001).
  - Захищено вихідний код бекенду від модифікації в рантаймі; права на запис ізольовано виключно для робочих директорій: `/app/data`, `/app/uploads`, `/app/backups`, `/app/alembic/versions`.
- **Двоетапні хелсчеки Liveness та Readiness (INF-15)**:
  - Розділено перевірки стану: легковаговий зонд `/api/health/liveness` для моніторингу процесу сервера та глибокий зонд `/api/health/readiness` (та `/api/health`) із тестом з'єднання з базою даних (`SELECT 1`).
- **Захист контексту збірки (`.dockerignore`, INF-16)**:
  - Додано надійне виключення файлів секретів `.env*`, службових каталогів `.git`, артефактів тестування `.pytest_cache`, `tests`, `docs` та локальних архівів резервних копій із образу Docker.
- **Надійність оркестрації Docker Compose (INF-17/INF-18)**:
  - Додано перевірку стану БД у `docker-compose.yml` (`depends_on: db: condition: service_healthy`) для гарантії готовності PostgreSQL перед стартом бекенду.

### Інтеграція мережі АЗК OKKO та подвійний роздрібний моніторинг (Dual Retail Fuel)
- **Парсер роздрібних цін мережі OKKO**:
  - Розроблено асинхронний скрейпер роздрібних цін АЗК OKKO (`https://www.okko.ua/fuels`) поруч із діючим парсером мережі WOG.
  - Серверний кеш роздрібних цін із автоматичним оновленням та аварійним кешем (Fallback Cache).
- **Прив'язка мережі АЗС до об'єктів та чеків**:
  - Додано поле `facilities.default_fuel_provider` (`wog` або `okko`) у створення та редагування об'єктів;
  - Додано індивідуальний вибір мережі АЗС у формі оприбуткування палива (`fuel_receipts.fuel_provider`) із динамічними підказками цін;
  - Інформаційні кольорові бейджі в історії надходжень: зелений `АЗК WOG` та бурштиновий `АЗК OKKO`.
- **Інтерфейс табло цін**:
  - Інтерактивні вкладки вибору мережі [🟢 АЗК WOG] та [🟡 АЗК OKKO] у системних налаштуваннях із відображенням живих роздрібних цін та договірних ставок.
  - Підтримка вибіркової актуалізації цін через ендпоінт `POST /api/v1/system/fuel-prices/refresh?provider=wog|okko`.
- **Звітність Excel**:
  - На аркуш «Рух палива» книги Excel додано окрему колонку «Мережа АЗС».

### Надійність планувальника резервного копіювання (Backup Stability)
- **Усунення хибних спрацювань автобекапу при рестарті**:
  - Планувальник автобекапів налаштовано на строге 15-хвилинне вікно запуску (`0 <= diff_minutes <= 15`);
  - Додано збереження дати останнього виконання (`backup_last_auto_run_date`) у налаштуваннях БД, що унеможливлює повторне створення бекапів під час перезавантаження контейнера в межах тієї ж доби.
- **Контрольні суми SHA-256**:
  - Для кожного створеного архіву `.zip` поруч автоматично формується зовнішній файл `.sha256` для швидкої верифікації цілісності.
- **Політика збереження повних бекапів (Protected Full Backups)**:
  - Захист критичних повних знімків системи від випадкового видалення під час планової ротації.

### Нормативна відповідність та інтерфейсні виправлення
- **Виправлення модального вікна Data Governance & SLA**:
  - Усунено невідрендерені KaTeX-формули `$\le 24$` та `$\le 2$`, замінено на чисті стандартизовані символи `≤ 24` та `≤ 2`.
  - Виправлено помилкове зазначення формату `tar.gz` на фактичний формат `.zip` із контрольними сумами SHA-256 та захистом від Zip Slip/Zip Bomb.
- **Стійкість міграцій Alembic**:
  - Розширено розмірність стовпця `alembic_version.version_num` до VARCHAR(64) для усунення помилок обрізання хешів ревізій.
- **Синхронізація версії та розширення тестів**:
  - Узгоджено версію системи до `v4.6.0` у FastAPI, маніфестах бекапів та нормативній документації;
  - Тестовий набір розширено до **109 автоматизованих тестів** (100% успіху).

---

## [v4.5.3] — 2026-10-26

### Інтеграція графіків відключень YASNO та проактивні сповіщення (YASNO Outages Integration & Push Alerts)
- **Підключення до офіційного мікросервісу розкладів YASNO**:
  - Розроблено асинхронний бекенд-сервіс `yasno_service.py`, що взаємодіє з API `app.yasno.ua/api/blackout-service/public/shutdowns/regions/{region_id}/dsos/{dso_id}/planned-outages`.
  - Забезпечено стійкість до блокувань WAF Cloudflare/Incapsula, парсинг хвилинних тайм-слотів доби (0–1440 хв) та генерацію погодинної карти (24 години: 00:00–24:00).
  - Впроваджено серверне кешування (TTL 15 хв) для мінімізації навантаження та миттєвої віддачі розкладів клієнтам.
- **Багатооб'єктне налаштування груп та операторів (Multi-site Groups & DSO)**:
  - Розширено модель `Facility` та схеми валідації полями `yasno_enabled`, `yasno_region_id`, `yasno_dso_id`, `yasno_group`.
  - Черга та підгрупа відключення закріплюються індивідуально за кожним об'єктом/адресою (наприклад, група `3.2` та ДТЕК Дніпровські електромережі для об'єкта у м. Самар).
  - Підтримка вибору операторів розподілу: ДТЕК Дніпровські електромережі (код 301), ЦЕК (код 303), ДТЕК Київські електромережі (код 902) та діапазону груп `1.1`–`6.2`.
- **Проактивні Web Push сповіщення операторам за 30 хвилин**:
  - Реалізовано фоновий форекаст-цикл `run_yasno_checker_loop` у `yasno_service.py`, який відслідковує наближення відключень (`DEFINITE` або `PROBABLE`).
  - У вікні 25–35 хвилин до відключення операторам закріпленого об'єкта надсилається нативне Web Push сповіщення з таймером зворотного відліку та типом знеструмлення.
  - Впроваджено захист від дублювання сповіщень у межах однієї доби (`notified_slots`).
- **Інтерактивна плитка на дашборді та візуальна 24-годинна шкала**:
  - На головній сторінці додано картку-плитку `yasnoScheduleCard` із 24-годинною кольоровою шкалою: зелений (є світло), червоний (планове відключення), жовтий (ймовірне відключення).
  - Поточна година виділяється пульсуючим синім контуром та маркером `ЗАРАЗ`.
  - Відображається зворотний відлік до найближчого відключення та статус підключення до YASNO.
- **Оновлення кешу клієнта (PWA Asset Cache & Service Worker v4.9.7)**:
  - Версію кешу PWA додатку та статичних ресурсів підвищено до `v4.9.7` для миттєвого оновлення інтерфейсу в браузерах і на смартфонах (надалі, в межах цього релізу, послідовно до `v4.9.9`).
- **Розрізнення часу перевірки та часу публікації графіка YASNO**:
  - Відповідь `GET /api/v1/facilities/{id}/outage-schedule` доповнено полями `checked_at` (момент останнього звернення до YASNO у часовому поясі `Europe/Kyiv`) та `yasno_updated_on` (час публікації графіка оператором).
  - На плитці дашборда відображаються обидві позначки; кнопка оновлення має візуальний відгук (анімація обертання).
  - Ендпоінт повертає заголовок `Cache-Control: no-cache, no-store, must-revalidate`, щоб браузер і Service Worker не віддавали застарілий графік.
- **Сумісність міграції з PostgreSQL**: у міграції Alembic `004_add_yasno_fields.py` та схемах булеве поле `yasno_enabled` оголошується через `sa.false()` / коректний серверний default для PostgreSQL.
- **Посилення безпеки, надійності доставки та усунення хибних спрацювань (P1 / P2 Audit Fixes)**:
  - **Fail-closed санітизація історичних логів аудиту (`backend/app/main.py`)**: етапи `seed_initial_data()` та `sanitize_historical_audit_logs()` розділено на незалежні блоки життєвого циклу (`lifespan`). Якщо обов'язкове очищення старих секретів завершується помилкою, запуск сервера негайно блокується (`RuntimeError`).
  - **Вимкнення YASNO за замовчуванням для початкового об'єкта (`backend/app/main.py`, `init_service.py`)**: початковий об'єкт більше не отримує автоматичну групу `3.2` та ввімкнений моніторинг (`yasno_enabled = False`, `yasno_group = None`), доки адміністратор явно не підтвердить регіон, оператора розподілу та чергу для реальної локації.
  - **Персистентна дедуплікація та повторні спроби Web Push для YASNO (`yasno_service.py`)**: стан успішної доставки фіксується та перевіряється в БД (`NotificationLog`). Якщо `send_push_notification()` повернув `sent == 0`, часовий слот не блокується — система виконує до 3 повторних спроб у межах вікна 20–35 хв, а після перезапуску контейнера дублікати не надсилаються.
  - **Захист від повторної відправки щотижневого Email-звіту при рестарті Docker (`operational_guard_service.py`, `settings_service.py`)**: дата останньої відправки (`last_weekly_digest_date`) зберігається в БД (`system_settings`) та дублюється в `NotificationLog` (`EMAIL_DIGEST_WEEKLY`) і `AuditLog` (`WEEKLY_DIGEST_AUTO_SENT`), що повністю виключає повторну розсилку звіту після перезавантаження контейнера або оновлення коду в той самий день.
  - **Розширення санітизатора аудиту (`audit_service.py`)**: перелік `SENSITIVE_KEY_MARKERS` доповнено загальним маркером `key`, а також `encryption_key`, `access_key`, `auth_key`, `signing_key`, `master_key`, `session_key`, `client_secret`, `database_url`, `conn_str`, `connection_string`, `bearer`; додано маскування `old_value`/`new_value` для чутливих полів у коригуваннях.
  - **Синхронізація версії API (`4.5.3`)**: узгоджено версію `FastAPI(version="4.5.3")`, маніфест бекапів та нормативну документацію; тестовий набір розширено до 95 автоматизованих тестів.
- **Дрібні виправлення інтерфейсу та експорту**:
  - З випадаючих списків вибору групи прибрано застарілу підпис «(м. Самар)».
  - Назву 5-го аркуша Excel скорочено до **«Несправності та інциденти»** (ліміт Excel — 31 символ).

## [v4.5.2] — 2026-10-26

### Розмежування звітності та окремий експорт аудиту (Reports & Audit Governance)
- **Вилучення журналу дій аудиту з загального звіту Excel**:
  - Відповідно до вимог керівництва, з 5-го аркуша загального аналітичного звіту Excel (`GET /api/v1/reports/export-excel`) повністю видалено блок «2. Журнал операційного аудиту (останні ключові дії)».
  - 5-й аркуш оптимізовано та офіційно перейменовано на **«Журнал несправностей та інцидентів»**, де зосереджено виключно реєстр дефектів, поломок та статусів їх усунення.
- **Окремий спеціалізований звіт операційного аудиту та системних коригувань**:
  - Створено новий захищений ендпоінт `GET /api/v1/audit/export-excel` з доступом виключно для Головного суперадміністратора (`get_current_superadmin`).
  - Звіт формує книгу Excel (.xlsx) за стандартом ДСТУ 4163:2020 з 2-ма аркушами: **«Журнал дій аудиту»** та **«Системні коригування»** (лічильників мотогодин та залишків палива).
  - Усі текстові комірки та формули надійно санітизуються проти CSV/Excel Formula Injection (`=`, `+`, `-`, `@`, `\t`, `\r`).
- **Модальне вікно експорту аудиту з періодами вибірки**:
  - У розділ «Журнал аудиту та Системні коригування» додано кнопку `📊 Експорт аудиту в Excel` із модальним вікном вибору періоду дат (Сьогодні, 7 днів, 30 днів, Весь час).
- **Оновлення кешу клієнтських додатків (PWA Asset Cache & Service Worker v4.9.6)**:
  - Версію кешу PWA та статичних активів (`styles.css`, `app.js`) підвищено до `v4.9.6`, що забезпечує миттєве скидання застарілого кешу в браузерах.
  - Маршрут сервера `/sw.js` доповнено заголовками `Cache-Control: no-cache, no-store, must-revalidate` для гарантованої доставки оновлень клієнтам.
  - Додано пряму ініціалізацію та обробники кліку для надійного відкриття модального вікна аудиту.

## [v4.5.1] — 2026-10-25

### Посилення безпеки, захист облікових даних та цілісність даних (Security & Data Integrity Hardening)
- **Усунення витоку паролів SMTP через журнал аудиту (P0)**:
  - Реалізовано централізований рекурсивний механізм санітизації `sanitize_audit_details` у `audit_service.py`, що маскує будь-які секретні ключі (`password`, `secret`, `token`, `key`, `credential`) значенням `[REDACTED]`.
  - Маршрут оновлення налаштувань `system.py` та сервіс аудиту гарантують, що відкриті паролі ніколи не потрапляють у `details_json` таблиці `audit_logs`.
  - Захист на виході (Defense-in-depth): маршрут `GET /api/v1/audit` додатково санітизує вихідні JSON-деталі.
  - Автоматична санітизація історичних записів: фонова підпрограма при старті системи сканує БД та безпечно маскує раніше збережені паролі.
- **Заборона передавання SMTP-облікових даних без TLS (P0)**:
  - Впроваджено суворий принцип Fail-Closed у `email_service.py`: перед автентифікацією перевіряється розширення `server.has_extn("starttls")`.
  - Будь-який збій узгодження STARTTLS або помилка сертифіката негайно перериває сесію та блокує виклик `login()`, унеможливлюючи передавання паролів відкритим текстом.
  - Для режиму SSL використовується клієнт `smtplib.SMTP_SSL` із валідацією сертифікатів за замовчуванням.
- **Сувора ізоляція між об'єктами та блокування неприкріплених користувачів (P1)**:
  - Виправлено модель контролю доступу у `deps.py`: для користувача без закріпленого `facility_id` (`None`) запити до об'єктів та генераторів повертають `403 Forbidden` із поясненням: *«Ваш обліковий запис очікує закріплення за об'єктом адміністратором»*.
  - Список `GET /api/v1/facilities` для неприкріпленого користувача повертає порожній перелік `[]`.
  - Додано міжоб'єктний запобіжник у `fuel_service.py`: заправка бака генератора зі складу ГСМ дозволена лише якщо генератор та склад належать до одного й того ж об'єкта.
- **Обмеження видалення об'єкта виключно SuperAdmin (P1)**:
  - Ендпоінт `DELETE /api/v1/facilities/{id}` переведено на залежність `get_current_superadmin` та сувору перевірку `current_user.is_superadmin`. Звичайним адміністраторам операцію заборонено (`403 Forbidden`).
  - Збагачено аудиторський слід `FACILITY_DELETED` детальним фіксуванням списку видалених генераторів, складів та відкріплених користувачів.
- **Серверна валідація цілісності системних налаштувань та атомарність (P1)**:
  - У `settings_service.py` додано сувору перевірку прив'язки: генератор або склад ГСМ із `facility_id=None` категорично відхиляються при спробі призначити їх за замовчуванням для обраного об'єкта.
  - Заборонено встановлення дефолтного генератора чи складу без попереднього визначення самого об'єкта за замовчуванням.
  - Гарантовано повну транзакційну атомарність: публікація змін в оперативну пам'ять `RUNTIME_SETTINGS` виконується виключно після успішного завершення `await db.commit()`, із безпечним `rollback()` у разі збою транзакції.
- **Блокування запуску в Production із дефолтними секретами (Config Hardening)**:
  - У `config.py` реалізовано обов'язковий fail-closed контроль: при `APP_ENV=production` наявність стандартного `APP_SECRET_KEY` (< 32 символів) або публічного `INITIAL_ADMIN_PASSWORD` спричиняє негайну фатальну зупинку сервера (`RuntimeError`).
  - Тестові та розробницькі середовища захищені від випадкових блокувань.
- **Запобіжник запуску з порожнім баком (Fuel Deficit Safeguard)**:
  - Дозвіл пуску при розрахунковому нулі з огляду на фактичну економію палива;
  - Червоний пульсуючий ореол навколо кнопки запуску та попереджувальний трикутник `⚠️ ▶ ЗАПУСТИТИ ГЕНЕРАТОР`;
  - Бурштиновий бейдж-підказка `ПОТРІБНА ЗАПРАВКА` на картці швидкої заправки бака.

---

### Багатооб'єктне закріплення та каскадне очищення (Multi-site Default Chain & Cascade Delete)
- **Стартовий ланцюжок за замовчуванням (Default Chain Binding)**:
  - Адміністративне встановлення жорсткої зв'язки: **Об'єкт за замовчуванням** ➔ **Генератор за замовчуванням** ➔ **Склад ГСМ за замовчуванням**.
  - Нові системні поля в `SystemSettings`: `default_facility_id`, `default_generator_id`, `default_fuel_stock_id`.
  - Захист від людських помилок: при виборі об'єкта генератор та склад автоматично синхронізуються; для операторів заблоковано вибір незв'язаних генераторів або складів.
- **Безпечне каскадне видалення об'єкта (Cascade Facility Deletion)**:
  - Ендпоінт `DELETE /api/v1/facilities/{facility_id}?cascade=true` (доступний виключно SuperAdmin).
  - Повне каскадне очищення пов'язаних складів ГСМ, генераторів, сеансів напрацювання, записів ТО, дефектів та записів інвентаризаційних коригувань (`system_adjustments`) без виникнення помилок цілісності зовнішніх ключів (`ForeignKeyViolationError`).
  - Обов'язкова фіксація факту видалення у незмінному реєстрі системного аудиту (`FACILITY_DELETE`).
- **Таргетування щотижневого звіту Excel (Weekly Digest Scoping)**:
  - Формування книги Excel (`.xlsx`) та автоматична розсилка керівництву тепер генеруються суворо за вибраним цільовим об'єктом (`default_facility_id` або переданим `facility_id`), запобігаючи надсиланню порожніх звітів по першому системному об'єкту.

### Ергономіка інтерфейсу, Адаптивність та Мобільна навігація (Responsive UX & PWA v4.9.3)
- **Адаптивний рідкий десктопний макет (Fluid Tiered Container)**:
  - Плавне динамічне розширення контейнера робочої області (`1200px` ➔ `1260px` ➔ `1360px` ➔ `1420px`) на дисплеях із роздільною здатністю 1280px, 1440px та 1680px+.
  - Ідеальне горизонтальне центрування перемикача об'єктів та генераторів у шапці для всіх екранів ≥ 769px.
- **Мобільна нижня панель навігації (Bottom Navigation Bar)**:
  - Сенсорно оптимізована фіксована нижня панель із 5 ключовими вкладками (*Головна, Паливо, ТО, Несправності, Меню*) для комфортного перемикання однією рукою біля генератора.
- **Оновлення брендингу та назви**:
  - Назву системи в шапці оновлено до зрозумілого та офіційного найменування: **⚡ Service Desk Генератора**.
  - Заголовок адмінки приведено до лаконічного та професійного вигляду: **⚙️ Системні налаштування**.

### Обслуговування, Журнал сповіщень та Реструктуризація налаштувань (Maintenance & Admin Controls)
- **Скидання лічильника регламентного ТО сервісною службою**:
  - Кнопка **«⚙️ Скидання лічильника ТО»** та спеціалізоване модальне вікно (доступне лише адміністраторам та суперадміністраторам).
  - Можливість ретроспективного внесення фактичних мотогодин виконання робіт (`operating_hours`), вартості, використаних матеріалів та номера акту сервісу.
  - Автоматичне зміщення дедлайну наступного ТО на `+300 год` (або норматив генератора) та скидання попереджувального статусу `MAINTENANCE_REQUIRED` до робочого `STOPPED`.
- **Очищення історії відправлених сповіщень**:
  - Кнопка **«🗑️ Очистити історію»** у блоці надісланих сповіщень.
  - Ендпоінт `DELETE /api/v1/notifications/logs` із перевіркою прав адміністратора, ізоляцією за об'єктом та обов'язковим записом у журнал аудиту (`NOTIFICATION_LOGS_CLEARED`).
- **Логічна реструктуризація панелі адміністратора**:
  - Розбиття налаштувань на 5 послідовних пронумерованих карток.
  - Перенесення кнопки **«🟢 Оновити ціни АЗК WOG»** безпосередньо в картку табло цін WOG.
  - Перенесення деструктивної кнопки **«🧹 Очищення даних / Скидання БД»** у картку резервних копій (SuperAdmin Only).

### Тестування та надійність
- Розширено автоматизований набір тестів: додано тести каскадного видалення об'єктів, валідації ланцюжків за замовчуванням, скидання лічильника ТО із довільними годинами та очищення журналу сповіщень.
- Загальна кількість тестів зросла до **72 тестів із 100% успішним проходженням**.

---

## [v4.4.0] — 2026-10-24

### Універсальна система сповіщень на Email та Резервування (Universal Email & SMTP Failover)
- **100% безкоштовний поштовий шлюз без покупки власного домену**:
  - Реалізовано пряме підключення через SMTP з підтримкою STARTTLS (порт 587) та прямого SSL (порт 465) засобами стандартної бібліотеки Python (`smtplib`, `email.message.EmailMessage`) без сторонніх платних API.
  - Налаштовано роботу з безкоштовними поштовими провайдерами: Основний SMTP — Gmail (паролі додатків), Резервний SMTP — Ukr.net (паролі зовнішніх програм).
- **Автоматичне перемикання при відмові (SMTP Failover)**:
  - При виникненні мережевої помилки, таймауту або збої на сервері Gmail система автоматично та миттєво перемикається на резервний шлюз Ukr.net.
  - Факт перемикання документується у журналі `NotificationLog` (`event_type="EMAIL_FAILOVER"`).
- **Безпечне одноразове відновлення пароля (Forgot Password Flow)**:
  - Маршрут `POST /api/v1/auth/forgot-password`: генерація криптографічного 32-байтового токена з 20-хвилинним терміном дії;
  - Збереження в базі даних виключно SHA-256 хешу токена (`PasswordResetToken`);
  - Жорсткий Rate Limiting (не більше 3 спроб за 15 хвилин);
  - Захист від витоку облікових записів через однаковий уніфікований текст відповіді;
  - Маршрут `POST /api/v1/auth/reset-password`: валідація токена, захист від повторного використання (`used = True`), зміна пароля.
  - **Миттєва інвалідація всіх активних сесій**: перерахунок `pwd_sig` миттєво робить недійсними всі раніше видані JWT токени на всіх пристроях користувача.
- **Оповіщення безпеки**:
  - Автоматичне надсилання email-сповіщення при зміні власного пароля з фіксацією дати, часу та IP-адреси.
- **Щотижневі зведені звіти Excel (Weekly Excel Digest)**:
  - Автоматична щотижнева генерація 5-сторінкової книги Excel (`.xlsx`) та розсилка на адреси керівництва щопонеділка (або за налаштованим днем/часом).
  - Ендпоінт `POST /api/v1/system/email/weekly-digest/send` для примусової відправки звіту адміністратором.
- **Аварійні сповіщення операційного контролю**:
  - Автоматичне надсилання термінового листа керівництву при спрацюванні захисту від роботи насухо (>12 год безперервної роботи).
- **Адміністративне керування та тестування пошти**:
  - Ендпоінт `POST /api/v1/system/email/test` для перевірки доставки через `primary`, `fallback` або `failover`.
  - Маскування паролів SMTP (`********`) на рівні API `GET /settings` та збереження оригінальних паролів при збереженні налаштувань.
  - Модальні вікна «Забули пароль?» та «Встановлення нового пароля» у веб-інтерфейсі (з автоматичним відкриттям за параметром `?reset_token=` у URL).
- **Розширення тестового покриття**:
  - Створено вичерпний тестовий набір `backend/tests/test_email_system.py` (9 нових тестів).
  - Загальне покриття розширено до **67 тестів із 100% успішним проходженням**.

---

## [v4.3.0] — 2026-10-24

### Експлуатаційні запобіжники та захист від людських помилок (Operational Safeguards)
- **Запобіжник опечатки мотогодин (Typo Guard on End Hours)**:
  - Серверна перевірка приросту мотогодин (Δhours = `end_hours` − `start_hours`) щодо тривалості за таймером (Δtime).
  - Блокування опечаток при Δhours > 14.0 год (максимальний фізичний час роботи на одному баку) або розходженні з таймером > 2.0 год (`400 Bad Request`), якщо користувач не підтвердив операцію прапорцем `force_confirm: true`.
  - Запобіжник для ручного внесення журналу (`manual-run`) при розходженні мотогодин із часовим інтервалом > 3.0 год.
- **Аварійний запобіжник від порожнього бака (Empty Tank Overrun Fuse)**:
  - Автоматична аварійна зупинка генератора при безперервній роботі ≥ 12.0 год (`max_continuous_run_hours`) для запобігання роботі насухо, заклинюванню двигуна та перегріву.
  - Фіксація події в системному аудиті (`GENERATOR_SAFETY_STOP`) та надсилання аварійного Web Push сповіщення на пристрої операторів.
- **Автоматична зупинка після закінчення робочого дня (Strict Day-Shift Auto-Stop)**:
  - Згідно з регламентом експлуатації (тільки в робочий час), фоновий вартовий автоматично зупиняє генератор після завершення дозволеного графіка роботи об'єкта.
  - Коректне збереження сеансу з приміткою: *«Автоматична зупинка за розкладом закінчення робочого дня»*, запис аудиту `GENERATOR_AUTO_STOP` та push-сповіщення.
- **Пульс-нагадування кожні 4 години (Heartbeat Reminder)**:
  - Для активних тривалих сеансів сервер кожні 4 години генерує push-нагадування черговому персоналу: *«⚠️ Генератор {name} досі працює (N год). Перевірте фізичний стан генератора, рівень палива та статус»*.
- **Контроль об'єму та вартості палива за чеком (Fuel Receipt Scale & Price Sanity Checks)**:
  - Запобіжник великих партій: оприбуткування понад 1000 л палива вимагає обов'язкового підтвердження (`force_confirm: true`).
  - Запобіжник аномальної ціни: блокування збереження чеків із розрахунковою ціною за літр менше 15 грн або більше 250 грн без явного підтвердження.
- **Клієнтський захист від випадкових дій (Frontend Debounce & Modals)**:
  - Миттєве блокування (`disabled = true`) кнопок управління та форм під час виконання мережевих запитів для запобігання подвійним клікам при нестабільному мобільному зв'язку;
  - Попереджувальне модальне вікно при спробі запуску генератора із простроченим регламентом ТО (`MAINTENANCE_REQUIRED`);
  - Інтерактивні діалоги підтвердження опечаток мотогодин та великих партій палива.

### Додано
- Виділений сервіс фонового моніторингу `OperationalGuardService` (`run_operational_guard_loop`), зареєстрований у життєвому циклі (`lifespan`) застосунку.
- Набір системних налаштувань у `system_settings`: `max_continuous_run_hours`, `auto_stop_on_schedule_end`, `notify_running_heartbeat`, `heartbeat_interval_hours`, `fuel_receipt_max_liters_warning`, `fuel_receipt_min_price`, `fuel_receipt_max_price`.
- Автоматизований тестовий набір `backend/tests/test_operational_safeguards.py` (5 нових тестів, загальне покриття розширено до 58 тестів, 100% успішне проходження).

---

## [v4.2.0] — 2026-10-24

### Безпека (Security Hardening)
- **Жорстка Multi-site ізоляція об'єктів (Варіант Б)**: оператори та спостерігачі тепер мають доступ виключно до свого закріпленого об'єкта (`user.facility_id`). Спроби доступу або керування обладнанням, складами чи журналами інших локацій блокуються сервером із кодом `403 Forbidden`. Адміністратори (`admin`) та головний системний адміністратор (`superadmin`) зберігають глобальний доступ до всіх локацій.
- **Самостійна зміна пароля та миттєва інвалідація сесій**:
  - Реалізовано новий ендпоінт `POST /api/v1/auth/change-password` для безпечної зміни пароля будь-яким авторизованим користувачем (з перевіркою поточного пароля та вимог складності).
  - У JWT-токен додано криптографічний підпис поточного хешу пароля (`pwd_sig`). При зміні або скиданні пароля всі раніше видані токени на всіх пристроях користувача миттєво стають недійсними (`401 Unauthorized`).
  - У `POST /api/v1/auth/logout` впроваджено серверний реєстр відкликаних токенів (`_REVOKED_TOKENS`) з автоматичним очищенням застарілих записів.
- **Стійкий захист від Brute-Force та підробки `X-Forwarded-For`**:
  - Удосконалено резолвер IP-адрес: пріоритет віддається заголовку `X-Real-IP` від довіреного Nginx, а при обробці `X-Forwarded-For` береться останній надійний вузол.
  - Лімітер невдалих спроб входу тепер одночасно відслідковує спроби за парою `ip:{ip}:{login}` та глобально за обліковим записом `acct:{login}`, що унеможливлює підбір пароля шляхом ротації фіктивних IP-адрес.
- **Захист облікового запису SuperAdmin при перезапусках**:
  - Пароль `superadmin` тепер задається виключно під час першого створення у порожній БД і більше не перезаписується значенням з `.env` при кожному перезапуску контейнера.
  - Додано автоматичний аудит конфігурації під час старту застосунку (`check_security_warnings`), що попереджає про використання дефолтних ключів або паролів.
- **Захист модулів резервного копіювання (Disaster Recovery Hardening)**:
  - Автоматичне маскування секретів: при упаковці конфігураційних файлів у бекап значення змінних із ключами `SECRET`, `PASSWORD`, `KEY`, `TOKEN`, `DATABASE_URL` замінюються на `***REDACTED***`.
  - Захист від Zip Slip (Path Traversal) та Zip Bomb (ліміт: до 10 000 файлів та до 500 МБ розпакованих даних у `_safe_extract_zip`).
  - Жорсткий ліміт розміру завантажуваного архіву бекапу до 100 МБ (`HTTP 413 Payload Too Large`) з потоковою валідацією.
  - Санітизація внутрішніх помилок: усунуто витік сирих системних трейсів та шляхів сервера при помилках відновлення.
- **Захист Web Push від SSRF та IDOR**:
  - Строга валідація Push-ендпоінтів: дозволено виключно HTTPS та білий список офіційних сервісів (Google FCM, Mozilla, Apple Push, Windows WNS); блокування приватних, внутрішніх (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`) та link-local (`169.254.169.254`) адрес.
  - Захист від IDOR: користувач може відписати від push-сповіщень виключно власний пристрій (`403 Forbidden` при спробі маніпуляції чужими записами).
  - Тестова відправка сповіщень `POST /api/v1/notifications/test` обмежена виключно зареєстрованими пристроями поточного користувача.
- **Захист від витоку системної інформації (Anti-Fingerprinting)**:
  - Публічний ендпоінт `/api/v1/system/status` більше не розкриває точну версію ядра ОС чи повний патч-номер Python.
- **Інфраструктурна безпека (Docker & Nginx)**:
  - З репозиторію видалено статичні файли приватних ключів SSL; додано генерацію безпечних тимчасових сертифікатів на льоту при старті Nginx.
  - Параметр `--forwarded-allow-ips` у Dockerfile обмежено довіреними внутрішніми діапазонами Docker.
  - Узгоджено заголовки безпеки у Nginx: `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Strict-Transport-Security`.

### Додано
- Створено виділений тестовий модуль безпеки `backend/tests/test_security_hardening.py` (8 нових автоматизованих тестів, загальне покриття розширено до 53 тестів, 100% успішне проходження).
- Хелпери перевірки прав доступу до об'єктів: `verify_facility_access` та `verify_generator_facility_access`.

### Змінено
- При передачі неіснуючого `generator_id` в API-запитах повертається чітка помилка `404 Not Found` замість мовчазного підставляння першого генератора.
- Збережено сумісність: якщо `generator_id` взагалі не вказано, система продовжує вибирати генератор за замовчуванням.

---

## [v4.1.0] — 2026-10-20

### Додано
- **Дотримання вимог ДСТУ 4163:2020**: уніфіковані стандарти відображення часу (точний хронометраж `ГГ:ХХ:СС`, підсумок `X год YY хв`), словесно-числових дат (`20 жовт. 2026 р.` / `20.10.2026`), грошових сум (`грн.коп`) та об'ємів палива в літрах (`15,0 л`).
- **Миттєвий зворотний зв'язок оператору**: спливаюче сповіщення про успішне формування звіту та інтерактивні картки ключових показників (мотогодини, витрата пального, сума у грн, питома витрата л/год) безпосередньо під формою фільтрів.
- **Офлайн-журнал та ретроспективне внесення сесій**: новий ендпоінт `POST /api/v1/generator/manual-run` для фіксації роботи генератора за паперовим журналом під час блекаутів або збоїв зв'язку.
- **Розширений пакет нормативної документації та політик**:
  - `docs/OPERATIONAL_SAFETY_POLICY.md` — політика безпеки, охорони праці та пожежної безпеки під час обслуговування генераторів;
  - `docs/DATA_GOVERNANCE_AND_AUDIT.md` — стандарти управління даними, процедури місячних інвентаризацій та RPO/RTO бекапів;
  - `docs/SLA_AND_SUPPORT.md` — регламент технічної підтримки та матриця пріоритетів інцидентів (P1–P4);
  - Оновлено `docs/PRIVACY_POLICY.md` та `docs/TERMS_OF_SERVICE.md` з покриттям GDPR, Закону України № 2297-VI, юридичних застережень та недоторканності лічильників.
- **Повна актуалізація документації API та оточення**:
  - `docs/API_REFERENCE.md` — розписано всі 12 модулів REST API;
  - `docs/ENV_VARS.md` — розмежовано статичні інфраструктурні параметри та динамічні runtime-налаштування;
  - `docs/RBAC_PERMISSIONS.md` — зафіксовано повну матрицю з 23 дозволів.
- **Автоматизоване тестування**: розширено тестовий набір до 42 тестів (100% успішне проходження).

### Змінено
- Зафіксовано версію PWA додатка: `v4.1` (оновлено `sw.js` та кеш-стратегії).
- Покращено обробку помилок при формуванні аналітичного звіту: усунуто падіння при відсутності атрибутів обслуговування.

---

## [v4.0.0] — 2026-10-18

### Додано
- **Багатооб'єктність (Multi-site Architecture)**: додано модель `Facility`, можливість управління філіями та закріплення генераторів і складів за об'єктами.
- **Запам'ятовування стану оператора**: автоматичне збереження обраного об'єкта та генератора у `localStorage`.
- **Швидкі налаштування об'єктів та генераторів**: кнопки `⚙️` у навігаційній шапці.
- **Динамічні системні налаштування у БД**: таблиця `system_settings` для керування порогами та графіком на льоту.
- **Парсер цін АЗК WOG**: автоматичне підтягування актуальних цін на бензин та дизель із сайту мережі WOG.
- **Безпечне очищення бази даних (Clean DB)**: процедура скидання даних за кодовим словом `ОЧИСТИТИ`.
- **Багатосторінковий Excel-експорт (5 аркушів)**: повна заміна застарілого CSV на сучасні книги `.xlsx` (OpenPyXL).
- **Web Push сповіщення (VAPID)**: оперативне оповіщення на смартфонах операторів про запуск, зупинку, ТО та рівень палива.

---

## [v3.0.0] — 2026-10-05

### Додано
- **Розширений паливний модуль**: підтримка складів ГСМ, прибуткування палива за накладними та внутрішнє переміщення (заправка бака).
- **Облік регламентного та проміжного ТО**: автоматичний підрахунок залишкового міжсервісного ресурсу.
- **Журнал несправностей**: реєстрація дефектів та блокування пуску при критичних несправностях (`CRITICAL`).
- **Розширений RBAC**: ролі `superadmin`, `admin`, `operator`, `viewer`.
- **Журнал системного аудиту**: незмінна фіксація дій користувачів.

---

## [v2.0.0] — 2026-09-15

### Додано
- **PWA версія**: підтримка встановлення як застосунку на Android та iOS Safari.
- **Контроль графіка (Europe/Kyiv)**: обмеження роботи генератора згідно з визначеними годинами.
- **Bcrypt + JWT захист**: захищені сесії з опцією «Запам'ятати мене» (до 60 діб).
- **Rate Limiting та захист від брутфорсу**: блокування спроб підбору пароля.

---

## [v1.0.0] — 2026-08-01

### Додано
- Базовий реліз системи обліку генераторів (SD-GEN016).
- Реєстрація робочих циклів (пуск, стоп, секундомір мотогодин).
- Розрахунок списання палива за паспортом.
- SQLite база даних та початковий інтерфейс оператора.
