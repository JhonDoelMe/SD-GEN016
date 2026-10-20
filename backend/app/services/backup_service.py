import os
import json
import zipfile
import hashlib
import datetime
import shutil
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import settings
from backend.app.database import AsyncSessionLocal
from backend.app.core.timezone import now_facility
from backend.app.services.audit_service import log_audit
from backend.app.services.settings_service import get_runtime_setting

# Import all models to serialize data for database-agnostic JSON export
from backend.app.models.facility import Facility
from backend.app.models.generator import Generator, GeneratorSchedule, GeneratorRun
from backend.app.models.fuel import FuelStock, FuelReceipt, FuelTransfer
from backend.app.models.maintenance import MaintenanceSchedule, MaintenanceRecord
from backend.app.models.fault import Fault
from backend.app.models.audit import AuditLog, SystemAdjustment
from backend.app.models.user import User, Role, Permission, user_roles, role_permissions
from backend.app.models.settings import SystemSetting
from backend.app.models.notification import PushSubscription, NotificationLog


def get_backup_dir() -> Path:
    backup_path = Path(settings.BACKUP_DIR).resolve()
    backup_path.mkdir(parents=True, exist_ok=True)
    return backup_path


def format_file_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} Б"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} КБ"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} МБ"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} ГБ"


def compute_sha256(file_path: Path) -> str:
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            sha.update(chunk)
    return sha.hexdigest()


def model_row_to_dict(row: Any) -> Dict[str, Any]:
    """Serialize an SQLAlchemy model instance into JSON-friendly dict."""
    data = {}
    for col in row.__table__.columns:
        val = getattr(row, col.name)
        if isinstance(val, (datetime.datetime, datetime.date, datetime.time)):
            data[col.name] = val.isoformat()
        else:
            data[col.name] = val
    return data


async def dump_all_tables_to_dict(session: AsyncSession) -> Dict[str, Any]:
    """Database-agnostic export of all tables to dict for JSON serialization."""
    models_to_export = [
        ("facilities", Facility),
        ("generators", Generator),
        ("generator_schedules", GeneratorSchedule),
        ("generator_runs", GeneratorRun),
        ("fuel_stocks", FuelStock),
        ("fuel_receipts", FuelReceipt),
        ("fuel_transfers", FuelTransfer),
        ("maintenance_schedules", MaintenanceSchedule),
        ("maintenance_records", MaintenanceRecord),
        ("faults", Fault),
        ("system_adjustments", SystemAdjustment),
        ("users", User),
        ("roles", Role),
        ("permissions", Permission),
        ("system_settings", SystemSetting),
        ("push_subscriptions", PushSubscription),
        ("notification_logs", NotificationLog),
        ("audit_logs", AuditLog),
    ]

    export_data = {}
    counts = {}

    for table_name, model_cls in models_to_export:
        stmt = select(model_cls)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        export_data[table_name] = [model_row_to_dict(r) for r in rows]
        counts[table_name] = len(rows)

    # Export secondary many-to-many tables
    for m2m_name, m2m_table in [("user_roles", user_roles), ("role_permissions", role_permissions)]:
        res = await session.execute(select(m2m_table))
        rows = [dict(r._mapping) for r in res.all()]
        export_data[m2m_name] = rows
        counts[m2m_name] = len(rows)

    return {"tables": export_data, "counts": counts}


async def create_backup(
    session: AsyncSession,
    backup_type: str = "full",
    creator: str = "superadmin",
    creator_ip: str = "127.0.0.1",
    notes: str = ""
) -> Dict[str, Any]:
    """
    Creates a full or DB-only backup packaged as a .zip archive.
    Includes database_export.json, raw db file (if SQLite), uploads/ (if full), and manifest.json.
    """
    backup_dir = get_backup_dir()
    now = now_facility()
    timestamp_str = now.strftime("%Y%m%d_%H%M%S")
    backup_id = f"backup_{backup_type}_{timestamp_str}"
    zip_filename = f"{backup_id}.zip"
    zip_path = backup_dir / zip_filename

    staging_dir = backup_dir / f"_staging_{backup_id}"
    staging_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1. Export DB data to JSON (portable across SQLite and PostgreSQL)
        db_dump = await dump_all_tables_to_dict(session)
        db_dump_file = staging_dir / "database_export.json"
        with open(db_dump_file, "w", encoding="utf-8") as f:
            json.dump(db_dump["tables"], f, ensure_ascii=False, indent=2)

        included_files = ["database_export.json"]

        # 2. If SQLite, copy service_desk.db directly as well
        if settings.is_sqlite:
            root_db = Path("service_desk.db").resolve()
            if root_db.exists():
                shutil.copy2(root_db, staging_dir / "service_desk.db")
                included_files.append("service_desk.db")

        # 3. If Full backup, copy uploads folder
        uploads_count = 0
        if backup_type == "full":
            uploads_src = Path(settings.UPLOAD_DIR).resolve()
            if uploads_src.exists() and uploads_src.is_dir():
                uploads_dest = staging_dir / "uploads"
                uploads_dest.mkdir(exist_ok=True)
                for root, _, files in os.walk(uploads_src):
                    rel_dir = Path(root).relative_to(uploads_src)
                    target_dir = uploads_dest / rel_dir
                    target_dir.mkdir(parents=True, exist_ok=True)
                    for file in files:
                        src_file = Path(root) / file
                        shutil.copy2(src_file, target_dir / file)
                        uploads_count += 1
                included_files.append(f"uploads/ ({uploads_count} файлів)")

        # 4. Generate manifest.json
        manifest = {
            "app_name": "Service Desk Бензинового Генератора (SD-GEN016)",
            "app_version": "4.1.0",
            "backup_id": backup_id,
            "filename": zip_filename,
            "backup_type": backup_type,
            "created_at": now.isoformat(),
            "created_by": creator,
            "created_by_ip": creator_ip,
            "notes": notes,
            "database_dialect": "sqlite" if settings.is_sqlite else "postgresql",
            "table_records_count": db_dump["counts"],
            "uploads_files_count": uploads_count,
            "included_components": included_files,
        }

        manifest_file = staging_dir / "manifest.json"
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        # 5. Build ZIP archive (single pass, perfectly packaged)
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(staging_dir):
                for file in files:
                    abs_path = Path(root) / file
                    rel_path = abs_path.relative_to(staging_dir)
                    zf.write(abs_path, arcname=str(rel_path))

        # 6. Compute final file stats
        size_bytes = zip_path.stat().st_size
        sha256_hash = compute_sha256(zip_path)

        manifest["size_bytes"] = size_bytes
        manifest["size_formatted"] = format_file_size(size_bytes)
        manifest["sha256"] = sha256_hash

        # 7. Audit Log
        await log_audit(
            db=session,
            action="BACKUP_CREATE",
            entity_type="backup",
            entity_id=backup_id,
            details={
                "message": f"Створено {backup_type} резервну копію '{zip_filename}' розміром {manifest['size_formatted']}",
                "records_count": sum(db_dump["counts"].values()),
                "uploads_count": uploads_count,
                "notes": notes,
            },
            ip_address=creator_ip
        )

        return manifest

    finally:
        # Cleanup temporary staging folder
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)


def list_backups() -> List[Dict[str, Any]]:
    """List all available backup archives with their metadata."""
    backup_dir = get_backup_dir()
    results = []

    for item in backup_dir.glob("backup_*.zip"):
        if not item.is_file():
            continue

        size_bytes = item.stat().st_size
        modified_time = datetime.datetime.fromtimestamp(item.stat().st_mtime)

        # Try to read manifest.json from inside the ZIP
        manifest = None
        try:
            with zipfile.ZipFile(item, "r") as zf:
                if "manifest.json" in zf.namelist():
                    manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        except Exception:
            manifest = None

        if manifest:
            entry = {
                "backup_id": manifest.get("backup_id", item.stem),
                "filename": item.name,
                "backup_type": manifest.get("backup_type", "unknown"),
                "created_at": manifest.get("created_at", modified_time.isoformat()),
                "created_by": manifest.get("created_by", "system"),
                "notes": manifest.get("notes", ""),
                "size_bytes": size_bytes,
                "size_formatted": format_file_size(size_bytes),
                "sha256": manifest.get("sha256", ""),
                "table_records_count": manifest.get("table_records_count", {}),
                "uploads_files_count": manifest.get("uploads_files_count", 0),
            }
        else:
            b_type = "db_only" if "db_only" in item.name else "full"
            entry = {
                "backup_id": item.stem,
                "filename": item.name,
                "backup_type": b_type,
                "created_at": modified_time.isoformat(),
                "created_by": "unknown",
                "notes": "",
                "size_bytes": size_bytes,
                "size_formatted": format_file_size(size_bytes),
                "sha256": "",
                "table_records_count": {},
                "uploads_files_count": 0,
            }

        results.append(entry)

    # Sort descending by creation date (newest first)
    results.sort(key=lambda x: x["created_at"], reverse=True)
    return results


async def delete_backup(session: AsyncSession, filename: str, user_login: str, ip_address: str) -> bool:
    """Safely delete a backup file."""
    # Sanitize filename
    safe_name = Path(filename).name
    if not safe_name.endswith(".zip") or not safe_name.startswith("backup_"):
        raise ValueError("Неприпустима назва файлу резервної копії")

    backup_dir = get_backup_dir()
    target_file = backup_dir / safe_name

    if not target_file.exists() or not target_file.is_file():
        return False

    size_formatted = format_file_size(target_file.stat().st_size)
    target_file.unlink()

    await log_audit(
        db=session,
        action="BACKUP_DELETE",
        entity_type="backup",
        entity_id=safe_name,
        details={
            "message": f"Видалено резервну копію '{safe_name}' ({size_formatted})"
        },
        ip_address=ip_address
    )
    return True


def rotate_backups(keep_count: int = 7) -> List[str]:
    """Deletes old backups keeping only the most recent keep_count files."""
    if keep_count <= 0:
        return []

    backups = list_backups()
    if len(backups) <= keep_count:
        return []

    deleted = []
    backup_dir = get_backup_dir()
    for extra in backups[keep_count:]:
        target = backup_dir / extra["filename"]
        if target.exists():
            target.unlink(missing_ok=True)
            deleted.append(extra["filename"])

    return deleted


async def run_backup_scheduler():
    """
    Background worker that runs scheduled automatic backups at configured facility time.
    """
    last_run_day = None

    while True:
        try:
            await asyncio.sleep(25)

            enabled = get_runtime_setting("backup_auto_enabled", False)
            if not enabled:
                continue

            schedule_time = get_runtime_setting("backup_schedule_time", "03:00")
            frequency = get_runtime_setting("backup_frequency", "daily")
            retention_count = int(get_runtime_setting("backup_retention_count", 7))
            b_type = get_runtime_setting("backup_default_type", "full")

            now = now_facility()
            today_str = now.strftime("%Y-%m-%d")
            current_hm = now.strftime("%H:%M")

            # Check frequency condition (if weekly, check if today is Sunday, weekday() == 6)
            if frequency == "weekly" and now.weekday() != 6:
                continue

            if current_hm == schedule_time and last_run_day != today_str:
                last_run_day = today_str
                print(f"[BACKUP_SCHEDULER] Triggering scheduled {b_type} backup at {now}...", flush=True)

                async with AsyncSessionLocal() as session:
                    await create_backup(
                        session=session,
                        backup_type=b_type,
                        creator="SYSTEM_SCHEDULER",
                        creator_ip="127.0.0.1",
                        notes=f"Автоматичний бекап за розкладом ({schedule_time})"
                    )
                    removed = rotate_backups(retention_count)
                    if removed:
                        print(f"[BACKUP_SCHEDULER] Rotated {len(removed)} old backups: {removed}", flush=True)

        except asyncio.CancelledError:
            print("[BACKUP_SCHEDULER] Worker cancelled.", flush=True)
            break
        except Exception as e:
            print(f"[BACKUP_SCHEDULER_ERROR] {e}", flush=True)
            await asyncio.sleep(60)
