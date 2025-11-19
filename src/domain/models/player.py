"""
Player Domain Model for Lumen RPG (LES 2025).

Purpose
-------
Rich domain model representing a player with business logic for character
progression, maiden management, and game state transitions.

This is separate from the database model (PlayerCore, etc.) which are anemic
data schemas. Services convert between database models and domain models.

Responsibilities
----------------
- Enforce business rules for player progression
- Manage maiden collection and leader selection
- Handle experience gain and level-up logic
- Validate state transitions
- Emit domain events for important changes

Non-Responsibilities
--------------------
- Persistence (handled by repositories)
- Database transactions (handled by services/repositories)
- UI presentation (handled by cogs)

LUMEN LAW / LES 2025 Compliance
-------------------------------
- Business logic belongs in domain models (P1.2, P1.3)
- Services orchestrate domain models, don't manipulate data directly
- Domain events communicate state changes
- Self-validating with explicit invariants

Usage Example
-------------
>>> # Create from database model
>>> player = Player.from_db(player_core_row, progression_row, currencies_row)
>>>
>>> # Business logic in domain model
>>> player.add_experience(500)  # Handles level-up automatically
>>> player.add_currency("lumens", 1000)
>>> player.set_leader_maiden(maiden_id=42)
>>>
>>> # Domain events emitted automatically
>>> events = player.get_pending_events()
>>> for event in events:
...     await event_bus.publish(event.event_name, event.payload)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from src.domain.models.base import AggregateRoot, DomainEvent, DomainValidationError, validate_positive

if TYPE_CHECKING:
    from src.database.models.core.player.player_core import PlayerCore as PlayerCoreDB
    from src.database.models.core.player.player_progression import PlayerProgression as PlayerProgressionDB
    from src.database.models.core.player.player_currencies import PlayerCurrencies as PlayerCurrenciesDB


# ============================================================================
# VALUE OBJECTS
# ============================================================================


@dataclass(frozen=True)
class PlayerIdentity:
    """
    Immutable value object representing player identity.

    Attributes
    ----------
    discord_id : int
        Discord user ID (primary key)
    username : str
        Discord username
    discriminator : Optional[str]
        Discord discriminator (legacy, optional)
    """

    discord_id: int
    username: str
    discriminator: Optional[str] = None

    def __post_init__(self) -> None:
        """Validate identity on creation."""
        validate_positive(self.discord_id, "discord_id")
        if not self.username or not self.username.strip():
            raise DomainValidationError("username cannot be empty", field="username")


@dataclass(frozen=True)
class PlayerProgression:
    """
    Immutable value object representing player progression state.

    Attributes
    ----------
    level : int
        Current player level
    experience : int
        Current experience points
    experience_to_next_level : int
        Experience needed for next level
    """

    level: int
    experience: int
    experience_to_next_level: int

    def __post_init__(self) -> None:
        """Validate progression on creation."""
        validate_positive(self.level, "level")
        if self.experience < 0:
            raise DomainValidationError("experience cannot be negative", field="experience")
        validate_positive(self.experience_to_next_level, "experience_to_next_level")


@dataclass(frozen=True)
class PlayerCurrencies:
    """
    Immutable value object representing player currencies.

    Attributes
    ----------
    lumens : int
        Primary currency
    gems : int
        Premium currency
    """

    lumens: int
    gems: int

    def __post_init__(self) -> None:
        """Validate currencies on creation."""
        if self.lumens < 0:
            raise DomainValidationError("lumens cannot be negative", field="lumens")
        if self.gems < 0:
            raise DomainValidationError("gems cannot be negative", field="gems")

    def add_lumens(self, amount: int) -> PlayerCurrencies:
        """
        Return new PlayerCurrencies with lumens added.

        Parameters
        ----------
        amount : int
            Amount to add (must be positive)

        Returns
        -------
        PlayerCurrencies
            New immutable instance with updated lumens
        """
        validate_positive(amount, "amount")
        return PlayerCurrencies(lumens=self.lumens + amount, gems=self.gems)

    def subtract_lumens(self, amount: int) -> PlayerCurrencies:
        """
        Return new PlayerCurrencies with lumens subtracted.

        Parameters
        ----------
        amount : int
            Amount to subtract (must be positive)

        Returns
        -------
        PlayerCurrencies
            New immutable instance with updated lumens

        Raises
        ------
        DomainValidationError
            If insufficient lumens
        """
        validate_positive(amount, "amount")
        if self.lumens < amount:
            raise DomainValidationError(
                f"Insufficient lumens: have {self.lumens}, need {amount}",
                field="lumens",
            )
        return PlayerCurrencies(lumens=self.lumens - amount, gems=self.gems)

    def add_gems(self, amount: int) -> PlayerCurrencies:
        """
        Return new PlayerCurrencies with gems added.

        Parameters
        ----------
        amount : int
            Amount to add (must be positive)

        Returns
        -------
        PlayerCurrencies
            New immutable instance with updated gems
        """
        validate_positive(amount, "amount")
        return PlayerCurrencies(lumens=self.lumens, gems=self.gems + amount)


# ============================================================================
# PLAYER AGGREGATE ROOT
# ============================================================================


class Player(AggregateRoot):
    """
    Player aggregate root with business logic.

    The Player is an aggregate root that maintains consistency across
    player identity, progression, currencies, and maiden collection.

    Business Rules
    --------------
    - Level increases when experience reaches threshold
    - Currencies cannot go negative
    - Leader maiden must be owned by the player
    - Experience gain triggers level-up automatically

    Domain Events
    -------------
    - player.leveled_up: When player gains a level
    - player.experience_gained: When player gains experience
    - player.currency_changed: When currency amounts change
    - player.leader_maiden_changed: When leader maiden is updated
    """

    def __init__(
        self,
        identity: PlayerIdentity,
        progression: PlayerProgression,
        currencies: PlayerCurrencies,
        leader_maiden_id: Optional[int] = None,
        total_maidens_owned: int = 0,
        unique_maidens: int = 0,
    ) -> None:
        """
        Initialize Player aggregate.

        Parameters
        ----------
        identity : PlayerIdentity
            Player identity (discord_id, username, etc.)
        progression : PlayerProgression
            Player progression state (level, xp, etc.)
        currencies : PlayerCurrencies
            Player currencies (lumens, gems)
        leader_maiden_id : Optional[int]
            ID of currently selected leader maiden
        total_maidens_owned : int
            Total number of maidens owned
        unique_maidens : int
            Number of unique maiden types collected
        """
        super().__init__(identity.discord_id)

        # Store value objects (immutable)
        self._identity = identity
        self._progression = progression
        self._currencies = currencies

        # Mutable state
        self._leader_maiden_id = leader_maiden_id
        self._total_maidens_owned = total_maidens_owned
        self._unique_maidens = unique_maidens

    # ========================================================================
    # PROPERTIES (READ-ONLY ACCESS TO VALUE OBJECTS)
    # ========================================================================

    @property
    def identity(self) -> PlayerIdentity:
        """Get player identity (immutable)."""
        return self._identity

    @property
    def progression(self) -> PlayerProgression:
        """Get player progression (immutable)."""
        return self._progression

    @property
    def currencies(self) -> PlayerCurrencies:
        """Get player currencies (immutable)."""
        return self._currencies

    @property
    def leader_maiden_id(self) -> Optional[int]:
        """Get leader maiden ID."""
        return self._leader_maiden_id

    @property
    def total_maidens_owned(self) -> int:
        """Get total maidens owned."""
        return self._total_maidens_owned

    @property
    def unique_maidens(self) -> int:
        """Get unique maidens collected."""
        return self._unique_maidens

    # ========================================================================
    # BUSINESS LOGIC - EXPERIENCE & PROGRESSION
    # ========================================================================

    def add_experience(self, amount: int) -> None:
        """
        Add experience points and handle level-ups.

        This method encapsulates the business logic for experience gain
        and automatic level progression.

        Parameters
        ----------
        amount : int
            Experience points to add (must be positive)

        Business Rules
        --------------
        - Experience can overflow into multiple levels
        - Each level-up recalculates experience threshold
        - Domain events emitted for each level-up

        Examples
        --------
        >>> player.add_experience(500)  # May trigger multiple level-ups
        """
        validate_positive(amount, "amount")

        current_xp = self._progression.experience + amount
        current_level = self._progression.level
        xp_threshold = self._progression.experience_to_next_level

        # Emit experience gained event
        self.add_domain_event(
            "player.experience_gained",
            {
                "player_id": self.id,
                "amount": amount,
                "new_total": current_xp,
            },
        )

        # Handle level-ups (may be multiple if large XP gain)
        levels_gained = 0
        while current_xp >= xp_threshold:
            current_xp -= xp_threshold
            current_level += 1
            levels_gained += 1
            xp_threshold = self._calculate_experience_threshold(current_level)

            # Emit level-up event
            self.add_domain_event(
                "player.leveled_up",
                {
                    "player_id": self.id,
                    "old_level": current_level - 1,
                    "new_level": current_level,
                },
            )

        # Update progression value object (immutable, so create new instance)
        self._progression = PlayerProgression(
            level=current_level,
            experience=current_xp,
            experience_to_next_level=xp_threshold,
        )

    @staticmethod
    def _calculate_experience_threshold(level: int) -> int:
        """
        Calculate experience needed for next level.

        Business Rule: Experience threshold grows exponentially.

        Parameters
        ----------
        level : int
            Current level

        Returns
        -------
        int
            Experience needed to reach next level
        """
        # Example formula: base * level^1.5
        base_xp = 100
        return int(base_xp * (level**1.5))

    # ========================================================================
    # BUSINESS LOGIC - CURRENCIES
    # ========================================================================

    def add_currency(self, currency_type: str, amount: int) -> None:
        """
        Add currency to the player.

        Parameters
        ----------
        currency_type : str
            Type of currency ("lumens" or "gems")
        amount : int
            Amount to add (must be positive)

        Raises
        ------
        DomainValidationError
            If currency_type is invalid

        Examples
        --------
        >>> player.add_currency("lumens", 1000)
        >>> player.add_currency("gems", 50)
        """
        validate_positive(amount, "amount")

        if currency_type == "lumens":
            self._currencies = self._currencies.add_lumens(amount)
        elif currency_type == "gems":
            self._currencies = self._currencies.add_gems(amount)
        else:
            raise DomainValidationError(
                f"Invalid currency type: {currency_type}",
                field="currency_type",
            )

        self.add_domain_event(
            "player.currency_changed",
            {
                "player_id": self.id,
                "currency_type": currency_type,
                "amount_added": amount,
                "new_total": (
                    self._currencies.lumens
                    if currency_type == "lumens"
                    else self._currencies.gems
                ),
            },
        )

    def subtract_currency(self, currency_type: str, amount: int) -> None:
        """
        Subtract currency from the player.

        Parameters
        ----------
        currency_type : str
            Type of currency ("lumens" or "gems")
        amount : int
            Amount to subtract (must be positive)

        Raises
        ------
        DomainValidationError
            If currency_type is invalid or insufficient funds

        Examples
        --------
        >>> player.subtract_currency("lumens", 500)
        """
        validate_positive(amount, "amount")

        if currency_type == "lumens":
            self._currencies = self._currencies.subtract_lumens(amount)
        elif currency_type == "gems":
            raise NotImplementedError("Gem subtraction not yet implemented")
        else:
            raise DomainValidationError(
                f"Invalid currency type: {currency_type}",
                field="currency_type",
            )

        self.add_domain_event(
            "player.currency_changed",
            {
                "player_id": self.id,
                "currency_type": currency_type,
                "amount_subtracted": amount,
                "new_total": self._currencies.lumens,
            },
        )

    # ========================================================================
    # BUSINESS LOGIC - MAIDEN MANAGEMENT
    # ========================================================================

    def set_leader_maiden(self, maiden_id: int) -> None:
        """
        Set the player's leader maiden.

        Business Rule: Leader maiden must be owned by the player.
        (Validation of ownership happens in service layer before calling this)

        Parameters
        ----------
        maiden_id : int
            ID of the maiden to set as leader

        Examples
        --------
        >>> player.set_leader_maiden(42)
        """
        validate_positive(maiden_id, "maiden_id")

        old_leader_id = self._leader_maiden_id
        self._leader_maiden_id = maiden_id

        self.add_domain_event(
            "player.leader_maiden_changed",
            {
                "player_id": self.id,
                "old_leader_id": old_leader_id,
                "new_leader_id": maiden_id,
            },
        )

    def increment_maiden_count(self, is_unique: bool = False) -> None:
        """
        Increment maiden counts when a maiden is acquired.

        Parameters
        ----------
        is_unique : bool
            Whether this is a new unique maiden type

        Examples
        --------
        >>> player.increment_maiden_count(is_unique=True)  # New type
        >>> player.increment_maiden_count(is_unique=False)  # Duplicate
        """
        self._total_maidens_owned += 1
        if is_unique:
            self._unique_maidens += 1

        self.add_domain_event(
            "player.maiden_acquired",
            {
                "player_id": self.id,
                "is_unique": is_unique,
                "total_maidens": self._total_maidens_owned,
                "unique_maidens": self._unique_maidens,
            },
        )

    # ========================================================================
    # FACTORY METHODS (CONVERT FROM DATABASE MODELS)
    # ========================================================================

    @classmethod
    def from_db(
        cls,
        player_core: PlayerCoreDB,
        progression: Optional[PlayerProgressionDB] = None,
        currencies: Optional[PlayerCurrenciesDB] = None,
    ) -> Player:
        """
        Create Player domain model from database models.

        This factory method converts anemic database models into
        a rich domain model with business logic.

        Parameters
        ----------
        player_core : PlayerCore
            Core player database model
        progression : Optional[PlayerProgression]
            Progression database model (or None for defaults)
        currencies : Optional[PlayerCurrencies]
            Currencies database model (or None for defaults)

        Returns
        -------
        Player
            Rich domain model instance

        Examples
        --------
        >>> player = Player.from_db(player_core_row, progression_row, currencies_row)
        """
        # Extract identity
        identity = PlayerIdentity(
            discord_id=player_core.discord_id,
            username=player_core.username,
            discriminator=player_core.discriminator,
        )

        # Extract progression (with defaults if not provided)
        if progression:
            # Calculate experience to next level (placeholder formula)
            # TODO: Use proper leveling formula from game config
            exp_to_next = (progression.level * 100) - progression.xp
            prog_vo = PlayerProgression(
                level=progression.level,
                experience=progression.xp,
                experience_to_next_level=max(exp_to_next, 0),
            )
        else:
            prog_vo = PlayerProgression(level=1, experience=0, experience_to_next_level=100)

        # Extract currencies (with defaults if not provided)
        if currencies:
            curr_vo = PlayerCurrencies(
                lumens=currencies.lumees,
                gems=currencies.auric_coin,
            )
        else:
            curr_vo = PlayerCurrencies(lumens=0, gems=0)

        return cls(
            identity=identity,
            progression=prog_vo,
            currencies=curr_vo,
            leader_maiden_id=player_core.leader_maiden_id,
            total_maidens_owned=player_core.total_maidens_owned,
            unique_maidens=player_core.unique_maidens,
        )

    # ========================================================================
    # CONVERSION TO DATABASE MODELS
    # ========================================================================

    def to_db_updates(self) -> dict:
        """
        Convert domain model state to database update dict.

        Returns
        -------
        dict
            Dictionary of fields to update in database models

        Examples
        --------
        >>> updates = player.to_db_updates()
        >>> player_core.update(updates['core'])
        >>> progression.update(updates['progression'])
        """
        return {
            "core": {
                "leader_maiden_id": self._leader_maiden_id,
                "total_maidens_owned": self._total_maidens_owned,
                "unique_maidens": self._unique_maidens,
            },
            "progression": {
                "level": self._progression.level,
                "experience": self._progression.experience,
                "experience_to_next_level": self._progression.experience_to_next_level,
            },
            "currencies": {
                "lumens": self._currencies.lumens,
                "gems": self._currencies.gems,
            },
        }
