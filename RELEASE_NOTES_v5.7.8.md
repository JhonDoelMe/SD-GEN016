# Примітки до релізу SD-GEN016 v5.7.8 (Release Notes v5.7.5 — v5.7.8)

**Дата випуску:** 14 листопада 2026 року  
**Версія платформи та PWA:** `v5.7.8` (`sw.js`: `sd-gen016-v5.7.8`)  
**Версія Android APK:** `v5.7.8` (`versionCode 15`, підписаний APK + OTA)

Консолідований реліз **v5.7.5 — v5.7.8** зосереджений на посиленні виробничої безпеки, усуненні експлуатаційних обмежень обліку палива та доведенні нативного Android-додатка (брендинг, клавіатура IME, OTA-оновлення, апаратна/жестова навігація «Назад»).

---

## 1. Нативна навігація кнопкою «Назад» на Android (`v5.7.8`, `versionCode 15`)
- **Перехоплення системного Back у WebView (`android/app/src/main/java/ua/pp/sdgen/app/MainActivity.java`)**:
  - Замість миттєвого закриття додатка зареєстровано `OnBackPressedCallback`, який делегує обробку у JS-функцію `window.__handleNativeBack()`.
- **Ієрархія повернення (`frontend/js/auth-nav.js`, `frontend/js/core.js`, `frontend/js/audit-reports.js`)**:
  1. Закриття відкритого навігаційного меню (`#navDrawer`), меню профілю (`#accountDropdown`) або панелі сповіщень (`#notificationsDropdown`).
  2. Закриття верхнього відкритого модального вікна (`window.getTopOpenModalId()` за `z-index` і стеком `_openModalStack`, не закриваючи екран входу `#authOverlay` та обов'язковий OTA-блок `#modalAppUpdate`; додатково підтримано закриття верхньої модалки клавішею `Escape`).
  3. Покрокове повернення історією переходів (`window._navHistory`) між розділами (`switchTab`), підвкладками адміністрування (`switchAdminSubtab`) та підвкладками звітів (`switchReportSubtab`), а за порожньої історії — повернення на Головну (`tab-dashboard`).
  4. На кореневому екрані (Головна або екран входу) — подвійне натискання «Назад» у вікні `2.2 с` із тостом-підказкою для захисту від випадкового виходу.

## 2. Стабільні OTA-оновлення Android та усунення ліміту 59,9 л (`v5.7.7`, `versionCode 14`)
- **OTA Updater у Capacitor Android (`frontend/js/ota-updater.js`, `frontend/js/core.js`, `frontend/js/auth-nav.js`)**:
  - Усунено проблему пропуску `DOMContentLoaded` при лінивому підвантаженні через `view-loader.js` — впроваджено негайний запуск `initOtaUpdater()`.
  - `showUpdateModal()` переведено в `async` з обов'язковим `await ViewLoader.ensureModal('modalAppUpdate')`.
  - Додано відображення версії APK у вікні «🌐 Адреса сервера» (`window.refreshOtaVersionBadge()`) та запуск OTA-перевірки при натисканні **«🔄 Оновити застосунок»** у меню профілю на Android.
- **Повна заправка бака 60,0 л без глухого кута округлення (`backend/app/services/fuel_service.py`, `frontend/js/fuel.js`, `frontend/views/modals-ops.html`)**:
  - Усунено розбіжність між серверним обліком `0.001 л` та округленням UI до `0.1 л`, коли при залишку на кшталт `59.944 л` спроба долити `0.1 л` відхилялася як перелив.
  - На сервері додано допуск округлення `rounding_slack = Decimal("0.050")` (`tank_before < tank_cap` і `tank_after <= tank_cap + 0.050` ➔ фіксується `tank_cap`), на клієнті — `step="any" min="0.01"` і спільну функцію `_computeTransferBounds()`. Додано відповідний тест `test_fuel_transfer_allows_0_05l_rounding_tolerance_to_fill_full_60l_tank`.

## 3. Клавіатура IME та фірмова айдентика Android (`v5.7.5` — `v5.7.6`)
- **Виправлення подвійного відступу над клавіатурою (`v5.7.6`, `versionCode 13`)**: у `capacitor.config.json` увімкнено `SystemBars` (`insetsHandling: "css"`, `style: "DARK"`, `initialViewportFitValueHint: "cover"`) та прибрано дублюючий IME padding у `MainActivity.java`.
- **Фірмові іконки запуску та splash-екрани (`v5.7.5`)**: оновлено всі ресурси лаунчера (`ic_launcher`, `ic_launcher_round`, adaptive icons) та `splash.png` під логотип `SD-GEN016` скриптом `scripts/generate-android-icons.py`.

## 4. Комплексне зміцнення безпеки та виробництва (`v5.7.5`)
- **Production-жорсткість API та Nginx (`backend/app/main.py`, `backend/app/config.py`, `docker/nginx.conf`)**:
  - У режимі `APP_ENV=production` автоматично вимикаються `/docs`, `/redoc` та `/openapi.json`.
  - У всіх серверних блоках Nginx увімкнено `server_tokens off` та усунено дублювання безпекових/CSP-заголовків.
- **Безпека сервісів, OTA, бекапів і PWA**:
  - Посилено перевірки SSRF, валідацію завантажень та SHA-256 контрольних сум у `ota-server/storage.py` й `OtaUpdaterPlugin.java`, обробку архівів бекапів, санітизацію фронтенду, та додано примусовий релоад SW-клієнтів при `controllerchange`.
  - Покрито новими тестами безпеки та цілісності (`backend/tests/test_security_and_domain_hardening.py`). Загальне тестове покриття: **203 тести бекенду + 5 тестів OTA-сервера**.
