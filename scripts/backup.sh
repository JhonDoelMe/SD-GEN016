#!/bin/sh
set -e

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_DIR="./backups"
ARCHIVE_NAME="${BACKUP_DIR}/backup_sd_gen016_${TIMESTAMP}.tar.gz"
TEMP_DIR="${BACKUP_DIR}/tmp_${TIMESTAMP}"

mkdir -p "${BACKUP_DIR}"
mkdir -p "${TEMP_DIR}"

echo "[*] Starting backup at ${TIMESTAMP}..."

# Database backup
if [ -f "./service_desk.db" ]; then
    cp ./service_desk.db "${TEMP_DIR}/service_desk.db"
    echo "[+] SQLite database copied"
fi

if [ -n "$DATABASE_URL" ] && echo "$DATABASE_URL" | grep -q "postgres"; then
    CLEAN_URL=$(echo "$DATABASE_URL" | sed 's/+asyncpg//')
    pg_dump "${CLEAN_URL}" -f "${TEMP_DIR}/db_dump.sql" || true
    echo "[+] PostgreSQL dump processed"
fi

# Uploads backup
if [ -d "./uploads" ]; then
    cp -r ./uploads "${TEMP_DIR}/uploads"
    echo "[+] Uploads folder copied"
fi

# Create archive
tar -czf "${ARCHIVE_NAME}" -C "${TEMP_DIR}" .
rm -rf "${TEMP_DIR}"

echo "[OK] Backup created: ${ARCHIVE_NAME}"
