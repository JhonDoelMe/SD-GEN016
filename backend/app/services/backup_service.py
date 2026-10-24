import os
import json
import zipfile
import hashlib
import datetime
import shutil
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional
from sqlalchemy import select, delete, insert, text, DateTime, Date, Time
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import settings
from backend.app.database import AsyncSessionLocal
from backend.app.core.timezone import now_facility
from backend.app.services.audit_service import log_audit
from backend.app.services.settings_service import get_runtime_setting, load_system_settings

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


SENSITIVE_ENV_KEYWORDS = ("SECRET", "PASSWORD", "PRIVATE_KEY", "TOKEN", "DATABASE_URL")
MAX_ZIP_FILES = 10_000
MAX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024  # 500 MB


def _copy_env_redacted(src_env: Path, dst_env: Path) -> None:
    """Copies .env file while masking sensitive secret values."""
    lines = src_env.read_text(encoding="utf-8", errors="replace").splitlines()
    redacted_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            redacted_lines.append(line)
            continue
        key, _, val = line.partition("=")
        key_upper = key.strip().upper()
        if any(kw in key_upper for kw in SENSITIVE_ENV_KEYWORDS):
            redacted_lines.append(f"{key.strip()}=***REDACTED***")
        else:
            redacted_lines.append(line)
    dst_env.write_text("\n".join(redacted_lines) + "\n", encoding="utf-8")


def _safe_extract_zip(zf: zipfile.ZipFile, dest_dir: Path) -> None:
    """
    Safely extracts a ZIP archive into dest_dir with protection against:
    - Zip Slip (path traversal outside dest_dir)
    - Zip Bomb (excessive uncompressed size or file count)
    """
    dest_resolved = dest_dir.resolve()
    infolist = zf.infolist()

    if len(infolist) > MAX_ZIP_FILES:
        raise ValueError(f"Архів містить забагато файлів ({len(infolist)} > {MAX_ZIP_FILES}). Можлива Zip-бомба.")

    total_uncompressed = 0
    for info in infolist:
        total_uncompressed += info.file_size
        if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
            raise ValueError("Розмір розпакованих даних перевищує допустимий ліміт (500 МБ). Можлива Zip-бомба.")

        member_path = Path(info.filename)
        if member_path.is_absolute() or ".." in member_path.parts:
            raise ValueError(f"Виявлено небезпечний шлях у архіві (Path Traversal): {info.filename}")

        target_path = (dest_resolved / member_path).resolve()
        if not target_path.is_relative_to(dest_resolved):
            raise ValueError(f"Виявлено спробу виходу за межі цільової директорії: {info.filename}")

    for info in infolist:
        zf.extract(info, path=dest_resolved)


# Strict topological order of tables for data export, import, and cascade-free deletion
TABLE_ORDER = [
    ("permissions", Permission),
    ("roles", Role),
    ("facilities", Facility),
    ("users", User),
    ("system_settings", SystemSetting),
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
    ("push_subscriptions", PushSubscription),
    ("notification_logs", NotificationLog),
    ("audit_logs", AuditLog),
]

M2M_TABLES = [
    ("user_roles", user_roles),
    ("role_permissions", role_permissions),
]


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


def prepare_rows_for_insert(model_cls: Any, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]:
]:
    """Clean and deserialize row dictionaries matching the model column types."""
    cols = model_cls.__table__.columns
    cleaned_rows = []
    for r in rows:
        cleaned = {}
        for col in cols:
            if col.name not in r:
                continue
            v = r[col.name]
            if v is not None and isinstance(v, str):
                if isinstance(col.type, (DateTime,)):
                    try:
                        v = datetime.datetime.fromisoformat(v)
                    except Exception:
                        pass
                elif isinstance(col.type, (Date,)):
                    try:
                        v = datetime.date.fromisoformat(v)
                    except Exception:
                        pass
                elif isinstance(col.type, (Time,)):
                    try:
                        v = datetime.time.fromisoformat(v)
                    except Exception:
                        pass
            cleaned[col.name] = v
        cleaned_rows.append(cleaned)
    return cleaned_rows


async def dump_all_tables_to_dict(session: AsyncSession) -> Dict[str, Any]:
    """Database-agnostic export of all tables to dict for JSON serialization."""
    export_data = {}
    counts = {}

    for table_name, model_cls in TABLE_ORDER:
        stmt = select(model_cls)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        export_data[table_name] = [model_row_to_dict(r) for r in rows]
        counts[table_name] = len(rows)

    # Export secondary many-to-many tables
    for m2m_name, m2m_table in M2M_TABLES:
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
    - 'partial' (or 'db_only'): Dump of database tables + SQLite DB + system configs + redacted .env.
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

        # 3. Copy configuration files (.env with secrets redacted, .env.example, docker-compose.yml, nginx.conf)
        config_staging = staging_dir / "config"
        config_staging.mkdir(exist_ok=True)
        for env_name in [".env", ".env.example"]:
            env_file = project_root / env_name
            if env_file.exists():
                if env_name == ".env":
                    _copy_env_redacted(env_file, config_staging / env_name)
                else:
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
            exclude_extensions = {".pyc", ".pyo", ".zip", ".pem", ".key"}

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

            # Copy root project files (redact .env if present)
            for root_f in project_root.iterdir():
                if root_f.is_file() and not any(root_f.name.endswith(ext) for ext in exclude_extensions):
                    try:
                        if root_f.name == ".env":
                            _copy_env_redacted(root_f, server_staging / root_f.name)
                        else:
                            shutil.copy2(root_f, server_staging / root_f.name)
                        total_server_files += 1
                    except Exception:
                        pass

            included_components.append(f"server_files/ ({total_server_files} файлів: вихідний код, медіа, скрипти)")

        # 5. Generate manifest.json
        manifest = {
            "app_name": "Service Desk Бензинового Генератора (SD-GEN016)",
            "app_version": "4.5.0",
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

    zip_candidates = sorted(
        list(backup_dir.glob("backup_*.zip")) + list(backup_dir.glob("uploaded_*.zip")),
        key=lambda x: x.stat().st_mtime,
        reverse=True
    )

    for item in zip_candidates:
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
    if not safe_name.endswith(".zip") or not (safe_name.startswith("backup_") or safe_name.startswith("uploaded_")):
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


def inspect_backup(zip_path: Path) -> Dict[str, Any]:
    """Inspects a backup zip archive and extracts manifest and metadata."""
    if not zip_path.exists() or not zip_path.is_file():
        raise FileNotFoundError(f"Файл резервної копії не знайдено: {zip_path.name}")

    size_bytes = zip_path.stat().st_size
    manifest = None
    namelist = []

    with zipfile.ZipFile(zip_path, "r") as zf:
        namelist = zf.namelist()
        if "manifest.json" in namelist:
            try:
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            except Exception:
                manifest = None

    if not manifest:
        manifest = {
            "backup_id": zip_path.stem,
            "filename": zip_path.name,
            "backup_type": "full" if "full" in zip_path.name else "partial",
            "backup_type_ua": "Повний бекап" if "full" in zip_path.name else "Частковий бекап",
            "created_at": datetime.datetime.fromtimestamp(zip_path.stat().st_mtime).isoformat(),
            "created_by": "unknown",
            "notes": "",
            "table_records_count": {},
            "tables_count": 0,
            "records_count": 0,
            "server_files_count": len([n for n in namelist if n.startswith("server_files/")]),
        }

    return {
        "filename": zip_path.name,
        "size_bytes": size_bytes,
        "size_formatted": format_file_size(size_bytes),
        "manifest": manifest,
        "has_database_export": "database_export.json" in namelist,
        "has_server_files": any(n.startswith("server_files/") for n in namelist),
        "has_uploads": any(n.startswith("server_files/uploads/") or n.startswith("uploads/") for n in namelist),
        "total_files": len(namelist),
    }


async def restore_backup(
    session: AsyncSession,
    zip_path: Path,
    restore_files: bool = True,
    creator: str = "superadmin",
    creator_ip: str = "127.0.0.1"
) -> Dict[str, Any]:
    """
    Performs full system restore from backup .zip:
    1. Validates zip file and manifest (with Zip Slip & Zip Bomb protection).
    2. Creates an automated safety snapshot before starting.
    3. Cleans up existing DB tables (handling foreign keys and engines).
    4. Populates database from database_export.json with proper deserialization.
    5. Resets sequences (if PostgreSQL).
    6. Restores uploads/ if present and restore_files is True.
    7. Refreshes in-memory system settings.
    8. Records audit log.
    """
    if not zip_path.exists() or not zip_path.is_file():
        raise FileNotFoundError(f"Файл резервної копії не знайдено: {zip_path.name}")

    backup_dir = get_backup_dir()
    staging_dir = backup_dir / f"_staging_restore_{int(datetime.datetime.now().timestamp())}_{zip_path.stem}"
    staging_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1. Safely unzip archive into staging (protects against Zip Slip & Zip Bomb)
        with zipfile.ZipFile(zip_path, "r") as zf:
            _safe_extract_zip(zf, staging_dir)

        # 2. Validate manifest and database_export.json
        manifest_file = staging_dir / "manifest.json"
        manifest = {}
        if manifest_file.exists():
            with open(manifest_file, "r", encoding="utf-8") as f:
                manifest = json.load(f)

        db_export_file = staging_dir / "database_export.json"
        if not db_export_file.exists():
            raise ValueError("У резервній копії відсутній обов'язковий файл 'database_export.json'!")

        with open(db_export_file, "r", encoding="utf-8") as f:
            tables_data = json.load(f)

        # 3. Create automated pre-restore safety backup
        safety_manifest = await create_backup(
            session=session,
            backup_type="partial",
            creator=f"{creator}_pre_restore",
            creator_ip=creator_ip,
            notes=f"Автоматичний snapshot безпеки перед відновленням з {zip_path.name}"
        )

        # 4. Clear database tables
        if settings.is_sqlite:
            await session.execute(text("PRAGMA foreign_keys = OFF;"))

        # Delete in reverse topological order
        for m2m_name, m2m_table in reversed(M2M_TABLES):
            await session.execute(delete(m2m_table))

        for table_name, model_cls in reversed(TABLE_ORDER):
            await session.execute(delete(model_cls))

        # 5. Populate database in forward topological order
        restored_counts = {}
        for table_name, model_cls in TABLE_ORDER:
            rows = tables_data.get(table_name, [])
            if rows:
                cleaned_rows = prepare_rows_for_insert(model_cls, rows)
                await session.execute(insert(model_cls), cleaned_rows)
            restored_counts[table_name] = len(rows)

        for m2m_name, m2m_table in M2M_TABLES:
            rows = tables_data.get(m2m_name, [])
            if rows:
                await session.execute(insert(m2m_table), rows)
            restored_counts[m2m_name] = len(rows)

        if settings.is_sqlite:
            await session.execute(text("PRAGMA foreign_keys = ON;"))
        else:
            # PostgreSQL sequence reset for tables with autoincrement ID
            for table_name, model_cls in TABLE_ORDER:
                if "id" in model_cls.__table__.columns:
                    seq_sql = text(f"""
                        SELECT setval(
                            pg_get_serial_sequence('{table_name}', 'id'),
                            COALESCE((SELECT MAX(id) FROM {table_name}), 1),
                            (SELECT MAX(id) FROM {table_name}) IS NOT NULL
                        );
                    """)
                    try:
                        await session.execute(seq_sql)
                    except Exception:
                        pass

        await session.commit()

        # 6. Refresh in-memory system settings cache
        await load_system_settings(session)

        # 7. Restore media files (uploads) if requested
        restored_files_count = 0
        if restore_files:
            uploads_dest = Path(settings.UPLOAD_DIR).resolve()
            uploads_dest.mkdir(parents=True, exist_ok=True)

            potential_sources = [
                staging_dir / "server_files" / "uploads",
                staging_dir / "uploads"
            ]
            for u_src in potential_sources:
                if u_src.exists() and u_src.is_dir():
                    for root, _, files in os.walk(u_src):
                        rel_dir = Path(root).relative_to(u_src)
                        cur_target = (uploads_dest / rel_dir).resolve()
                        if not cur_target.is_relative_to(uploads_dest):
                            continue
                        cur_target.mkdir(parents=True, exist_ok=True)
                        for f_name in files:
                            safe_f = Path(f_name).name
                            shutil.copy2(Path(root) / safe_f, cur_target / safe_f)
                            restored_files_count += 1

        # 8. Audit log
        total_records = sum(restored_counts.values())
        await log_audit(
            db=session,
            action="BACKUP_RESTORE",
            entity_type="backup",
            entity_id=zip_path.stem,
            details={
                "message": f"Успішно відновлено систему з резервної копії '{zip_path.name}'",
                "filename": zip_path.name,
                "safety_backup_id": safety_manifest.get("backup_id"),
                "safety_backup_file": safety_manifest.get("filename"),
                "records_restored": total_records,
                "tables_count": len(restored_counts),
                "media_files_restored": restored_files_count,
                "restore_files": restore_files,
            },
            ip_address=creator_ip
        )

        return {
            "status": "success",
            "message": f"Систему успішно відновлено з резервної копії '{zip_path.name}'!",
            "filename": zip_path.name,
            "safety_backup_filename": safety_manifest.get("filename"),
            "safety_backup_id": safety_manifest.get("backup_id"),
            "records_restored": total_records,
            "tables_restored_count": len(restored_counts),
            "media_files_restored": restored_files_count,
            "restored_at": now_facility().isoformat(),
        }

    finally:
        # Cleanup temporary staging folder
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)


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
