# Розгортання на VPS та налаштування PWA

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
- `APP_SECRET_KEY`: згенеруйте випадковий 32+ символьний рядок (`openssl rand -hex 32`).
- `INITIAL_ADMIN_PASSWORD`: надійний пароль первинного адміністратора.
- `POSTGRES_PASSWORD`: надійний пароль для бази даних.

---

## 3. Отримання безкоштовного SSL-сертифіката (Certbot / Let's Encrypt)

Для домену (наприклад, `gen.myfacility.ua`):
```bash
sudo apt install -y certbot
sudo certbot certonly --standalone -d gen.myfacility.ua
```
Сертифікати будуть збережені в `/etc/letsencrypt/live/gen.myfacility.ua/`.

Для підключення SSL до Nginx:
1. Скопіюйте або підмонтуйте сертифікати до `docker/ssl/`:
```bash
mkdir -p docker/ssl
sudo cp /etc/letsencrypt/live/gen.myfacility.ua/fullchain.pem docker/ssl/fullchain.pem
sudo cp /etc/letsencrypt/live/gen.myfacility.ua/privkey.pem docker/ssl/privkey.pem
```
2. У `docker/nginx.conf` увімкніть блок `listen 443 ssl` та вкажіть шляхи до `ssl_certificate /etc/nginx/ssl/fullchain.pem;`.

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
1. Автоматично підніметься PostgreSQL.
2. Alembic автоматично виконає міграції схеми БД.
3. Сервіс ініціалізації створить суперкористувача `superadmin` та стандартні ролі.
4. Додаток стане доступним за адресою вашого домену або IP сервера.

---

## 5. Встановлення PWA на Android

1. Відкрийте сайт через мобільний браузер Chrome на Android: `https://gen.myfacility.ua`
2. Авторизуйтесь у системі.
3. У правому верхньому меню Chrome (три крапки) виберіть пункт: **«Встановити додаток»** (або «Додати на головний екран»).
4. Додаток з'явиться на робочому столі смартфона з власною іконкою.
5. При запуску він відкривається у повноекранному автономному режимі (`standalone`) без адресного рядка браузера і кешує інтерфейс через Service Worker.
