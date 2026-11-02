import os
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from backend.app.config import settings
from backend.app.database import engine, Base, AsyncSessionLocal
from backend.app.models import *  # noqa: F401, F403 Ensure all models loaded
from backend.app.services.init_service import seed_initial_data
from backend.app.services.audit_service import sanitize_historical_audit_logs
from backend.app.services.backup_service import run_backup_scheduler
from backend.app.services.operational_guard_service import run_operational_guard_loop
from backend.app.services.yasno_service import run_yasno_checker_loop
from backend.app.api.v1 import api_v1_router


from sqlalchemy import inspect, text


def ensure_schema_updates(sync_conn):
    """
    MAIN-01, MAIN-02: Controlled schema updates are handled via Alembic migrations.
    This startup check only guarantees default facility record and PostgreSQL sequence synchronization.
    """
    inspector = inspect(sync_conn)
    tables = inspector.get_table_names()

    # 1. Facilities default record
    default_facility_id = None
    if "facilities" in tables:
        fac_cols = [c["name"] for c in inspector.get_columns("facilities")]
        bool_def = "FALSE" if sync_conn.dialect.name == "postgresql" else "0"
        if "yasno_enabled" not in fac_cols:
            sync_conn.execute(text(f"ALTER TABLE facilities ADD COLUMN yasno_enabled BOOLEAN DEFAULT {bool_def}"))
        if "yasno_region_id" not in fac_cols:
            sync_conn.execute(text("ALTER TABLE facilities ADD COLUMN yasno_region_id INTEGER DEFAULT 3"))
        if "yasno_dso_id" not in fac_cols:
            sync_conn.execute(text("ALTER TABLE facilities ADD COLUMN yasno_dso_id INTEGER DEFAULT 301"))
        if "yasno_group" not in fac_cols:
            sync_conn.execute(text("ALTER TABLE facilities ADD COLUMN yasno_group VARCHAR(10)"))
        if "default_fuel_provider" not in fac_cols:
            sync_conn.execute(text("ALTER TABLE facilities ADD COLUMN default_fuel_provider VARCHAR(30) DEFAULT 'wog'"))

        res = sync_conn.execute(text("SELECT COUNT(*) FROM facilities")).scalar()
        if res == 0:
            sync_conn.execute(
                text(
                    "INSERT INTO facilities (name, address, description, timezone, yasno_enabled, yasno_region_id, yasno_dso_id, yasno_group, created_at, updated_at) "
                    "VALUES (:name, :address, :desc, :tz, :yasno_enabled, :region_id, :dso_id, :group, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {
                    "name": "Основний об'єкт",
                    "address": "Головна локація",
                    "desc": "Базовий об'єкт генератора",
                    "tz": "Europe/Kyiv",
                    "yasno_enabled": False,
                    "region_id": 3,
                    "dso_id": 301,
                    "group": None,
                }
            )
        default_facility_id = sync_conn.execute(text("SELECT id FROM facilities ORDER BY id ASC LIMIT 1")).scalar()

    # 3. Add facility_id to related tables (strictly whitelisted identifiers)
    allowed_facility_tables = ("generators", "fuel_stocks", "fuel_receipts", "fuel_transfers", "users", "system_adjustments")
    for table_name in allowed_facility_tables:
        if table_name in tables:
            cols = [c["name"] for c in inspector.get_columns(table_name)]
            if "facility_id" not in cols:
                sync_conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN facility_id INTEGER REFERENCES facilities(id) ON DELETE SET NULL"))
            # Only associate generators & fuel_stocks if facility_id is null and an existing facility exists
            if default_facility_id is not None and table_name in ("generators", "fuel_stocks"):
                sync_conn.execute(
                    text(f"UPDATE {table_name} SET facility_id = :fid WHERE facility_id IS NULL"),
                    {"fid": default_facility_id}
                )

    # Ensure PostgreSQL constraints have ON DELETE SET NULL for foreign keys referencing facilities(id)
    if sync_conn.dialect.name == "postgresql":
        fk_set_null_tables = ("system_adjustments", "fuel_receipts", "fuel_transfers", "users", "push_subscriptions", "notification_logs")
        for tbl in fk_set_null_tables:
            if tbl in tables:
                try:
                    with sync_conn.begin_nested():
                        sync_conn.execute(text(f"""
                            DO $$
                            BEGIN
                                IF EXISTS (
                                    SELECT 1 FROM information_schema.table_constraints 
                                    WHERE constraint_name = '{tbl}_facility_id_fkey' 
                                    AND table_name = '{tbl}'
                                ) THEN
                                    ALTER TABLE {tbl} DROP CONSTRAINT {tbl}_facility_id_fkey;
                                    ALTER TABLE {tbl} ADD CONSTRAINT {tbl}_facility_id_fkey 
                                        FOREIGN KEY (facility_id) REFERENCES facilities(id) ON DELETE SET NULL;
                                END IF;
                            END $$;
                        """))
                except Exception as ex:
                    print(f"[DB] FK upgrade notice for {tbl}: {ex}", flush=True)

    if "system_adjustments" in tables:
        cols = [c["name"] for c in inspector.get_columns("system_adjustments")]
        if "target_name" not in cols:
            sync_conn.execute(text("ALTER TABLE system_adjustments ADD COLUMN target_name VARCHAR(200)"))

    if sync_conn.dialect.name == "postgresql":
        sync_conn.execute(text("ALTER TABLE fuel_stocks ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE"))
        sync_conn.execute(text("ALTER TABLE fuel_receipts ADD COLUMN IF NOT EXISTS fuel_provider VARCHAR(50) DEFAULT 'wog'"))
        sync_conn.execute(text("ALTER TABLE fuel_receipts ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)"))
        sync_conn.execute(text("ALTER TABLE fuel_transfers ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)"))
        sync_conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_fuel_receipts_idempotency_key ON fuel_receipts(idempotency_key)"))
        sync_conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_fuel_transfers_idempotency_key ON fuel_transfers(idempotency_key)"))
        sync_conn.execute(text("ALTER TABLE generators ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE"))
        sync_conn.execute(text("ALTER TABLE generators ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP"))
        sync_conn.execute(text("ALTER TABLE generator_runs ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)"))
        sync_conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_generator_runs_idempotency_key ON generator_runs(idempotency_key)"))
        sync_conn.execute(text(
            "UPDATE generator_runs SET status = 'COMPLETED', end_time = COALESCE(end_time, start_time), "
            "end_hours = COALESCE(end_hours, start_hours), duration_seconds = COALESCE(duration_seconds, 0), "
            "duration_hours = COALESCE(duration_hours, 0.0), calculated_consumption_l = COALESCE(calculated_consumption_l, 0.0) "
            "WHERE status = 'RUNNING' AND id NOT IN (SELECT MAX(id) FROM generator_runs WHERE status = 'RUNNING' GROUP BY generator_id)"
        ))
        sync_conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_generator_runs_one_active ON generator_runs(generator_id) WHERE status = 'RUNNING'"))
    else:
        if "fuel_stocks" in tables:
            cols = [c["name"] for c in inspector.get_columns("fuel_stocks")]
            if "is_active" not in cols:
                sync_conn.execute(text("ALTER TABLE fuel_stocks ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1"))

        if "fuel_receipts" in tables:
            cols = [c["name"] for c in inspector.get_columns("fuel_receipts")]
            if "fuel_provider" not in cols:
                sync_conn.execute(text("ALTER TABLE fuel_receipts ADD COLUMN fuel_provider VARCHAR(50) DEFAULT 'wog'"))
            if "idempotency_key" not in cols:
                sync_conn.execute(text("ALTER TABLE fuel_receipts ADD COLUMN idempotency_key VARCHAR(64)"))
                try:
                    sync_conn.execute(text("CREATE UNIQUE INDEX ix_fuel_receipts_idempotency_key ON fuel_receipts(idempotency_key)"))
                except Exception:
                    pass

        if "fuel_transfers" in tables:
            cols = [c["name"] for c in inspector.get_columns("fuel_transfers")]
            if "idempotency_key" not in cols:
                sync_conn.execute(text("ALTER TABLE fuel_transfers ADD COLUMN idempotency_key VARCHAR(64)"))
                try:
                    sync_conn.execute(text("CREATE UNIQUE INDEX ix_fuel_transfers_idempotency_key ON fuel_transfers(idempotency_key)"))
                except Exception:
                    pass

        if "generators" in tables:
            cols = [c["name"] for c in inspector.get_columns("generators")]
            if "is_active" not in cols:
                sync_conn.execute(text("ALTER TABLE generators ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1"))
            if "archived_at" not in cols:
                sync_conn.execute(text("ALTER TABLE generators ADD COLUMN archived_at TIMESTAMP"))

        if "generator_runs" in tables:
            cols = [c["name"] for c in inspector.get_columns("generator_runs")]
            if "idempotency_key" not in cols:
                sync_conn.execute(text("ALTER TABLE generator_runs ADD COLUMN idempotency_key VARCHAR(64)"))
                try:
                    sync_conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_generator_runs_idempotency_key ON generator_runs(idempotency_key)"))
                except Exception:
                    pass
            try:
                sync_conn.execute(text(
                    "UPDATE generator_runs SET status = 'COMPLETED', end_time = COALESCE(end_time, start_time) "
                    "WHERE status = 'RUNNING' AND id NOT IN (SELECT MAX(id) FROM generator_runs WHERE status = 'RUNNING' GROUP BY generator_id)"
                ))
                sync_conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_generator_runs_one_active ON generator_runs(generator_id) WHERE status = 'RUNNING'"))
            except Exception:
                pass

    # 4. Fix maintenance schedule anomaly: interval=300, next_due=535 -> next_due=300, last_performed=0
    if "maintenance_schedules" in tables:
        sync_conn.execute(text(
            "UPDATE maintenance_schedules SET last_performed_hours = 0.0, next_due_hours = interval_hours "
            "WHERE (last_performed_hours = 235.0 AND next_due_hours = 535.0) "
            "OR (last_performed_hours = 235.0 AND next_due_hours > 300.0)"
        ))

    # 5. Synchronize sequences for PostgreSQL to avoid duplicate key errors on auto-incrementing IDs
    if sync_conn.dialect.name == "postgresql":
        serial_tables = (
            "facilities", "generators", "fuel_stocks", "fuel_receipts",
            "fuel_transfers", "users", "roles", "permissions",
            "maintenance_schedules", "maintenance_records",
            "generator_runs", "faults", "audit_logs", "system_adjustments",
            "push_subscriptions", "notification_logs", "password_resets"
        )
        for tbl in serial_tables:
            if tbl in tables:
                try:
                    with sync_conn.begin_nested():
                        sync_conn.execute(text(f"""
                            SELECT setval(
                                pg_get_serial_sequence('{tbl}', 'id'),
                                COALESCE((SELECT MAX(id) FROM {tbl}), 1),
                                (SELECT MAX(id) IS NOT NULL FROM {tbl})
                            ) WHERE pg_get_serial_sequence('{tbl}', 'id') IS NOT NULL;
                        """))
                except Exception as ex:
                    print(f"[DB] Sequence sync notice for {tbl}: {ex}", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 0. Check for insecure default secrets and emit warnings if found
    settings.check_security_warnings()

    # 1. Create DB schema if needed and apply missing columns to existing DBs
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(ensure_schema_updates)

    # 2. Seed initial permissions, roles, superadmin, fuel stock
    try:
        async with AsyncSessionLocal() as session:
            await seed_initial_data(session)
        print(f"[AUTH] SuperAdmin user '{settings.INITIAL_ADMIN_LOGIN}' successfully ensured. Ready for login.", flush=True)
    except Exception as e:
        import traceback
        print(f"[ERROR] Failed to seed initial data: {e}", flush=True)
        traceback.print_exc()
        if str(getattr(settings, "APP_ENV", "")).strip().lower() in ("production", "prod"):
            raise RuntimeError(f"CRITICAL: Initial data seeding failed in production: {e}") from e

    # 2.1. Mandatory historical audit log sanitization (fail-closed)
    try:
        async with AsyncSessionLocal() as session:
            sanitized_count = await sanitize_historical_audit_logs(session)
            if sanitized_count > 0:
                print(f"[AUDIT] Sanitized {sanitized_count} historical audit records containing plaintext secrets.", flush=True)
    except Exception as e:
        import traceback
        print(f"[CRITICAL] Historical audit log sanitization failed: {e}", flush=True)
        traceback.print_exc()
        raise RuntimeError(
            f"CRITICAL SECURITY FAILURE: Historical audit log sanitization failed ({e}). "
            "Application startup aborted to prevent unredacted secret exposure."
        ) from e

    # 3. Ensure uploads and backups directories exist
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    os.makedirs(settings.BACKUP_DIR, exist_ok=True)

    # 4. Start background backup scheduler
    backup_scheduler_task = asyncio.create_task(run_backup_scheduler())
    guard_worker_task = asyncio.create_task(run_operational_guard_loop())
    yasno_worker_task = asyncio.create_task(run_yasno_checker_loop())

    yield

    # Shutdown: Graceful cancellation and await background tasks before disposing engine (MAIN-05)
    backup_scheduler_task.cancel()
    guard_worker_task.cancel()
    yasno_worker_task.cancel()
    await asyncio.gather(backup_scheduler_task, guard_worker_task, yasno_worker_task, return_exceptions=True)
    await engine.dispose()


app = FastAPI(
    title="Service Desk Генератора (SD-GEN016)",
    description="Система оперативного обліку фактичної експлуатації бензинового генератора",
    version="4.6.0",
    lifespan=lifespan
)

# 1. Restrict trusted hosts (prevents Host header attacks, rogue clone domains and unauthorized proxies)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=settings.effective_allowed_hosts,
)

# 2. Restrict CORS origins based on configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.effective_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Requested-With"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    # MAIN-09: Removed obsolete X-XSS-Protection header in favor of CSP
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data: blob:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    return response


# API routes
app.include_router(api_v1_router)


# Liveness check: confirms web process is alive
@app.get("/api/health/liveness", tags=["Health"])
async def liveness_check():
    return {"status": "alive"}


# MAIN-07: Readiness & Healthcheck with verified database connectivity test
@app.get("/api/health/readiness", tags=["Health"])
@app.get("/api/health", tags=["Health"])
async def health_check():
    db_status = "connected"
    is_healthy = True
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        db_status = "disconnected"
        is_healthy = False

    payload = {
        "status": "healthy" if is_healthy else "unhealthy",
        "facility_timezone": settings.FACILITY_TIMEZONE,
        "primary_domain": settings.PRIMARY_DOMAIN,
        "database": db_status
    }
    if not is_healthy:
        return JSONResponse(status_code=503, content=payload)
    return payload


# Frontend and PWA static assets handling
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

if FRONTEND_DIR.exists():
    # Mount frontend static directory if exists
    app.mount("/frontend", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")

    @app.get("/manifest.json")
    async def get_manifest():
        manifest_path = FRONTEND_DIR / "manifest.json"
        if manifest_path.exists():
            return FileResponse(manifest_path, media_type="application/manifest+json")
        return JSONResponse({"error": "Manifest not found"}, status_code=404)

    @app.get("/sw.js")
    async def get_service_worker():
        sw_path = FRONTEND_DIR / "sw.js"
        if sw_path.exists():
            return FileResponse(sw_path, media_type="application/javascript", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
        return JSONResponse({"error": "Service worker not found"}, status_code=404)

    @app.get("/robots.txt", include_in_schema=False)
    async def get_robots():
        return PlainTextResponse("User-agent: *\nDisallow: /api/\n")

    @app.get("/favicon.ico", include_in_schema=False)
    async def get_favicon():
        fav_path = FRONTEND_DIR / "favicon.ico"
        if fav_path.exists():
            return FileResponse(fav_path, media_type="image/x-icon")
        return JSONResponse({"error": "Favicon not found"}, status_code=404)

    # INF-07: Secure authorized uploads endpoint
    @app.get("/uploads/{file_path:path}")
    async def get_uploaded_media(file_path: str, request: Request):
        token = request.cookies.get("access_token")
        if not token:
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.split(" ", 1)[1]

        if not token:
            return JSONResponse({"error": "Неавторизований доступ до файлів"}, status_code=401)

        from backend.app.core.security import decode_access_token
        payload = decode_access_token(token)
        if not payload:
            return JSONResponse({"error": "Недійсний або прострочений токен"}, status_code=401)

        uploads_base = Path(settings.UPLOAD_DIR).resolve()
        target_file = (uploads_base / file_path).resolve()
        if not target_file.is_relative_to(uploads_base) or not target_file.is_file():
            return JSONResponse({"error": "Файл не знайдено"}, status_code=404)

        return FileResponse(
            target_file,
            headers={
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": "inline",
                "Cache-Control": "private, max-age=3600"
            }
        )

    @app.api_route("/", methods=["GET", "HEAD"])
    async def serve_index():
        index_path = FRONTEND_DIR / "index.html"
        if index_path.exists():
            content = index_path.read_text(encoding="utf-8")
            # Inject dynamic primary domain from .env configuration
            meta_tag = f'<meta name="app-primary-domain" content="{settings.PRIMARY_DOMAIN}">'
            if "</head>" in content and 'name="app-primary-domain"' not in content:
                content = content.replace("</head>", f"  {meta_tag}\n</head>", 1)
            return HTMLResponse(
                content=content,
                headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
            )
        return {"message": "Service Desk API is running. Frontend index.html not found."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=8000, reload=True)
