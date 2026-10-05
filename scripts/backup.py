#!/usr/bin/env python3
"""
Automated Database & Uploads Backup Utility for SD-GEN016
Backs up SQLite or PostgreSQL database along with user uploads and configuration.
"""
import os
import sys
import shutil
import tarfile
import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from backend.app.config import settings


def run_backup():
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = ROOT_DIR / "backups"
    backup_dir.mkdir(exist_ok=True)
    archive_name = backup_dir / f"backup_sd_gen016_{timestamp}.tar.gz"

    temp_dir = backup_dir / f"tmp_{timestamp}"
    temp_dir.mkdir(exist_ok=True)

    try:
        print(f"[*] Starting backup at {timestamp}...")

        # 1. Database backup
        if settings.is_sqlite:
            db_path = ROOT_DIR / "service_desk.db"
            if db_path.exists():
                shutil.copy2(db_path, temp_dir / "service_desk.db")
                print(f"[+] SQLite database copied: {db_path}")
            else:
                print("[-] SQLite database file not found, skipping...")
        else:
            # PostgreSQL pg_dump
            dump_file = temp_dir / "db_dump.sql"
            ret = os.system(f"pg_dump {settings.DATABASE_URL.replace('+asyncpg', '')} -f {dump_file}")
            if ret == 0:
                print("[+] PostgreSQL dump completed successfully")
            else:
                print("[-] PostgreSQL dump returned non-zero code")

        # 2. Uploads folder backup
        uploads_dir = Path(settings.UPLOAD_DIR)
        if not uploads_dir.is_absolute():
            uploads_dir = ROOT_DIR / uploads_dir
        if uploads_dir.exists():
            shutil.copytree(uploads_dir, temp_dir / "uploads", dirs_exist_ok=True)
            print(f"[+] Uploads directory archived: {uploads_dir}")

        # 3. Create compressed tar.gz archive
        with tarfile.open(archive_name, "w:gz") as tar:
            for item in temp_dir.iterdir():
                tar.add(item, arcname=item.name)

        size_kb = round(archive_name.stat().st_size / 1024, 2)
        print(f"[OK] Backup successfully created: {archive_name} ({size_kb} KB)")
        return str(archive_name)

    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)


if __name__ == "__main__":
    run_backup()
