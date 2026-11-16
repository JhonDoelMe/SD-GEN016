import asyncio
import datetime
import re
from pathlib import Path
from typing import AsyncGenerator, Optional, Tuple
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession, AsyncEngine
from sqlalchemy.orm import DeclarativeBase
from backend.app.config import settings, Settings


def utc_now() -> datetime.datetime:
    """Return current UTC timestamp as naive datetime (matches DB DateTime columns)."""
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def _is_sqlite_url(database_url: str) -> bool:
    return "sqlite" in (database_url or "").lower()


def _ensure_sqlite_parent_dir(database_url: str) -> None:
    """Create parent directory for file-backed SQLite URLs if needed."""
    if not _is_sqlite_url(database_url) or ":memory:" in database_url:
        return
    if ":///" not in database_url:
        return
    raw_path = database_url.split(":///", 1)[1].split("?", 1)[0].strip()
    if raw_path:
        Path(raw_path).parent.mkdir(parents=True, exist_ok=True)


def build_async_engine(database_url: str) -> AsyncEngine:
    """Construct a configured SQLAlchemy AsyncEngine for SQLite or PostgreSQL."""
    is_sqlite = _is_sqlite_url(database_url)
    engine_kwargs = {
        "echo": (settings.APP_ENV == "development"),
        "future": True,
    }
    if is_sqlite:
        _ensure_sqlite_parent_dir(database_url)
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    else:
        # DB-01: Explicit PostgreSQL pool configuration and connection health check
        engine_kwargs.update({
            "pool_size": 10,
            "max_overflow": 20,
            "pool_timeout": 30,
            "pool_recycle": 1800,
            "pool_pre_ping": True,
        })

    new_engine = create_async_engine(database_url, **engine_kwargs)
    if is_sqlite:
        @event.listens_for(new_engine.sync_engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return new_engine


engine: AsyncEngine = build_async_engine(settings.DATABASE_URL)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


def get_engine() -> AsyncEngine:
    """Return the currently active SQLAlchemy AsyncEngine."""
    return engine


async def reinit_database_engine(new_database_url: Optional[str] = None) -> str:
    """
    Dispose the current AsyncEngine and bind AsyncSessionLocal to a new database URL.
    Used by Zero-.env setup/migration workflows without full interpreter restart.
    Returns active dialect label: 'sqlite' or 'postgresql'.
    """
    global engine
    if new_database_url is not None and new_database_url.strip():
        settings.DATABASE_URL = Settings.sanitize_database_url(new_database_url)

    old_engine = engine
    new_engine = build_async_engine(settings.DATABASE_URL)
    engine = new_engine
    AsyncSessionLocal.configure(bind=new_engine)
    import sys
    main_mod = sys.modules.get("backend.app.main")
    if main_mod is not None and hasattr(main_mod, "engine"):
        setattr(main_mod, "engine", new_engine)
    if old_engine is not None and old_engine is not new_engine:
        await old_engine.dispose()
    return "sqlite" if settings.is_sqlite else "postgresql"


def _scrub_dsn_credentials(text_val: str) -> str:
    """Redact user:password from any database URL in error messages."""
    return re.sub(r"://([^:@/\s]+):([^@/\s]+)@", "://\\1:***@", str(text_val or ""))


async def probe_database_connection(database_url: str, timeout_sec: float = 5.0) -> Tuple[bool, str]:
    """
    Verify connectivity to a candidate SQLite or PostgreSQL DATABASE_URL.
    Returns (ok, message) with any DSN credentials redacted.
    """
    sanitized = Settings.sanitize_database_url(database_url)
    test_eng: Optional[AsyncEngine] = None
    try:
        test_eng = build_async_engine(sanitized)
        async def _probe() -> None:
            async with test_eng.connect() as conn:
                await conn.execute(text("SELECT 1"))

        await asyncio.wait_for(_probe(), timeout=timeout_sec)
        dialect = "SQLite" if _is_sqlite_url(sanitized) else "PostgreSQL"
        return True, f"Підключення до {dialect} успішне"
    except Exception as exc:
        return False, _scrub_dsn_credentials(f"{type(exc).__name__}: {exc}")
    finally:
        if test_eng is not None:
            try:
                await test_eng.dispose()
            except Exception:
                pass


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    # DB-02 & DB-03: Single consistent session context with cancellation handling
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except asyncio.CancelledError:
            await session.rollback()
            raise
        except Exception:
            await session.rollback()
            raise
