"""
Maiden Domain Model for Lumen RPG (LES 2025).

Purpose
-------
Rich domain model representing a player-owned maiden with business logic for
stack management, fusion, upgrades, and protection mechanisms.

This is separate from the database model (Maiden) which is an anemic data schema.
Services convert between database models and domain models.

Responsibilities
----------------
- Enforce business rules for maiden stacks and fusion
- Manage quantity changes (add/remove)
- Handle lock/unlock protection
- Validate fusability rules
- Validate state transitions
- Emit domain events for important changes

Non-Responsibilities
--------------------
- Persistence (handled by repositories)
- Database transactions (handled by services/repositories)
- UI presentation (handled by cogs)
- Fusion mechanics (handled by FusionService)

LUMEN LAW / LES 2025 Compliance
-------------------------------
- Business logic belongs in domain models (P1.2, P1.3)
- Services orchestrate domain models, don't manipulate data directly
- Domain events communicate state changes
- Self-validating with explicit invariants

Usage Example
-------------
>>> # Create from database model
>>> maiden = Maiden.from_db(maiden_row, maiden_base_row)
>>>
>>> # Business logic in domain model
>>> maiden.add_quantity(5)  # Stack management
>>> maiden.lock()  # Protection from fusion
>>> can_fuse = maiden.is_fusable()  # Business rule validation
>>>
>>> # Domain events emitted automatically
>>> events = maiden.get_pending_events()
>>> for event in events:
...     await event_bus.publish(event.event_name, event.payload)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, Optional

from src.domain.models.base import (
    AggregateRoot,
    DomainValidationError,
    ValueObject,
    validate_non_negative,
    validate_positive,
    validate_range,
)

if TYPE_CHECKING:
    from src.database.models.core.maiden import Maiden as MaidenDB
    from src.database.models.core.maiden_base import MaidenBase as MaidenBaseDB


# ============================================================================
# CONSTANTS
# ============================================================================

MIN_TIER = 1
MAX_TIER = 12
MIN_FUSABLE_QUANTITY = 2


# ============================================================================
# VALUE OBJECTS
# ============================================================================


@dataclass(frozen=True)
class MaidenIdentity:
    """
    Immutable value object representing maiden identity.

    Attributes
    ----------
    player_id : int
        Discord ID of the owner
    maiden_base_id : int
        ID of the maiden base template
    tier : int
        Tier level (1-12)
    """

    player_id: int
    maiden_base_id: int
    tier: int

    def __post_init__(self) -> None:
        """Validate identity on creation."""
        validate_positive(self.player_id, "player_id")
        validate_positive(self.maiden_base_id, "maiden_base_id")
        validate_range(self.tier, MIN_TIER, MAX_TIER, "tier")


@dataclass(frozen=True)
class MaidenBaseStats:
    """
    Immutable value object representing maiden base template information.

    This represents the archetypal template that all maiden instances
    of this type share.

    Attributes
    ----------
    name : str
        Maiden name
    element : str
        Elemental affinity
    base_tier : int
        Starting tier when summoned
    base_atk : int
        Base attack stat
    base_def : int
        Base defense stat
    image_url : str
        Artwork URL
    rarity_weight : float
        Gacha weighting (lower = rarer)
    is_premium : bool
        Flags limited/premium availability
    """

    name: str
    element: str
    base_tier: int
    base_atk: int
    base_def: int
    image_url: str
    rarity_weight: float
    is_premium: bool

    def __post_init__(self) -> None:
        """Validate base stats on creation."""
        if not self.name or not self.name.strip():
            raise DomainValidationError("name cannot be empty", field="name")
        if not self.element or not self.element.strip():
            raise DomainValidationError("element cannot be empty", field="element")
        validate_range(self.base_tier, MIN_TIER, MAX_TIER, "base_tier")
        validate_non_negative(self.base_atk, "base_atk")
        validate_non_negative(self.base_def, "base_def")


@dataclass(frozen=True)
class MaidenMetadata:
    """
    Immutable value object representing maiden metadata.

    Attributes
    ----------
    element : str
        Current elemental affinity (can differ from base)
    acquired_from : str
        Acquisition source label
    times_fused : int
        Number of times this maiden has been used in fusion
    """

    element: str
    acquired_from: str
    times_fused: int

    def __post_init__(self) -> None:
        """Validate metadata on creation."""
        if not self.element or not self.element.strip():
            raise DomainValidationError("element cannot be empty", field="element")
        if not self.acquired_from or not self.acquired_from.strip():
            raise DomainValidationError("acquired_from cannot be empty", field="acquired_from")
        validate_non_negative(self.times_fused, "times_fused")

    def increment_fusion_count(self) -> MaidenMetadata:
        """
        Return new MaidenMetadata with fusion count incremented.

        Returns
        -------
        MaidenMetadata
            New immutable instance with fusion count +1
        """
        return MaidenMetadata(
            element=self.element,
            acquired_from=self.acquired_from,
            times_fused=self.times_fused + 1,
        )


# ============================================================================
# MAIDEN AGGREGATE ROOT
# ============================================================================


class Maiden(AggregateRoot):
    """
    Maiden aggregate root with business logic.

    The Maiden is an aggregate root that maintains consistency for
    player-owned maiden instances with stack-based management.

    Business Rules
    --------------
    - Quantity must be >= 0 (zero triggers soft-delete in service layer)
    - Tier must be in range [1, 12]
    - Fusable if: quantity >= 2, not locked, tier < 12
    - Locked maidens cannot be used in fusion
    - Each player can only have one stack per (maiden_base_id, tier)

    Domain Events
    -------------
    - maiden.quantity_changed: When quantity is added or removed
    - maiden.locked: When maiden is locked
    - maiden.unlocked: When maiden is unlocked
    - maiden.fusion_count_incremented: When used in fusion
    """

    def __init__(
        self,
        maiden_id: int,
        identity: MaidenIdentity,
        base_stats: MaidenBaseStats,
        metadata: MaidenMetadata,
        quantity: int,
        is_locked: bool = False,
    ) -> None:
        """
        Initialize Maiden aggregate.

        Parameters
        ----------
        maiden_id : int
            Database ID of this maiden instance
        identity : MaidenIdentity
            Maiden identity (player_id, maiden_base_id, tier)
        base_stats : MaidenBaseStats
            Maiden base template information
        metadata : MaidenMetadata
            Maiden metadata (element, acquired_from, times_fused)
        quantity : int
            Stack quantity (must be >= 0)
        is_locked : bool
            Whether maiden is locked (default False)
        """
        super().__init__(maiden_id)

        # Store value objects (immutable)
        self._identity = identity
        self._base_stats = base_stats
        self._metadata = metadata

        # Mutable state
        self._quantity = quantity
        self._is_locked = is_locked

        # Validate initial state
        validate_non_negative(self._quantity, "quantity")

    # ========================================================================
    # PROPERTIES (READ-ONLY ACCESS TO VALUE OBJECTS)
    # ========================================================================

    @property
    def identity(self) -> MaidenIdentity:
        """Get maiden identity (immutable)."""
        return self._identity

    @property
    def base_stats(self) -> MaidenBaseStats:
        """Get maiden base stats (immutable)."""
        return self._base_stats

    @property
    def metadata(self) -> MaidenMetadata:
        """Get maiden metadata (immutable)."""
        return self._metadata

    @property
    def quantity(self) -> int:
        """Get stack quantity."""
        return self._quantity

    @property
    def is_locked(self) -> bool:
        """Get lock status."""
        return self._is_locked

    # ========================================================================
    # BUSINESS LOGIC - QUANTITY MANAGEMENT
    # ========================================================================

    def add_quantity(self, amount: int) -> None:
        """
        Add to the maiden stack quantity.

        This method encapsulates the business logic for stack growth.

        Parameters
        ----------
        amount : int
            Quantity to add (must be positive)

        Business Rules
        --------------
        - Amount must be positive
        - New quantity cannot exceed int limits

        Examples
        --------
        >>> maiden.add_quantity(5)  # Stack grows by 5
        """
        validate_positive(amount, "amount")

        old_quantity = self._quantity
        self._quantity += amount

        self.add_domain_event(
            "maiden.quantity_changed",
            {
                "maiden_id": self.id,
                "player_id": self._identity.player_id,
                "maiden_base_id": self._identity.maiden_base_id,
                "tier": self._identity.tier,
                "old_quantity": old_quantity,
                "new_quantity": self._quantity,
                "amount_added": amount,
            },
        )

    def remove_quantity(self, amount: int) -> None:
        """
        Remove from the maiden stack quantity.

        This method encapsulates the business logic for stack reduction.

        Parameters
        ----------
        amount : int
            Quantity to remove (must be positive)

        Raises
        ------
        DomainValidationError
            If insufficient quantity or amount invalid

        Business Rules
        --------------
        - Amount must be positive
        - Cannot remove more than current quantity
        - If quantity reaches 0, service layer handles soft-delete

        Examples
        --------
        >>> maiden.remove_quantity(3)  # Stack shrinks by 3
        """
        validate_positive(amount, "amount")

        if self._quantity < amount:
            raise DomainValidationError(
                f"Insufficient quantity: have {self._quantity}, need {amount}",
                field="quantity",
            )

        old_quantity = self._quantity
        self._quantity -= amount

        self.add_domain_event(
            "maiden.quantity_changed",
            {
                "maiden_id": self.id,
                "player_id": self._identity.player_id,
                "maiden_base_id": self._identity.maiden_base_id,
                "tier": self._identity.tier,
                "old_quantity": old_quantity,
                "new_quantity": self._quantity,
                "amount_removed": amount,
            },
        )

    # ========================================================================
    # BUSINESS LOGIC - LOCK/UNLOCK PROTECTION
    # ========================================================================

    def lock(self) -> None:
        """
        Lock the maiden to prevent fusion/consumption.

        Business Rule: Locked maidens cannot be used in fusion operations.

        Examples
        --------
        >>> maiden.lock()  # Protect from accidental fusion
        """
        if self._is_locked:
            raise DomainValidationError("Maiden is already locked", field="is_locked")

        self._is_locked = True

        self.add_domain_event(
            "maiden.locked",
            {
                "maiden_id": self.id,
                "player_id": self._identity.player_id,
                "maiden_base_id": self._identity.maiden_base_id,
                "tier": self._identity.tier,
            },
        )

    def unlock(self) -> None:
        """
        Unlock the maiden to allow fusion/consumption.

        Examples
        --------
        >>> maiden.unlock()  # Allow fusion again
        """
        if not self._is_locked:
            raise DomainValidationError("Maiden is already unlocked", field="is_locked")

        self._is_locked = False

        self.add_domain_event(
            "maiden.unlocked",
            {
                "maiden_id": self.id,
                "player_id": self._identity.player_id,
                "maiden_base_id": self._identity.maiden_base_id,
                "tier": self._identity.tier,
            },
        )

    # ========================================================================
    # BUSINESS LOGIC - FUSION RULES
    # ========================================================================

    def is_fusable(self) -> bool:
        """
        Check if this maiden can be fused.

        Business Rules
        --------------
        - Quantity must be >= 2 (can fuse with self)
        - Must not be locked
        - Tier must be < 12 (max tier cannot fuse further)

        Returns
        -------
        bool
            True if maiden can be fused

        Examples
        --------
        >>> if maiden.is_fusable():
        ...     # Proceed with fusion
        """
        return (
            self._quantity >= MIN_FUSABLE_QUANTITY
            and not self._is_locked
            and self._identity.tier < MAX_TIER
        )

    def increment_fusion_count(self) -> None:
        """
        Increment the fusion count when this maiden is used in fusion.

        Business Rule: Tracks how many times this maiden has been fused.

        Examples
        --------
        >>> maiden.increment_fusion_count()  # After fusion operation
        """
        self._metadata = self._metadata.increment_fusion_count()

        self.add_domain_event(
            "maiden.fusion_count_incremented",
            {
                "maiden_id": self.id,
                "player_id": self._identity.player_id,
                "maiden_base_id": self._identity.maiden_base_id,
                "tier": self._identity.tier,
                "new_fusion_count": self._metadata.times_fused,
            },
        )

    # ========================================================================
    # COMPUTED PROPERTIES - BATTLE STATS
    # ========================================================================

    def calculate_atk(self) -> int:
        """
        Calculate effective attack based on tier and base stats.

        Business Rule: Attack scales with tier.

        Returns
        -------
        int
            Effective attack stat
        """
        # Example formula: base_atk * (1 + (tier - 1) * 0.2)
        tier_multiplier = 1 + (self._identity.tier - 1) * 0.2
        return int(self._base_stats.base_atk * tier_multiplier)

    def calculate_def(self) -> int:
        """
        Calculate effective defense based on tier and base stats.

        Business Rule: Defense scales with tier.

        Returns
        -------
        int
            Effective defense stat
        """
        # Example formula: base_def * (1 + (tier - 1) * 0.2)
        tier_multiplier = 1 + (self._identity.tier - 1) * 0.2
        return int(self._base_stats.base_def * tier_multiplier)

    def calculate_power(self) -> int:
        """
        Calculate total combat power.

        Business Rule: Power = ATK + DEF.

        Returns
        -------
        int
            Total combat power
        """
        return self.calculate_atk() + self.calculate_def()

    # ========================================================================
    # FACTORY METHODS (CONVERT FROM DATABASE MODELS)
    # ========================================================================

    @classmethod
    def from_db(
        cls,
        maiden: MaidenDB,
        maiden_base: MaidenBaseDB,
    ) -> Maiden:
        """
        Create Maiden domain model from database models.

        This factory method converts anemic database models into
        a rich domain model with business logic.

        Parameters
        ----------
        maiden : Maiden
            Player-owned maiden database model
        maiden_base : MaidenBase
            Maiden base template database model

        Returns
        -------
        Maiden
            Rich domain model instance

        Examples
        --------
        >>> maiden = Maiden.from_db(maiden_row, maiden_base_row)
        """
        # Extract identity
        identity = MaidenIdentity(
            player_id=maiden.player_id,
            maiden_base_id=maiden.maiden_base_id,
            tier=maiden.tier,
        )

        # Extract base stats
        base_stats = MaidenBaseStats(
            name=maiden_base.name,
            element=maiden_base.element,
            base_tier=maiden_base.base_tier,
            base_atk=maiden_base.base_atk,
            base_def=maiden_base.base_def,
            image_url=maiden_base.image_url,
            rarity_weight=maiden_base.rarity_weight,
            is_premium=maiden_base.is_premium,
        )

        # Extract metadata
        metadata = MaidenMetadata(
            element=maiden.element,
            acquired_from=maiden.acquired_from,
            times_fused=maiden.times_fused,
        )

        return cls(
            maiden_id=maiden.id,
            identity=identity,
            base_stats=base_stats,
            metadata=metadata,
            quantity=maiden.quantity,
            is_locked=maiden.is_locked,
        )

    # ========================================================================
    # CONVERSION TO DATABASE MODELS
    # ========================================================================

    def to_db_updates(self) -> Dict[str, Any]:
        """
        Convert domain model state to database update dict.

        Returns
        -------
        dict
            Dictionary of fields to update in database model

        Examples
        --------
        >>> updates = maiden.to_db_updates()
        >>> maiden_db.update(updates)
        """
        return {
            "quantity": self._quantity,
            "is_locked": self._is_locked,
            "times_fused": self._metadata.times_fused,
            "element": self._metadata.element,
            "acquired_from": self._metadata.acquired_from,
        }
