# Резервне копіювання та відновлення даних

Система **SD-GEN016** містить автоматизовані скрипти для створення резервних копій бази даних, конфігурації та файлів вкладень, а також швидкого відновлення у разі збоїв.

---

## 1. Створення резервної копії вручну

### За допомогою Python (кросплатформно):
```bash
python scripts/backup.py
```

### За допомогою Shell (на Linux / VPS):
```bash
sh scripts/backup.sh
```

Скрипт автоматично:
1. Створює дамп бази даних (SQLite або PostgreSQL через `pg_dump`).
2. Копіює директорію завантажених фотографій `uploads/`.
3. Упаковує все у стиснений архів: `backups/backup_sd_gen016_YYYYMMDD_HHMMSS.tar.gz`.

---

## 2. Налаштування автоматичного щоденного бекапу через Cron на VPS

Відкрийте crontab:
```bash
crontab -e
```

Додайте рядок для щоденного запуску о 02:00 ночі:
```cron
0 2 * * * cd /opt/sd-gen016 && sh scripts/backup.sh >> /var/log/sd_gen016_backup.log 2>&1
```

Для автоматичного видалення архівів, старіших за 30 днів:
```cron
0 3 * * * find /opt/sd-gen016/backups/ -name "backup_*.tar.gz" -mtime +30 -delete
```

---

## 3. Відновлення системи з резервної копії

### За допомогою Python:
```bash
python scripts/restore.py backups/backup_sd_gen016_20261005_135700.tar.gz
```

### За допомогою Shell:
```bash
sh scripts/restore.sh backups/backup_sd_gen016_20261005_135700.tar.gz
```

Скрипт відновлення:
1. Розпаковує архів.
2. Відновлює файл бази даних або застосовує SQL-дамп PostgreSQL.
3. Повертає директорію завантажених фотографій `uploads/`.
4. Перезапускає додаток (`docker compose restart app`).
