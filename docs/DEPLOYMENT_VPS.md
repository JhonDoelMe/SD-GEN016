# Розгортання на VPS, Налаштування PWA, Android APK (OTA) та FCM Push

**Версія документа:** 5.7.8 (Docker Hardened, Nginx OTA Proxy, Android APK Release Pipeline, Firebase FCM HTTP v1 & Modular PWA)  
**Дата набрання чинності:** 14 листопада 2026 року  

Цей документ описує покроковий процес розгортання **SD-GEN016** на окремому віртуальному сервері (VPS) під керуванням Ubuntu/Debian із власним доменом, сертифікатом HTTPS, мобільним push-шлюзом Firebase FCM HTTP v1 та сервером OTA-оновлень Android APK (`/ota/`).

---

## 1. Підготовка сервера VPS

### Встановлення Docker та Docker Compose
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y curl git ufw

# Встановлення офіційного Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# Налаштування файрволу UFW
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

---

## 2. Клонування репозиторію та налаштування ENV

```bash
git clone https://github.com/JhonDoelMe/SD-GEN016.git /opt/sd-gen016
cd /opt/sd-gen016

# Створіть файл .env на основі .env.example
cp .env.example .env
nano .env
```

Обов'язково заповніть у `.env`:
- `PRIMARY_DOMAIN`: ваш реальний робочий домен (наприклад `sdgen.pp.ua`).
- `APP_SECRET_KEY`: згенеруйте надійний 64-символьний ключ (`python -c "import secrets; print(secrets.token_urlsafe(64))"`).
- `INITIAL_ADMIN_PASSWORD`: надійний пароль первинного адміністратора (буде збережено у БД при першому старті).
- `POSTGRES_PASSWORD`: надійний пароль для бази даних.
- **Зовнішня телеметрія (рекомендовано):** `OPENWEATHER_API_KEY` (поточна погода та 5-денний прогноз), `ALERTS_IN_UA_TOKEN` та `UKRAINE_ALARM_API_KEY` (паралельний двоканальний моніторинг повітряних тривог зі «Страхуванням відбою»).
- **Нативні Push Android APK (опційно для FCM):** змонтуйте файл сервісного акаунта Firebase у `docker/firebase/firebase-service-account.json` (read-only том `/app/firebase`) або задайте `FIREBASE_SERVICE_ACCOUNT_JSON`.
- **CORS / Capacitor:** для підписаного Android APK додайте схеми `https://localhost,capacitor://localhost` до `CORS_ORIGINS` (у production за потреби поруч із доменом `https://sdgen.pp.ua`).

---

## 3. Налаштування SSL-сертифікатів (Let's Encrypt або Автоматичний Fallback)

### Варіант А: Отримання офіційного безкоштовного сертифіката (Certbot / Let's Encrypt)
Для вашого зареєстрованого домену:
```bash
sudo apt install -y certbot
sudo certbot certonly --standalone -d sdgen.pp.ua
```
Сертифікати будуть збережені в `/etc/letsencrypt/live/sdgen.pp.ua/`.

Скопіюйте сертифікати до `docker/ssl/`:
```bash
mkdir -p docker/ssl
sudo cp /etc/letsencrypt/live/sdgen.pp.ua/fullchain.pem docker/ssl/fullchain.pem
sudo cp /etc/letsencrypt/live/sdgen.pp.ua/privkey.pem docker/ssl/privkey.pem
chmod 600 docker/ssl/privkey.pem
```

### Варіант Б: Автоматичний Fallback (Self-Signed на льоту)
Якщо ви запускаєте систему на внутрішньому IP або сертифікати Let's Encrypt ще не готові, скрипт контейнера Nginx автоматично згенерує локальний тимчасовий SSL-сертифікат на льоту під час запуску. Система запрацює за протоколом HTTPS без помилок конфігурації Nginx.

---


> [!IMPORTANT]
> **Права на томи даних (Docker Hardening INF-14 v4.6.0):**
> Бекенд виконується від імені непривілейованого користувача `appuser` (UID: 10001, GID: 10001). Якщо ви монтуєте хостові каталоги для збереження даних (`./data`, `./uploads`, `./backups`), переконайтеся, що вони доступні для запису користувачу з UID 10001:
> ```bash
> sudo chown -R 10001:10001 data uploads backups
> ```

## 4. Запуск через Docker Compose

```bash
docker compose up -d --build
```

Перевірка статусу:
```bash
docker compose ps
docker compose logs -f app
```

При першому старті:
1. Автоматично підніметься PostgreSQL 16 із перевіркою працездатності (healthcheck).
2. Alembic автоматично застосує міграції схеми БД.
3. Сервіс ініціалізації створить суперкористувача `superadmin`, стандартні ролі та матрицю прав.
4. Nginx приховує версію сервера (`server_tokens off`), налаштовує єдині безпечні HTTP-заголовки без дублювання (`HSTS`, `CSP`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, ліміт тіла `client_max_body_size 100M`), Gzip-стиснення (`gzip_comp_level 5`) та кешування версіонованої статики `/frontend/` (з негайним оновленням `/sw.js`), тоді як при `APP_ENV=production` маршрути `/docs`, `/redoc` та `/openapi.json` автоматично вимикаються.
5. Застосунок стане доступним за захищеним протоколом `https://your-domain`.

---

## 5. Встановлення PWA на Android та iOS

1. Відкрийте сайт через мобільний браузер: `https://your-domain`
2. Авторизуйтесь у системі.
3. **Android (Chrome)**: У правому верхньому меню (три крапки) оберіть: **«Встановити додаток»** (або «Додати на головний екран»).
4. **iOS (Safari)**: Натисніть кнопку «Поділитися» (іконка зі стрілкою) та оберіть: **«На екран „Додому“»**.
5. Додаток з'явиться на робочому столі смартфона з власною іконкою. При запуску він відкривається в автономному повноекранному режимі (`standalone`) без адресного рядка браузера та з автоматичним офлайн-кешуванням в `IndexedDB`.

---

## 6. Автономний OTA-сервіс оновлень Android APK (`ota-server/`)

1. Конфігурація `docker/nginx.conf` автоматично проксіює маршрут `/ota/` на `upstream ota_server` (`host.docker.internal:8090`).
2. Для запуску сервісу оновлень APK на хості або в окремому контейнері:
   ```bash
   cd ota-server
   cp .env.example .env
   # Задайте безпечний OTA_ADMIN_TOKEN та за потреби підключіть том releases/
   docker compose up -d --build
   ```
3. Збірка та автоматична публікація підписаного Android APK виконується скриптом [`scripts/release_android.ps1`](../scripts/release_android.ps1) (піднімає версію, синхронізує Web-асети через `cap copy android` та `sync-android-assets.js`, збирає release APK, перевіряє `apksigner` і публікує на `/ota/`). Ручне завантаження також доступне через `/ota/admin` (захищено `OTA_ADMIN_TOKEN`) або `POST /ota/api/releases`. Клієнти Android APK перевіряють `/ota/api/latest` автоматично або через меню «🔄 Оновити застосунок» (`frontend/js/ota-updater.js`).
