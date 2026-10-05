# Змінні середовища (Environment Variables)

Конфігурація системи **SD-GEN016** зберігається у файлі `.env` і завантажується автоматично при старті додатку.

## Перелік змінних

| Змінна | Призначення | Значення за замовчуванням | Приклад для Production |
|---|---|---|---|
| `APP_ENV` | Режим оточення додатку | `production` | `production` |
| `APP_SECRET_KEY` | Секретний ключ для підпису JWT токенів та сесій | `change_this_to_a_secure_random_secret_key` | `k8f93j20dkld938210493820194820194` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Час дії токена доступу у хвилинах | `1440` (24 години) | `1440` |
| `INITIAL_ADMIN_LOGIN` | Логін первинного системного адміністратора (створюється лише якщо БД порожня) | `superadmin` | `superadmin` |
| `INITIAL_ADMIN_PASSWORD` | Пароль первинного системного адміністратора | `SuperAdminPass123!` | `НадійнийСкладнийПароль#2026` |
| `INITIAL_ADMIN_EMAIL` | Email первинного адміністратора | `admin@facility.local` | `admin@my-domain.com` |
| `INITIAL_ADMIN_FULL_NAME` | ПІБ первинного адміністратора | `Головний Системний Адміністратор` | `Іванов Іван Іванович` |
| `DATABASE_URL` | Рядок підключення до реляційної БД (async) | `sqlite+aiosqlite:///./service_desk.db` | `postgresql+asyncpg://sd_user:password@db:5432/sd_gen016` |
| `FACILITY_TIMEZONE` | Часовий пояс об'єкта (коректно враховує літній/зимовий час в Україні) | `Europe/Kyiv` | `Europe/Kyiv` |
| `UPLOAD_DIR` | Каталог для збереження фотографій дефектів та чеків | `./uploads` | `/app/uploads` |
| `POSTGRES_USER` | Користувач PostgreSQL (для Docker Compose) | `sd_user` | `sd_user` |
| `POSTGRES_PASSWORD` | Пароль PostgreSQL (для Docker Compose) | `sd_password` | `sd_strong_db_pass_2026` |
| `POSTGRES_DB` | Назва бази даних PostgreSQL | `sd_gen016` | `sd_gen016` |

> [!IMPORTANT]
> `INITIAL_ADMIN_LOGIN` та `INITIAL_ADMIN_PASSWORD` використовуються **лише один раз** під час ініціалізації порожньої бази даних. Надалі керування паролями та користувачами здійснюється виключно через інтерфейс додатку. Паролі в базі даних зберігаються виключно у вигляді незворотних хешів Bcrypt.
