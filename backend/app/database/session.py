"""Async SQLAlchemy engine and session factory."""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


# Pool-sizing args only apply to server-style databases (postgres). SQLite and
# in-memory URLs reject them, so gate them behind the URL scheme.
_engine_kwargs = dict(echo=False, future=True, pool_pre_ping=True)
if "sqlite" not in settings.database_url:
    _engine_kwargs.update(
        pool_size=10,
        max_overflow=20,
        pool_timeout=15,  # fail fast instead of hanging (was ~65s when pool exhausted)
        pool_recycle=1800,  # recycle connections every 30 min
    )

engine = create_async_engine(settings.database_url, **_engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async database session."""
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    """Create tables from metadata (dev convenience; use Alembic in prod)."""
    # Import models so they register on Base.metadata
    from app.models import (
        approval,
        conversation,
        document,
        event,
        memory,
        message,
        observability,
        task,
        user,
    )  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
