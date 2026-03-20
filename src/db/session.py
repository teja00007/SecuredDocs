"""Async database engine and session factory."""

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


def get_async_engine(database_url: str, **kwargs):
    """Create an async SQLAlchemy engine.

    Uses NullPool for SQLite (no connection pooling).
    Uses configurable pool settings for PostgreSQL.
    """
    connect_args = {}
    pool_kwargs = {}

    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        pool_kwargs["poolclass"] = NullPool
    else:
        pool_kwargs.update({
            "pool_size": kwargs.get("pool_size", 5),
            "max_overflow": kwargs.get("max_overflow", 10),
            "pool_timeout": kwargs.get("pool_timeout", 30),
            "pool_recycle": kwargs.get("pool_recycle", 1800),
        })

    return create_async_engine(
        database_url,
        connect_args=connect_args,
        echo=kwargs.get("echo", False),
        **pool_kwargs,
    )


def get_session_factory(engine) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory bound to the given engine."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_async_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session, auto-rollback on exception."""
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def check_db_health(session: AsyncSession) -> bool:
    """Verify database connection is alive."""
    try:
        await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
