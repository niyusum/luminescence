"""
Integration Tests for DatabaseService (LES 2025)
=================================================

Purpose
-------
Test database operations with real PostgreSQL using testcontainers.
Verifies connection pooling, transaction management, and schema creation.

Test Coverage
-------------
- Database connection and session management
- Transaction commit and rollback
- Concurrent access and connection pooling
- Schema creation and migrations
- Error handling and recovery

Testing Strategy
----------------
- Integration tests (uses testcontainers for real PostgreSQL)
- Tests actual database behavior, not mocks
- Each test gets clean database session (automatic rollback)
- Tests run in isolated transactions
"""

import pytest
from sqlalchemy import text

from src.core.database.base import Base
from src.database.models.core.player import PlayerCore


# ============================================================================
# DATABASE CONNECTION TESTS
# ============================================================================


@pytest.mark.integration
@pytest.mark.database
class TestDatabaseConnection:
    """Test database connection and basic operations."""

    async def test_database_connection(self, db_session):
        """Test that we can connect to the database."""
        # Act
        result = await db_session.execute(text("SELECT 1 as value"))
        row = result.fetchone()

        # Assert
        assert row is not None
        assert row.value == 1

    async def test_database_schema_created(self, database_engine):
        """Test that database schema tables are created."""
        # Arrange
        async with database_engine.connect() as conn:
            # Act - Query table existence
            result = await conn.execute(
                text(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                    """
                )
            )
            tables = [row.table_name for row in result.fetchall()]

        # Assert - Check that core tables exist
        assert "player_core" in tables
        assert "maidens" in tables
        assert "maiden_bases" in tables


# ============================================================================
# TRANSACTION TESTS
# ============================================================================


@pytest.mark.integration
@pytest.mark.database
class TestDatabaseTransactions:
    """Test transaction management and isolation."""

    async def test_transaction_commit(self, db_session):
        """Test that changes are committed within transaction."""
        # Arrange
        player = PlayerCore(
            discord_id=123456789,
            username="TestUser",
            discriminator="1234",
        )

        # Act
        db_session.add(player)
        await db_session.flush()

        # Assert - Player should be retrievable in same session
        result = await db_session.execute(
            text("SELECT username FROM player_core WHERE discord_id = :id"),
            {"id": 123456789},
        )
        row = result.fetchone()
        assert row is not None
        assert row.username == "TestUser"

    async def test_transaction_rollback_automatic(self, db_session):
        """Test that transaction rolls back automatically after test."""
        # Arrange
        player = PlayerCore(
            discord_id=987654321,
            username="RollbackUser",
            discriminator="5678",
        )

        # Act
        db_session.add(player)
        await db_session.flush()

        # Assert - Player exists in current transaction
        result = await db_session.execute(
            text("SELECT username FROM player_core WHERE discord_id = :id"),
            {"id": 987654321},
        )
        assert result.fetchone() is not None

        # Note: After this test completes, the transaction will rollback
        # The player will NOT exist in subsequent tests (clean slate)


# ============================================================================
# MODEL PERSISTENCE TESTS
# ============================================================================


@pytest.mark.integration
@pytest.mark.database
class TestModelPersistence:
    """Test persisting and retrieving database models."""

    async def test_create_player(self, db_session):
        """Test creating a player in the database."""
        # Arrange
        player = PlayerCore(
            discord_id=111222333,
            username="PersistenceTest",
            discriminator="0001",
        )

        # Act
        db_session.add(player)
        await db_session.flush()
        await db_session.refresh(player)

        # Assert
        assert player.discord_id == 111222333
        assert player.username == "PersistenceTest"
        assert player.created_at is not None

    async def test_query_player_by_discord_id(self, db_session):
        """Test querying player by discord_id."""
        # Arrange
        player = PlayerCore(
            discord_id=444555666,
            username="QueryTest",
        )
        db_session.add(player)
        await db_session.flush()

        # Act
        from sqlalchemy import select

        stmt = select(PlayerCore).where(PlayerCore.discord_id == 444555666)
        result = await db_session.execute(stmt)
        found_player = result.scalar_one_or_none()

        # Assert
        assert found_player is not None
        assert found_player.username == "QueryTest"

    async def test_update_player(self, db_session):
        """Test updating player fields."""
        # Arrange
        player = PlayerCore(
            discord_id=777888999,
            username="UpdateTest",
        )
        db_session.add(player)
        await db_session.flush()

        # Act
        player.username = "UpdatedUsername"
        await db_session.flush()
        await db_session.refresh(player)

        # Assert
        assert player.username == "UpdatedUsername"


# ============================================================================
# CONCURRENT ACCESS TESTS
# ============================================================================


@pytest.mark.integration
@pytest.mark.database
@pytest.mark.slow
class TestConcurrentAccess:
    """Test concurrent database access and connection pooling."""

    async def test_multiple_sessions(self, database_engine):
        """Test that multiple sessions can be created from the engine."""
        # Arrange
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        async_session_maker = async_sessionmaker(
            database_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        # Act - Create multiple sessions
        async with async_session_maker() as session1:
            async with async_session_maker() as session2:
                # Both sessions should be able to query
                result1 = await session1.execute(text("SELECT 1"))
                result2 = await session2.execute(text("SELECT 2"))

                # Assert
                assert result1.scalar() == 1
                assert result2.scalar() == 2


# ============================================================================
# ERROR HANDLING TESTS
# ============================================================================


@pytest.mark.integration
@pytest.mark.database
class TestDatabaseErrorHandling:
    """Test database error handling."""

    async def test_unique_constraint_violation(self, db_session):
        """Test that unique constraint violations are properly raised."""
        # Arrange
        discord_id = 123456789
        player1 = PlayerCore(
            discord_id=discord_id,
            username="Player1",
        )
        player2 = PlayerCore(
            discord_id=discord_id,  # Same discord_id (unique constraint)
            username="Player2",
        )

        # Act & Assert
        db_session.add(player1)
        await db_session.flush()

        db_session.add(player2)
        with pytest.raises(Exception):  # IntegrityError
            await db_session.flush()

    async def test_invalid_sql_query(self, db_session):
        """Test that invalid SQL queries raise appropriate errors."""
        # Act & Assert
        with pytest.raises(Exception):  # ProgrammingError or similar
            await db_session.execute(text("SELECT * FROM nonexistent_table"))
