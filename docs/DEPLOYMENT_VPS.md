# Розгортання на VPS та налаштування PWA

**Версія документа:** 4.2.0 (Production Hardened)  
**Дата набрання чинності:** 24 жовтня 2026 року  

Цей документ описує покроковий процес розгортання **SD-GEN016** на окремому віртуальному сервері (VPS) під керуванням Ubuntu/Debian із власним доменом та сертифікатом HTTPS.

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
- `PRIMARY_DOMAIN`: ваш реальний робочий домен (наприклад `generator-016.pp.ua`).
- `APP_SECRET_KEY`: згенеруйте надійний 64-символьний ключ (`python -c "import secrets; print(secrets.token_urlsafe(64))"`).
- `INITIAL_ADMIN_PASSWORD`: надійний пароль первинного адміністратора (буде збережено у БД при першому старті).
- `POSTGRES_PASSWORD`: надійний пароль для бази даних.

---

## 3. Налаштування SSL-сертифікатів (Let's Encrypt або Автоматичний Fallback)

### Варіант А: Отримання офіційного безкоштовного сертифіката (Certbot / Let's Encrypt)
Для вашого зареєстрованого домену:
```bash
sudo apt install -y certbot
sudo certbot certonly --standalone -d generator-016.pp.ua
```
Сертифікати будуть збережені в `/etc/letsencrypt/live/generator-016.pp.ua/`.

Скопіюйте сертифікати до `docker/ssl/`:
```bash
mkdir -p docker/ssl
sudo cp /etc/letsencrypt/live/generator-016.pp.ua/fullchain.pem docker/ssl/fullchain.pem
sudo cp /etc/letsencrypt/live/generator-016.pp.ua/privkey.pem docker/ssl/privkey.pem
chmod 600 docker/ssl/privkey.pem
```

### Варіант Б: Автоматичний Fallback (Self-Signed на льоту)
Якщо ви запускаєте систему на внутрішньому IP або сертифікати Let's Encrypt ще не готові, скрипт контейнера Nginx автоматично згенерує локальний тимчасовий SSL-сертифікат на льоту під час запуску. Система запрацює за протоколом HTTPS без помилок конфігурації Nginx.

---

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
4. Nginx налаштує безпечні HTTP-заголовки (`HSTS`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, ліміт тіла `client_max_body_size 100M`).
5. Застосунок стане доступним за захищеним протоколом `https://your-domain`.

---

## 5. Встановлення PWA на Android та iOS

1. Відкрийте сайт через мобільний браузер: `https://your-domain`
2. Авторизуйтесь у системі.
3. **Android (Chrome)**: У правому верхньому меню (три крапки) оберіть: **«Встановити додаток»** (або «Додати на головний екран»).
4. **iOS (Safari)**: Натисніть кнопку «Поділитися» (іконка зі стрілкою) та оберіть: **«На екран „Додому“»**.
5. Додаток з'явиться на робочому столі смартфона з власною іконкою. При запуску він відкривається в автономному повноекранному режимі (`standalone`) без адресного рядка браузера.
