import asyncio
import datetime
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from backend.app.config import settings


def utc_now() -> datetime.datetime:
    """Return current UTC timestamp as naive datetime (matches DB DateTime columns)."""
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

engine_kwargs = {
    "echo": (settings.APP_ENV == "development"),
    "future": True,
}

if settings.is_sqlite:
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

engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


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
