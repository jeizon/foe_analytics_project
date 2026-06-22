"""Async SQLAlchemy database manager for PostgreSQL."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from database.models import Base

DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://foe_analytics:foe_analytics_dev@localhost:5432/foe_analytics"
)


class DatabaseManager:
    """Owns the async engine and session factory."""

    def __init__(self, database_url: str | None = None, echo: bool = False) -> None:
        self.database_url = database_url or os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
        self.engine: AsyncEngine = create_async_engine(
            self.database_url,
            echo=echo,
            pool_pre_ping=True,
        )
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def create_schema(self) -> None:
        """Create database tables for local development and Phase 0 bootstrapping."""

        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Provide a transactional async session."""

        async with self.session_factory() as session:
            async with session.begin():
                yield session

    async def dispose(self) -> None:
        """Close all database connections."""

        await self.engine.dispose()

