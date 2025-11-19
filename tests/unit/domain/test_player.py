"""
Unit Tests for Player Domain Model (LES 2025)
==============================================

Purpose
-------
Test the business logic in the Player domain model without external dependencies.

Test Coverage
-------------
- Player identity and initialization
- Experience gain and level-up logic
- Currency operations (add/subtract)
- Leader maiden selection
- Domain event emission
- Validation and error handling

Testing Strategy
----------------
- Unit tests (fast, no database)
- Mocked dependencies
- AAA pattern (Arrange, Act, Assert)
- Test one behavior per test
"""

import pytest

from src.domain.models import (
    Player,
    PlayerCurrencies,
    PlayerIdentity,
    PlayerProgression,
)
from src.domain.models.base import DomainValidationError


# ============================================================================
# PLAYER IDENTITY TESTS
# ============================================================================


@pytest.mark.unit
@pytest.mark.domain
class TestPlayerIdentity:
    """Test PlayerIdentity value object."""

    def test_create_valid_identity(self):
        """Test creating valid player identity."""
        # Arrange & Act
        identity = PlayerIdentity(
            discord_id=123456789,
            username="TestUser",
            discriminator="1234",
        )

        # Assert
        assert identity.discord_id == 123456789
        assert identity.username == "TestUser"
        assert identity.discriminator == "1234"

    def test_identity_requires_positive_discord_id(self):
        """Test that discord_id must be positive."""
        # Arrange & Act & Assert
        with pytest.raises(DomainValidationError) as exc_info:
            PlayerIdentity(
                discord_id=0,  # Invalid: not positive
                username="TestUser",
            )

        assert "discord_id must be positive" in str(exc_info.value)

    def test_identity_requires_non_empty_username(self):
        """Test that username cannot be empty."""
        # Arrange & Act & Assert
        with pytest.raises(DomainValidationError) as exc_info:
            PlayerIdentity(
                discord_id=123456789,
                username="",  # Invalid: empty
            )

        assert "username cannot be empty" in str(exc_info.value)

    def test_identity_is_immutable(self):
        """Test that PlayerIdentity is immutable (frozen dataclass)."""
        # Arrange
        identity = PlayerIdentity(
            discord_id=123456789,
            username="TestUser",
        )

        # Act & Assert
        with pytest.raises(Exception):  # FrozenInstanceError
            identity.username = "NewName"  # type: ignore[misc]


# ============================================================================
# PLAYER CURRENCIES TESTS
# ============================================================================


@pytest.mark.unit
@pytest.mark.domain
class TestPlayerCurrencies:
    """Test PlayerCurrencies value object."""

    def test_add_lumens(self):
        """Test adding lumens creates new instance."""
        # Arrange
        currencies = PlayerCurrencies(lumens=100, gems=50)

        # Act
        new_currencies = currencies.add_lumens(250)

        # Assert
        assert new_currencies.lumens == 350
        assert new_currencies.gems == 50  # Unchanged
        assert currencies.lumens == 100  # Original unchanged (immutable)

    def test_subtract_lumens(self):
        """Test subtracting lumens creates new instance."""
        # Arrange
        currencies = PlayerCurrencies(lumens=500, gems=50)

        # Act
        new_currencies = currencies.subtract_lumens(200)

        # Assert
        assert new_currencies.lumens == 300
        assert new_currencies.gems == 50

    def test_subtract_lumens_insufficient_funds(self):
        """Test that subtracting more lumens than available raises error."""
        # Arrange
        currencies = PlayerCurrencies(lumens=100, gems=50)

        # Act & Assert
        with pytest.raises(DomainValidationError) as exc_info:
            currencies.subtract_lumens(200)

        assert "Insufficient lumens" in str(exc_info.value)

    def test_add_gems(self):
        """Test adding gems creates new instance."""
        # Arrange
        currencies = PlayerCurrencies(lumens=100, gems=50)

        # Act
        new_currencies = currencies.add_gems(25)

        # Assert
        assert new_currencies.gems == 75
        assert new_currencies.lumens == 100  # Unchanged


# ============================================================================
# PLAYER AGGREGATE ROOT TESTS
# ============================================================================


@pytest.mark.unit
@pytest.mark.domain
class TestPlayer:
    """Test Player aggregate root business logic."""

    @pytest.fixture
    def sample_player(self) -> Player:
        """Create a sample player for testing."""
        return Player(
            identity=PlayerIdentity(
                discord_id=123456789,
                username="TestUser",
            ),
            progression=PlayerProgression(
                level=1,
                experience=0,
                experience_to_next_level=100,
            ),
            currencies=PlayerCurrencies(lumens=1000, gems=50),
        )

    # ========================================================================
    # INITIALIZATION TESTS
    # ========================================================================

    def test_player_initialization(self, sample_player):
        """Test player initializes with correct values."""
        # Assert
        assert sample_player.id == 123456789
        assert sample_player.identity.username == "TestUser"
        assert sample_player.progression.level == 1
        assert sample_player.currencies.lumens == 1000

    # ========================================================================
    # EXPERIENCE & LEVEL-UP TESTS
    # ========================================================================

    def test_add_experience_no_level_up(self, sample_player):
        """Test adding experience without reaching level-up threshold."""
        # Arrange
        initial_level = sample_player.progression.level

        # Act
        sample_player.add_experience(50)

        # Assert
        assert sample_player.progression.experience == 50
        assert sample_player.progression.level == initial_level
        assert len(sample_player.get_pending_events()) == 1  # experience_gained event

    def test_add_experience_with_level_up(self, sample_player):
        """Test that adding experience triggers level-up when threshold reached."""
        # Arrange
        initial_level = sample_player.progression.level

        # Act
        sample_player.add_experience(100)  # Exactly enough to level up

        # Assert
        assert sample_player.progression.level == initial_level + 1
        assert sample_player.progression.experience == 0  # Reset after level-up
        # Should have experience_gained + leveled_up events
        events = sample_player.get_pending_events()
        assert len(events) == 2
        assert any(e.event_name == "player.leveled_up" for e in events)

    def test_add_experience_multiple_level_ups(self, sample_player):
        """Test that adding large experience can trigger multiple level-ups."""
        # Arrange
        initial_level = sample_player.progression.level

        # Act
        # Add enough XP for multiple levels (need to calculate based on formula)
        sample_player.add_experience(500)

        # Assert
        assert sample_player.progression.level > initial_level + 1
        events = sample_player.get_pending_events()
        level_up_events = [e for e in events if e.event_name == "player.leveled_up"]
        assert len(level_up_events) > 1

    def test_add_experience_emits_domain_event(self, sample_player):
        """Test that adding experience emits appropriate domain events."""
        # Act
        sample_player.add_experience(50)

        # Assert
        events = sample_player.get_pending_events()
        assert len(events) > 0
        xp_event = next(
            (e for e in events if e.event_name == "player.experience_gained"), None
        )
        assert xp_event is not None
        assert xp_event.payload["amount"] == 50
        assert xp_event.payload["player_id"] == sample_player.id

    # ========================================================================
    # CURRENCY TESTS
    # ========================================================================

    def test_add_currency_lumens(self, sample_player):
        """Test adding lumens updates player currencies."""
        # Arrange
        initial_lumens = sample_player.currencies.lumens

        # Act
        sample_player.add_currency("lumens", 500)

        # Assert
        assert sample_player.currencies.lumens == initial_lumens + 500

    def test_add_currency_gems(self, sample_player):
        """Test adding gems updates player currencies."""
        # Arrange
        initial_gems = sample_player.currencies.gems

        # Act
        sample_player.add_currency("gems", 25)

        # Assert
        assert sample_player.currencies.gems == initial_gems + 25

    def test_add_currency_invalid_type(self, sample_player):
        """Test that invalid currency type raises error."""
        # Act & Assert
        with pytest.raises(DomainValidationError) as exc_info:
            sample_player.add_currency("invalid_currency", 100)

        assert "Invalid currency type" in str(exc_info.value)

    def test_subtract_currency_lumens(self, sample_player):
        """Test subtracting lumens updates player currencies."""
        # Arrange
        initial_lumens = sample_player.currencies.lumens

        # Act
        sample_player.subtract_currency("lumens", 200)

        # Assert
        assert sample_player.currencies.lumens == initial_lumens - 200

    def test_subtract_currency_insufficient_funds(self, sample_player):
        """Test that subtracting more currency than available raises error."""
        # Act & Assert
        with pytest.raises(DomainValidationError) as exc_info:
            sample_player.subtract_currency("lumens", 99999)

        assert "Insufficient lumens" in str(exc_info.value)

    # ========================================================================
    # LEADER MAIDEN TESTS
    # ========================================================================

    def test_set_leader_maiden(self, sample_player):
        """Test setting leader maiden."""
        # Act
        sample_player.set_leader_maiden(42)

        # Assert
        assert sample_player.leader_maiden_id == 42

    def test_set_leader_maiden_emits_event(self, sample_player):
        """Test that setting leader maiden emits domain event."""
        # Act
        sample_player.set_leader_maiden(42)

        # Assert
        events = sample_player.get_pending_events()
        leader_event = next(
            (e for e in events if e.event_name == "player.leader_maiden_changed"),
            None,
        )
        assert leader_event is not None
        assert leader_event.payload["new_leader_id"] == 42

    # ========================================================================
    # DOMAIN EVENT TESTS
    # ========================================================================

    def test_domain_events_are_cleared(self, sample_player):
        """Test that clearing domain events removes them."""
        # Arrange
        sample_player.add_experience(50)
        assert len(sample_player.get_pending_events()) > 0

        # Act
        events = sample_player.clear_domain_events()

        # Assert
        assert len(events) > 0
        assert len(sample_player.get_pending_events()) == 0
