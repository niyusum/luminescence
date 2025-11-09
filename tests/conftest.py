"""
Pytest configuration and shared fixtures.

Provides database, Redis, and mock fixtures for testing.
"""

import pytest
import asyncio
from typing import AsyncGenerator, Generator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from src.core.config.config import Config
from src.database.models.core.player import Player
from src.database.models.core.maiden import Maiden
from src.database.models.core.maiden_base import MaidenBase


# ============================================================================
# PYTEST CONFIGURATION
# ============================================================================

@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# ============================================================================
# DATABASE FIXTURES
# ============================================================================

@pytest.fixture(scope="function")
async def db_engine():
    """Create test database engine with NullPool."""
    Config.set_testing_mode(True)

    engine = create_async_engine(
        "postgresql+asyncpg://test:test@localhost:5432/riki_test",
        poolclass=NullPool,
        echo=False,
    )

    yield engine

    await engine.dispose()


@pytest.fixture(scope="function")
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create test database session."""
    async_session = async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session() as session:
        yield session
        await session.rollback()


# ============================================================================
# PLAYER FIXTURES
# ============================================================================

@pytest.fixture
async def test_player(db_session: AsyncSession) -> Player:
    """Create test player."""
    player = Player(
        discord_id=123456789,
        username="TestPlayer",
        level=5,
        experience=1000,
        rikis=10000,
        grace=50,
        energy=100,
        max_energy=100,
        stamina=50,
        max_stamina=50,
        hp=500,
        max_hp=500,
        stat_points_available=5,
        stat_points_spent={"energy": 0, "stamina": 0, "hp": 0},
    )

    db_session.add(player)
    await db_session.commit()
    await db_session.refresh(player)

    return player


@pytest.fixture
async def test_player_high_level(db_session: AsyncSession) -> Player:
    """Create high-level test player."""
    player = Player(
        discord_id=987654321,
        username="HighLevelPlayer",
        level=50,
        experience=500000,
        rikis=1000000,
        grace=500,
        energy=200,
        max_energy=200,
        stamina=100,
        max_stamina=100,
        hp=1000,
        max_hp=1000,
        stat_points_available=0,
        stat_points_spent={"energy": 10, "stamina": 10, "hp": 5},
        total_power=50000,
    )

    db_session.add(player)
    await db_session.commit()
    await db_session.refresh(player)

    return player


# ============================================================================
# MAIDEN FIXTURES
# ============================================================================

@pytest.fixture
async def test_maiden_base(db_session: AsyncSession) -> MaidenBase:
    """Create test maiden base."""
    maiden_base = MaidenBase(
        name="Test Maiden",
        element="infernal",
        base_tier=1,
        base_attack=100,
        base_defense=50,
        description="Test maiden for unit tests",
    )

    db_session.add(maiden_base)
    await db_session.commit()
    await db_session.refresh(maiden_base)

    return maiden_base


@pytest.fixture
async def test_maiden(db_session: AsyncSession, test_player: Player, test_maiden_base: MaidenBase) -> Maiden:
    """Create test maiden owned by test player."""
    maiden = Maiden(
        player_id=test_player.discord_id,
        maiden_base_id=test_maiden_base.id,
        tier=1,
        quantity=2,
        element="infernal",
        is_locked=False,
    )

    db_session.add(maiden)
    await db_session.commit()
    await db_session.refresh(maiden)

    return maiden


# ============================================================================
# MOCK FIXTURES
# ============================================================================

@pytest.fixture
def mock_config(monkeypatch):
    """Mock ConfigManager for testing."""
    test_config = {
        "fusion_costs": {"base": 1000, "multiplier": 2.5, "max_cost": 10000000},
        "fusion_rates": {"1": 70, "2": 65, "3": 60},
        "shard_system": {
            "shards_per_failure_min": 1,
            "shards_per_failure_max": 12,
            "shards_for_redemption": 100
        },
        "energy_system": {
            "regen_minutes": 5,
            "overcap_threshold": 0.9,
            "overcap_bonus": 0.10
        },
        "stamina_system": {"regen_minutes": 10},
        "prayer_system": {"regen_minutes": 5, "regen_interval_seconds": 300},
    }

    from src.core.config.config_manager import ConfigManager

    def mock_get(key, default=None):
        keys = key.split(".")
        value = test_config
        for k in keys:
            value = value.get(k, {})
        return value if value != {} else default

    monkeypatch.setattr(ConfigManager, "get", staticmethod(mock_get))
    return test_config


# ============================================================================
# UTILITY FIXTURES
# ============================================================================

@pytest.fixture
def freeze_time(monkeypatch):
    """Freeze time for testing time-dependent functions."""
    from datetime import datetime

    frozen_time = datetime(2025, 1, 1, 12, 0, 0)

    class FrozenDatetime:
        @classmethod
        def utcnow(cls):
            return frozen_time

    monkeypatch.setattr("datetime.datetime", FrozenDatetime)

    return frozen_time
