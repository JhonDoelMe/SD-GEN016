#!/usr/bin/env python3
"""
Restore Utility for SD-GEN016
Restores SQLite or PostgreSQL database and uploads from a backup archive.
"""
import os
import sys
import shutil
import tarfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from backend.app.config import settings


def run_restore(archive_path_str: str):
    archive_path = Path(archive_path_str)
    if not archive_path.exists():
        print(f"[!] Error: Archive file '{archive_path}' does not exist!")
        sys.exit(1)

    temp_dir = ROOT_DIR / "backups" / "tmp_restore"
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        print(f"[*] Extracting archive {archive_path.name}...")
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(path=temp_dir)

        # 1. Restore SQLite database if present
        extracted_db = temp_dir / "service_desk.db"
        if extracted_db.exists() and settings.is_sqlite:
            target_db = ROOT_DIR / "service_desk.db"
            shutil.copy2(extracted_db, target_db)
            print(f"[OK] SQLite database restored to {target_db}")

        # 2. Restore PostgreSQL dump if present
        extracted_dump = temp_dir / "db_dump.sql"
        if extracted_dump.exists() and not settings.is_sqlite:
            print("[*] Restoring PostgreSQL dump...")
            os.system(f"psql {settings.DATABASE_URL.replace('+asyncpg', '')} -f {extracted_dump}")
            print("[OK] PostgreSQL database restored")

        # 3. Restore Uploads
        extracted_uploads = temp_dir / "uploads"
        if extracted_uploads.exists():
            uploads_dir = Path(settings.UPLOAD_DIR)
            if not uploads_dir.is_absolute():
                uploads_dir = ROOT_DIR / uploads_dir
            shutil.copytree(extracted_uploads, uploads_dir, dirs_exist_ok=True)
            print(f"[OK] Uploads restored to {uploads_dir}")

        print("[OK] System successfully restored from backup!")

    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/restore.py <path_to_backup_archive.tar.gz>")
        sys.exit(1)
    run_restore(sys.argv[1])
