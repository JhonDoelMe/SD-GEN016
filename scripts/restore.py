#!/usr/bin/env python3
"""
Modern Disaster Recovery Utility for SD-GEN016 (Service Desk Бензинового Генератора)
Restores PostgreSQL / SQLite database and media files from modern .zip backup archives.
"""
import sys
import asyncio
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from backend.app.database import AsyncSessionLocal
from backend.app.services.backup_service import restore_backup, inspect_backup


async def main_restore(archive_path_str: str, restore_files: bool = True):
    archive_path = Path(archive_path_str).resolve()
    if not archive_path.exists():
        print(f"[!] Error: Файл бекапу '{archive_path}' не знайдено!")
        sys.exit(1)

    print(f"[*] Перевірка архіву: {archive_path.name}...")
    try:
        info = inspect_backup(archive_path)
        manifest = info.get("manifest", {})
        print(f"    - Тип: {manifest.get('backup_type_ua', manifest.get('backup_type'))}")
        print(f"    - Створено: {manifest.get('created_at')} (автор: {manifest.get('created_by')})")
        print(f"    - Розмір: {info.get('size_formatted')}")
        print(f"    - Таблиць: {manifest.get('tables_count')}, Записів: {manifest.get('records_count')}")
    except Exception as e:
        print(f"[!] Warning: Не вдалося прочитати маніфест: {e}")

    print("\n[*] Запуск процедури відновлення...")
    async with AsyncSessionLocal() as session:
        result = await restore_backup(
            session=session,
            zip_path=archive_path,
            restore_files=restore_files,
            creator="CLI_DISASTER_RECOVERY",
            creator_ip="127.0.0.1"
        )

    print("\n[OK] " + result.get("message", "Відновлення завершено!"))
    print(f"     - Відновлено записів: {result.get('records_restored')}")
    print(f"     - Відновлено таблиць: {result.get('tables_restored_count')}")
    print(f"     - Медіа-файлів відновлено: {result.get('media_files_restored')}")
    print(f"     - Автоматичний snapshot безпеки: {result.get('safety_backup_filename')}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Використання: python scripts/restore.py <шлях_до_архіву_backup_*.zip> [--no-files]")
        sys.exit(1)

    archive = sys.argv[1]
    restore_media = "--no-files" not in sys.argv
    asyncio.run(main_restore(archive, restore_files=restore_media))
