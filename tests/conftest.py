"""
Shared pytest fixtures for the PersonSearch test suite.
"""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Provide an isolated database session for testing using NullPool
    so connections are bound to the current test event loop.
    Any database changes made during the test are rolled back.
    """
    test_engine = create_async_engine(
        settings.database_url,
        poolclass=NullPool,
        echo=False,
    )
    test_session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )
    async with test_session_factory() as session:
        yield session
        await session.rollback()
    await test_engine.dispose()
