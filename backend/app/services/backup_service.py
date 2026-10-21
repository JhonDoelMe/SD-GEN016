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
    Creates a full or partial backup packaged as a .zip archive:
    - 'full': Complete copy of the server (all files, code, configs, uploads, scripts) + DB dump.
    - 'partial' (or 'db_only'): Dump of database tables + SQLite DB + system configs + .env.
    """
    backup_dir = get_backup_dir()
    now = now_facility()
    timestamp_str = now.strftime("%Y%m%d_%H%M%S")
    clean_type = "partial" if backup_type in ("partial", "db_only") else "full"
    backup_id = f"backup_{clean_type}_{timestamp_str}"
    zip_filename = f"{backup_id}.zip"
    zip_path = backup_dir / zip_filename

    staging_dir = backup_dir / f"_staging_{backup_id}"
    staging_dir.mkdir(parents=True, exist_ok=True)

    project_root = Path(__file__).resolve().parents[3]

    try:
        # 1. Export DB data to JSON (portable across SQLite and PostgreSQL)
        db_dump = await dump_all_tables_to_dict(session)
        db_dump_file = staging_dir / "database_export.json"
        with open(db_dump_file, "w", encoding="utf-8") as f:
            json.dump(db_dump["tables"], f, ensure_ascii=False, indent=2)

        included_components = ["database_export.json (дамп 20 таблиць БД)"]

        # 2. If SQLite, copy service_desk.db directly as well
        if settings.is_sqlite:
            root_db = (project_root / "service_desk.db").resolve()
            if root_db.exists():
                shutil.copy2(root_db, staging_dir / "service_desk.db")
                included_components.append("service_desk.db (фізична база даних)")

        # 3. Copy configuration files (.env, .env.example, docker-compose.yml, nginx.conf)
        config_staging = staging_dir / "config"
        config_staging.mkdir(exist_ok=True)
        for env_name in [".env", ".env.example"]:
            env_file = project_root / env_name
            if env_file.exists():
                shutil.copy2(env_file, config_staging / env_name)
                included_components.append(f"config/{env_name}")

        for cfg_rel in ["docker-compose.yml", "alembic.ini", "Dockerfile"]:
            cfg_file = project_root / cfg_rel
            if cfg_file.exists():
                shutil.copy2(cfg_file, config_staging / cfg_rel)
                included_components.append(f"config/{cfg_rel}")

        nginx_cfg = project_root / "docker" / "nginx.conf"
        if nginx_cfg.exists():
            shutil.copy2(nginx_cfg, config_staging / "nginx.conf")
            included_components.append("config/nginx.conf")

        # 4. If Full backup, copy entire server codebase, uploads, scripts, docs
        total_server_files = 0
        if clean_type == "full":
            server_staging = staging_dir / "server_files"
            server_staging.mkdir(exist_ok=True)

            exclude_dirs = {
                ".git", ".pytest_cache", "__pycache__", "backups", "venv", ".venv",
                ".idea", ".vscode", "node_modules"
            }
            exclude_extensions = {".pyc", ".pyo", ".zip"}

            target_dirs = ["backend", "frontend", "docker", "scripts", "docs", "uploads"]
            for dir_name in target_dirs:
                src_dir = project_root / dir_name
                if src_dir.exists() and src_dir.is_dir():
                    for root_path, dirs, files in os.walk(src_dir):
                        dirs[:] = [d for d in dirs if d not in exclude_dirs and not d.startswith("_staging_")]
                        rel = Path(root_path).relative_to(project_root)
                        cur_dest = server_staging / rel
                        cur_dest.mkdir(parents=True, exist_ok=True)
                        for file_name in files:
                            if any(file_name.endswith(ext) for ext in exclude_extensions):
                                continue
                            src_file = Path(root_path) / file_name
                            try:
                                shutil.copy2(src_file, cur_dest / file_name)
                                total_server_files += 1
                            except Exception:
                                pass

            # Copy root project files
            for root_f in project_root.iterdir():
                if root_f.is_file() and not any(root_f.name.endswith(ext) for ext in exclude_extensions):
                    try:
                        shutil.copy2(root_f, server_staging / root_f.name)
                        total_server_files += 1
                    except Exception:
                        pass

            included_components.append(f"server_files/ ({total_server_files} файлів: вихідний код, медіа, скрипти)")

        # 5. Generate manifest.json
        manifest = {
            "app_name": "Service Desk Бензинового Генератора (SD-GEN016)",
            "app_version": "4.1.0",
            "backup_id": backup_id,
            "filename": zip_filename,
            "backup_type": clean_type,
            "backup_type_ua": "Повний бекап (повна копія сервера, файлів + дамп БД)" if clean_type == "full" else "Частковий бекап (дамп БД, конфігурація, .env)",
            "created_at": now.isoformat(),
            "created_by": creator,
            "created_by_ip": creator_ip,
            "notes": notes,
            "database_dialect": "sqlite" if settings.is_sqlite else "postgresql",
            "table_records_count": db_dump["counts"],
            "tables_count": len(db_dump["counts"]),
            "records_count": sum(db_dump["counts"].values()),
            "server_files_count": total_server_files if clean_type == "full" else len(included_components),
            "included_components": included_components,
        }

        manifest_file = staging_dir / "manifest.json"
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        # 6. Build ZIP archive (single pass, perfectly packaged)
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(staging_dir):
                for file in files:
                    abs_path = Path(root) / file
                    rel_path = abs_path.relative_to(staging_dir)
                    zf.write(abs_path, arcname=str(rel_path))

        # 7. Compute final file stats
        size_bytes = zip_path.stat().st_size
        sha256_hash = compute_sha256(zip_path)

        manifest["size_bytes"] = size_bytes
        manifest["size_formatted"] = format_file_size(size_bytes)
        manifest["sha256"] = sha256_hash

        # 8. Audit Log
        await log_audit(
            db=session,
            action="BACKUP_CREATE",
            entity_type="backup",
            entity_id=backup_id,
            details={
                "message": f"Створено {manifest['backup_type_ua']} '{zip_filename}' розміром {manifest['size_formatted']}",
                "records_count": sum(db_dump["counts"].values()),
                "files_count": total_server_files if clean_type == "full" else len(included_components),
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
            b_type = manifest.get("backup_type", "unknown")
            if b_type in ("partial", "db_only"):
                b_type = "partial"
            elif b_type == "full":
                b_type = "full"

            table_counts = manifest.get("table_records_count", {})
            entry = {
                "backup_id": manifest.get("backup_id", item.stem),
                "filename": item.name,
                "backup_type": b_type,
                "type": b_type,
                "backup_type_ua": manifest.get("backup_type_ua", "Повний бекап" if b_type == "full" else "Частковий бекап"),
                "created_at": manifest.get("created_at", modified_time.isoformat()),
                "created_by": manifest.get("created_by", "system"),
                "notes": manifest.get("notes", ""),
                "note": manifest.get("notes", ""),
                "size_bytes": size_bytes,
                "size_formatted": format_file_size(size_bytes),
                "sha256": manifest.get("sha256", ""),
                "table_records_count": table_counts,
                "tables_count": manifest.get("tables_count", len(table_counts) if isinstance(table_counts, dict) else 0),
                "records_count": manifest.get("records_count", sum(table_counts.values()) if isinstance(table_counts, dict) else 0),
                "files_count": manifest.get("server_files_count", manifest.get("uploads_files_count", 0)),
            }
        else:
            b_type = "partial" if any(x in item.name for x in ("partial", "db_only")) else "full"
            entry = {
                "backup_id": item.stem,
                "filename": item.name,
                "backup_type": b_type,
                "type": b_type,
                "backup_type_ua": "Повний бекап" if b_type == "full" else "Частковий бекап",
                "created_at": modified_time.isoformat(),
                "created_by": "unknown",
                "notes": "",
                "note": "",
                "size_bytes": size_bytes,
                "size_formatted": format_file_size(size_bytes),
                "sha256": "",
                "table_records_count": {},
                "tables_count": 0,
                "records_count": 0,
                "files_count": 0,
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
