#!/bin/sh
set -e

ARCHIVE_PATH="$1"

if [ -z "$ARCHIVE_PATH" ] || [ ! -f "$ARCHIVE_PATH" ]; then
    echo "Usage: ./scripts/restore.sh <path_to_backup.tar.gz>"
    exit 1
fi

TEMP_DIR="./backups/tmp_restore"
mkdir -p "${TEMP_DIR}"

echo "[*] Extracting ${ARCHIVE_PATH}..."
tar -xzf "${ARCHIVE_PATH}" -C "${TEMP_DIR}"

if [ -f "${TEMP_DIR}/service_desk.db" ]; then
    cp "${TEMP_DIR}/service_desk.db" ./service_desk.db
    echo "[OK] SQLite database restored"
fi

if [ -f "${TEMP_DIR}/db_dump.sql" ] && [ -n "$DATABASE_URL" ]; then
    CLEAN_URL=$(echo "$DATABASE_URL" | sed 's/+asyncpg//')
    psql "${CLEAN_URL}" -f "${TEMP_DIR}/db_dump.sql"
    echo "[OK] PostgreSQL database restored"
fi

if [ -d "${TEMP_DIR}/uploads" ]; then
    mkdir -p ./uploads
    cp -r "${TEMP_DIR}/uploads/"* ./uploads/
    echo "[OK] Uploads restored"
fi

rm -rf "${TEMP_DIR}"
echo "[OK] System successfully restored from backup!"
