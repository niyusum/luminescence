"""
Pytest Configuration and Fixtures for Lumen RPG Tests (LES 2025)
=================================================================

Purpose
-------
Centralized test fixtures and configuration for the Lumen RPG test suite.
Provides reusable fixtures for database, services, domain models, and mocks.

Responsibilities
----------------
- Testcontainers setup for PostgreSQL and Redis
- Database session management for integration tests
- Service container and dependency injection mocks
- Domain model factories for test data
- Discord.py mocks for cog testing

Non-Responsibilities
--------------------
- Test implementation (delegated to test files)
- Business logic (delegated to domain models)
- Production configuration (test-specific only)

LES 2025 Compliance
-------------------
- Async support via pytest-asyncio
- Testcontainers for real infrastructure in integration tests
- Dependency injection for testability
- Separation of unit vs integration fixtures
- Factory pattern for test data generation

Architecture Notes
------------------
- Unit tests use mocks (fast, isolated)
- Integration tests use testcontainers (real database/redis)
- Fixtures follow scope hierarchy: session > module > function
- Database fixtures provide clean slate per test
"""

from __future__ import annotations

import asyncio
import os
from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from src.core.database.base import Base
from src.core.logging.logger import get_logger

logger = get_logger(__name__)

# ============================================================================
# PYTEST CONFIGURATION
# ============================================================================


def pytest_configure(config):
    """Configure pytest environment."""
    # Set test environment flag
    os.environ["LUMEN_ENV"] = "test"
    os.environ["LUMEN_LOG_LEVEL"] = "DEBUG"


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """
    Create event loop for async tests.

    Scope: session (one event loop for all tests)
    """
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ============================================================================
# TESTCONTAINERS FIXTURES (Integration Tests)
# ============================================================================


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    """
    Start PostgreSQL testcontainer for integration tests.

    Scope: session (container persists across all tests)
    Uses: Integration tests that need real database
    """
    logger.info("Starting PostgreSQL testcontainer...")
    container = PostgresContainer(
        image="postgres:17-alpine",
        driver="asyncpg",
    )
    container.start()

    logger.info(
        "PostgreSQL testcontainer started: %s",
        container.get_connection_url(),
    )

    yield container

    logger.info("Stopping PostgreSQL testcontainer...")
    container.stop()


@pytest.fixture(scope="session")
def redis_container() -> Generator[RedisContainer, None, None]:
    """
    Start Redis testcontainer for integration tests.

    Scope: session (container persists across all tests)
    Uses: Integration tests that need real Redis
    """
    logger.info("Starting Redis testcontainer...")
    container = RedisContainer(image="redis:7-alpine")
    container.start()

    logger.info(
        "Redis testcontainer started: %s:%s",
        container.get_container_host_ip(),
        container.get_exposed_port(6379),
    )

    yield container

    logger.info("Stopping Redis testcontainer...")
    container.stop()


# ============================================================================
# DATABASE FIXTURES (Integration Tests)
# ============================================================================


@pytest_asyncio.fixture(scope="session")
async def database_engine(
    postgres_container: PostgresContainer,
) -> AsyncGenerator[AsyncEngine, None]:
    """
    Create async database engine connected to testcontainer.

    Scope: session (one engine for all tests)
    Uses: Integration tests that need database access
    """
    # Get connection URL from container (replace psycopg2 driver with asyncpg)
    connection_url = postgres_container.get_connection_url().replace(
        "psycopg2", "asyncpg"
    )

    logger.info("Creating database engine: %s", connection_url)

    engine = create_async_engine(
        connection_url,
        echo=False,  # Set to True for SQL query logging
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )

    # Create all tables
    async with engine.begin() as conn:
        logger.info("Creating database schema...")
        await conn.run_sync(Base.metadata.create_all)
        logger.info("Database schema created")

    yield engine

    # Cleanup
    logger.info("Disposing database engine...")
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(
    database_engine: AsyncEngine,
) -> AsyncGenerator[AsyncSession, None]:
    """
    Create clean database session for each test.

    Scope: function (new session per test, clean slate)
    Uses: Integration tests that need to write to database

    Features:
    - Automatic rollback after each test (clean slate)
    - Nested transactions for isolation
    - Automatic cleanup
    """
    # Create session factory
    async_session_maker = async_sessionmaker(
        database_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session_maker() as session:
        # Begin nested transaction (savepoint)
        async with session.begin():
            yield session
            # Automatic rollback happens here (clean slate for next test)


# ============================================================================
# MOCK FIXTURES (Unit Tests)
# ============================================================================


@pytest.fixture
def mock_database_service(mocker):
    """
    Mock DatabaseService for unit tests.

    Scope: function
    Uses: Unit tests that need to mock database access
    """
    mock_service = mocker.MagicMock()
    mock_service.get_transaction = mocker.AsyncMock()
    return mock_service


@pytest.fixture
def mock_event_bus(mocker):
    """
    Mock EventBus for unit tests.

    Scope: function
    Uses: Unit tests that need to mock event publishing
    """
    mock_bus = mocker.MagicMock()
    mock_bus.publish = mocker.AsyncMock()
    mock_bus.subscribe = mocker.MagicMock()
    return mock_bus


@pytest.fixture
def mock_config_manager(mocker):
    """
    Mock ConfigManager for unit tests.

    Scope: function
    Uses: Unit tests that need to mock configuration
    """
    mock_config = mocker.MagicMock()
    mock_config.get = mocker.MagicMock(return_value="test_value")
    mock_config.get_int = mocker.MagicMock(return_value=42)
    mock_config.get_bool = mocker.MagicMock(return_value=True)
    return mock_config


@pytest.fixture
def mock_service_container(
    mocker,
    mock_database_service,
    mock_event_bus,
    mock_config_manager,
):
    """
    Mock ServiceContainer with common services.

    Scope: function
    Uses: Unit tests that need service container
    """
    mock_container = mocker.MagicMock()
    mock_container.database_service = mock_database_service
    mock_container.event_bus = mock_event_bus
    mock_container.config_manager = mock_config_manager
    return mock_container


# ============================================================================
# DISCORD.PY MOCK FIXTURES (Cog Tests)
# ============================================================================


@pytest.fixture
def mock_bot(mocker):
    """
    Mock Discord bot for cog testing.

    Scope: function
    Uses: Cog tests that need bot instance
    """
    mock_bot = mocker.MagicMock()
    mock_bot.user = mocker.MagicMock()
    mock_bot.user.id = 123456789
    mock_bot.user.name = "TestBot"
    return mock_bot


@pytest.fixture
def mock_context(mocker, mock_bot):
    """
    Mock Discord command context for cog testing.

    Scope: function
    Uses: Cog tests that need command context
    """
    mock_ctx = mocker.MagicMock()
    mock_ctx.bot = mock_bot
    mock_ctx.author = mocker.MagicMock()
    mock_ctx.author.id = 987654321
    mock_ctx.author.name = "TestUser"
    mock_ctx.guild = mocker.MagicMock()
    mock_ctx.guild.id = 111222333
    mock_ctx.channel = mocker.MagicMock()
    mock_ctx.send = mocker.AsyncMock()
    mock_ctx.typing = mocker.AsyncMock()
    return mock_ctx


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================


def assert_domain_event_emitted(domain_model, event_name: str) -> bool:
    """
    Assert that a domain model emitted a specific event.

    Usage:
        player.add_experience(100)
        assert assert_domain_event_emitted(player, "player.leveled_up")
    """
    events = domain_model.get_pending_events()
    return any(event.event_name == event_name for event in events)


def get_domain_event_payload(domain_model, event_name: str) -> dict | None:
    """
    Get the payload of a specific domain event.

    Usage:
        player.add_experience(100)
        payload = get_domain_event_payload(player, "player.leveled_up")
        assert payload["new_level"] == 2
    """
    events = domain_model.get_pending_events()
    for event in events:
        if event.event_name == event_name:
            return event.payload
    return None
