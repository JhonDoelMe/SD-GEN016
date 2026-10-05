import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.app.config import settings
from backend.app.database import engine, Base, AsyncSessionLocal
from backend.app.models import *  # noqa: F401, F403 Ensure all models loaded
from backend.app.services.init_service import seed_initial_data
from backend.app.api.v1 import api_v1_router


from sqlalchemy import inspect, text


def ensure_schema_updates(sync_conn):
    inspector = inspect(sync_conn)
    tables = inspector.get_table_names()

    # 1. generator_runs duration_seconds
    if "generator_runs" in tables:
        columns = [c["name"] for c in inspector.get_columns("generator_runs")]
        if "duration_seconds" not in columns:
            sync_conn.execute(text("ALTER TABLE generator_runs ADD COLUMN duration_seconds INTEGER"))

    # 2. facilities default record
    if "facilities" in tables:
        res = sync_conn.execute(text("SELECT COUNT(*) FROM facilities")).scalar()
        if res == 0:
            sync_conn.execute(text(
                "INSERT INTO facilities (id, name, address, description, timezone, created_at, updated_at) "
                "VALUES (1, 'Основний об''єкт', 'Головна локація', 'Базовий об''єкт генератора', 'Europe/Kyiv', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))

    # 3. Add facility_id to related tables
    for table_name in ["generators", "fuel_stocks", "fuel_receipts", "fuel_transfers", "users"]:
        if table_name in tables:
            cols = [c["name"] for c in inspector.get_columns(table_name)]
            if "facility_id" not in cols:
                sync_conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN facility_id INTEGER REFERENCES facilities(id)"))
            # Set default facility_id to 1 if null
            sync_conn.execute(text(f"UPDATE {table_name} SET facility_id = 1 WHERE facility_id IS NULL"))

    # 4. Fix maintenance schedule anomaly: interval=300, next_due=535 -> next_due=300, last_performed=0
    if "maintenance_schedules" in tables:
        sync_conn.execute(text(
            "UPDATE maintenance_schedules SET last_performed_hours = 0.0, next_due_hours = interval_hours "
            "WHERE (last_performed_hours = 235.0 AND next_due_hours = 535.0) "
            "OR (last_performed_hours = 235.0 AND next_due_hours > 300.0)"
        ))

    # 5. Synchronize sequences for PostgreSQL to avoid duplicate key errors on auto-incrementing IDs
    if sync_conn.dialect.name == "postgresql":
        serial_tables = [
            "facilities", "generators", "fuel_stocks", "fuel_receipts",
            "fuel_transfers", "users", "roles", "permissions",
            "maintenance_schedules", "maintenance_records",
            "generator_runs", "generator_faults", "audit_logs"
        ]
        for tbl in serial_tables:
            if tbl in tables:
                try:
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
        print(f"[ERROR] Failed to seed initial data: {e}")
        traceback.print_exc()

    # 3. Ensure uploads directory exists
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)

    yield

    # Shutdown
    await engine.dispose()


app = FastAPI(
    title="Service Desk Бензинового Генератора (SD-GEN016)",
    description="Система оперативного обліку фактичної експлуатації бензинового генератора",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(api_v1_router)

# Healthcheck
@app.get("/api/health", tags=["Health"])
async def health_check():
    return {
        "status": "healthy",
        "app_env": settings.APP_ENV,
        "facility_timezone": settings.FACILITY_TIMEZONE,
        "database": "connected"
    }


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
            return FileResponse(sw_path, media_type="application/javascript")
        return JSONResponse({"error": "Service worker not found"}, status_code=404)

    @app.get("/")
    async def serve_index():
        index_path = FRONTEND_DIR / "index.html"
        if index_path.exists():
            return FileResponse(
                index_path,
                headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
            )
        return {"message": "Service Desk API is running. Frontend index.html not found."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=8000, reload=True)
