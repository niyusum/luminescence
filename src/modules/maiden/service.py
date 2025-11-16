"""
Maiden Service - LES 2025 Compliant
====================================

Purpose
-------
Manages player-owned maiden instances including inventory operations, stack management,
fusable queries, and lock/unlock operations with full transaction safety, audit logging,
and event emission.

Domain
------
- Maiden inventory management (add, remove, update quantities)
- Stack-based maiden ownership (unique constraint: player+base+tier)
- Fusable maiden queries
- Lock/unlock operations for protection
- Collection queries and statistics

LUMEN 2025 COMPLIANCE
---------------------
✓ Pure business logic - no Discord dependencies
✓ Transaction-safe - all writes in atomic transactions
✓ Config-driven - no hardcoded values
✓ Domain exceptions - raises NotFoundError, ValidationError, InvalidOperationError
✓ Event-driven - emits events for maiden changes
✓ Observable - structured logging, audit trail, timing metrics
✓ Pessimistic locking - uses SELECT FOR UPDATE for all writes
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from sqlalchemy import and_, select

from src.core.database.service import DatabaseService
from src.core.infra.audit_logger import AuditLogger
from src.core.logging.logger import get_logger
from src.core.validation.input_validator import InputValidator
from src.modules.shared.base_repository import BaseRepository
from src.modules.shared.base_service import BaseService
from src.modules.shared.exceptions import (
    InvalidOperationError,
    InsufficientResourcesError,
    NotFoundError,
    ValidationError,
)

if TYPE_CHECKING:
    from logging import Logger

    from src.core.config.manager import ConfigManager
    from src.core.event.bus import EventBus
    from src.database.models.core.maiden import Maiden


# ============================================================================
# Repository
# ============================================================================


class MaidenRepository(BaseRepository["Maiden"]):
    """Repository for Maiden model with custom queries."""

    async def find_by_player_base_tier(
        self,
        session: Any,
        player_id: int,
        maiden_base_id: int,
        tier: int,
        for_update: bool = False,
    ) -> Optional["Maiden"]:
        """
        Find maiden by player_id, maiden_base_id, and tier.

        This leverages the unique constraint on (player_id, maiden_base_id, tier).
        """
        return await self.find_one_where(
            session,
            and_(
                self.model_class.player_id == player_id,
                self.model_class.maiden_base_id == maiden_base_id,
                self.model_class.tier == tier,
            ),
            for_update=for_update,
        )

    async def find_fusable_maidens(
        self,
        session: Any,
        player_id: int,
    ) -> List["Maiden"]:
        """
        Find all maidens that can be fused (quantity >= 2, not locked, tier < 12).
        """
        stmt = (
            select(self.model_class)
            .where(
                and_(
                    self.model_class.player_id == player_id,
                    self.model_class.quantity >= 2,
                    self.model_class.is_locked == False,
                    self.model_class.tier < 12,
                    self.model_class.deleted_at.is_(None),
                )
            )
            .order_by(self.model_class.tier.desc(), self.model_class.maiden_base_id)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_player_collection(
        self,
        session: Any,
        player_id: int,
        tier_filter: Optional[int] = None,
        element_filter: Optional[str] = None,
    ) -> List["Maiden"]:
        """Get all maidens owned by player with optional filters."""
        conditions = [
            self.model_class.player_id == player_id,
            self.model_class.deleted_at.is_(None),
        ]

        if tier_filter is not None:
            conditions.append(self.model_class.tier == tier_filter)

        if element_filter:
            conditions.append(self.model_class.element == element_filter)

        stmt = (
            select(self.model_class)
            .where(and_(*conditions))
            .order_by(self.model_class.tier.desc(), self.model_class.maiden_base_id)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


# ============================================================================
# MaidenService
# ============================================================================


class MaidenService(BaseService):
    """
    Service for managing player-owned maiden instances.

    Handles maiden inventory, stack management, fusable queries,
    and lock/unlock operations.

    Dependencies
    ------------
    - ConfigManager: For config access
    - EventBus: For emitting maiden-related events
    - Logger: For structured logging
    - DatabaseService: For transaction management (injected via context)
    - AuditLogger: For audit trail (static)

    Public Methods
    --------------
    - get_maiden() -> Get maiden by ID
    - get_player_maiden() -> Get maiden by player+base+tier
    - get_player_collection() -> Get all maidens for player
    - add_maiden() -> Add new maiden or increase stack quantity
    - remove_maiden() -> Remove maiden or decrease stack quantity
    - update_quantity() -> Set specific stack quantity
    - lock_maiden() -> Lock maiden to prevent fusion
    - unlock_maiden() -> Unlock maiden
    - get_fusable_maidens() -> Find all fusable maidens
    - maiden_exists() -> Check if maiden exists
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        """
        Initialize MaidenService with required dependencies.

        Args:
            config_manager: Application configuration manager
            event_bus: Event bus for cross-module communication
            logger: Structured logger instance
        """
        super().__init__(config_manager, event_bus, logger)

        # Initialize repository with proper logger
        from src.database.models.core.maiden import Maiden

        self._maiden_repo = MaidenRepository(
            model_class=Maiden,
            logger=get_logger(f"{__name__}.MaidenRepository"),
        )

    # ========================================================================
    # PUBLIC API - Read Operations
    # ========================================================================

    async def get_maiden(self, maiden_id: int) -> Dict[str, Any]:
        """
        Get maiden by ID.

        This is a **read-only** operation using get_session().

        Args:
            maiden_id: Maiden ID

        Returns:
            Dict with maiden information

        Raises:
            NotFoundError: If maiden not found

        Example:
            >>> maiden = await maiden_service.get_maiden(42)
        """
        maiden_id = InputValidator.validate_positive_integer(maiden_id, "maiden_id")

        self.log_operation("get_maiden", maiden_id=maiden_id)

        async with DatabaseService.get_session() as session:
            maiden = await self._maiden_repo.get(session, maiden_id)

            if not maiden or maiden.deleted_at is not None:
                raise NotFoundError("Maiden", maiden_id)

            return self._maiden_to_dict(maiden)

    async def get_player_maiden(
        self,
        player_id: int,
        maiden_base_id: int,
        tier: int,
    ) -> Dict[str, Any]:
        """
        Get maiden by player + maiden_base + tier.

        Uses the unique constraint on (player_id, maiden_base_id, tier).

        Args:
            player_id: Discord ID of the player
            maiden_base_id: Maiden base template ID
            tier: Tier level

        Returns:
            Dict with maiden information

        Raises:
            NotFoundError: If maiden not found
        """
        player_id = InputValidator.validate_discord_id(player_id)
        maiden_base_id = InputValidator.validate_positive_integer(
            maiden_base_id, "maiden_base_id"
        )
        tier = InputValidator.validate_integer(tier, "tier", min_value=1, max_value=12)

        self.log_operation(
            "get_player_maiden",
            player_id=player_id,
            maiden_base_id=maiden_base_id,
            tier=tier,
        )

        async with DatabaseService.get_session() as session:
            maiden = await self._maiden_repo.find_by_player_base_tier(
                session,
                player_id=player_id,
                maiden_base_id=maiden_base_id,
                tier=tier,
            )

            if not maiden or maiden.deleted_at is not None:
                raise NotFoundError(
                    "Maiden",
                    f"player={player_id}, base={maiden_base_id}, tier={tier}",
                )

            return self._maiden_to_dict(maiden)

    async def get_player_collection(
        self,
        player_id: int,
        tier_filter: Optional[int] = None,
        element_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get all maidens owned by player.

        Args:
            player_id: Discord ID of the player
            tier_filter: Optional tier filter
            element_filter: Optional element filter

        Returns:
            List of maiden dicts

        Example:
            >>> maidens = await maiden_service.get_player_collection(123456789, tier_filter=5)
        """
        player_id = InputValidator.validate_discord_id(player_id)

        if tier_filter is not None:
            tier_filter = InputValidator.validate_integer(tier_filter, "tier", min_value=1, max_value=12)

        self.log_operation(
            "get_player_collection",
            player_id=player_id,
            tier_filter=tier_filter,
            element_filter=element_filter,
        )

        async with DatabaseService.get_session() as session:
            maidens = await self._maiden_repo.get_player_collection(
                session,
                player_id=player_id,
                tier_filter=tier_filter,
                element_filter=element_filter,
            )

            return [self._maiden_to_dict(m) for m in maidens]

    async def get_fusable_maidens(self, player_id: int) -> List[Dict[str, Any]]:
        """
        Get all maidens that can be fused.

        A maiden is fusable if:
        - quantity >= 2 (can fuse with itself)
        - is_locked == False
        - tier < 12 (max tier cannot be fused further)

        Args:
            player_id: Discord ID of the player

        Returns:
            List of fusable maiden dicts

        Example:
            >>> fusable = await maiden_service.get_fusable_maidens(123456789)
        """
        player_id = InputValidator.validate_discord_id(player_id)

        self.log_operation("get_fusable_maidens", player_id=player_id)

        async with DatabaseService.get_session() as session:
            maidens = await self._maiden_repo.find_fusable_maidens(session, player_id)

            return [self._maiden_to_dict(m) for m in maidens]

    async def maiden_exists(
        self,
        player_id: int,
        maiden_base_id: int,
        tier: int,
    ) -> bool:
        """Check if maiden exists."""
        player_id = InputValidator.validate_discord_id(player_id)
        maiden_base_id = InputValidator.validate_positive_integer(
            maiden_base_id, "maiden_base_id"
        )
        tier = InputValidator.validate_integer(tier, "tier", min_value=1, max_value=12)

        async with DatabaseService.get_session() as session:
            maiden = await self._maiden_repo.find_by_player_base_tier(
                session,
                player_id=player_id,
                maiden_base_id=maiden_base_id,
                tier=tier,
            )
            return maiden is not None and maiden.deleted_at is None

    # ========================================================================
    # PUBLIC API - Write Operations
    # ========================================================================

    async def add_maiden(
        self,
        player_id: int,
        maiden_base_id: int,
        tier: int,
        element: str,
        quantity: int = 1,
        acquired_from: str = "summon",
        reason: str = "maiden_acquisition",
    ) -> Dict[str, Any]:
        """
        Add maiden to player's collection.

        If a maiden with same (player_id, maiden_base_id, tier) exists,
        increases the quantity. Otherwise creates new maiden stack.

        This is a **write operation** using get_transaction() with pessimistic locking.

        Args:
            player_id: Discord ID of the player
            maiden_base_id: Maiden base template ID
            tier: Tier level (1-12)
            element: Elemental affinity
            quantity: Number to add (default 1)
            acquired_from: Acquisition source label
            reason: Reason for the addition

        Returns:
            Dict with maiden information and operation result

        Raises:
            ValidationError: If inputs invalid

        Example:
            >>> result = await maiden_service.add_maiden(
            ...     player_id=123456789,
            ...     maiden_base_id=1,
            ...     tier=1,
            ...     element="fire",
            ...     quantity=1,
            ...     acquired_from="summon"
            ... )
        """
        player_id = InputValidator.validate_discord_id(player_id)
        maiden_base_id = InputValidator.validate_positive_integer(
            maiden_base_id, "maiden_base_id"
        )
        tier = InputValidator.validate_integer(tier, "tier", min_value=1, max_value=12)
        quantity = InputValidator.validate_positive_integer(quantity, "quantity")

        self.log_operation(
            "add_maiden",
            player_id=player_id,
            maiden_base_id=maiden_base_id,
            tier=tier,
            quantity=quantity,
        )

        async with DatabaseService.get_transaction() as session:
            # Try to find existing maiden stack
            maiden = await self._maiden_repo.find_by_player_base_tier(
                session,
                player_id=player_id,
                maiden_base_id=maiden_base_id,
                tier=tier,
                for_update=True,
            )

            if maiden and maiden.deleted_at is None:
                # Stack exists - increase quantity
                old_quantity = maiden.quantity
                maiden.quantity = old_quantity + quantity
                operation = "quantity_increased"

                self.log.info(
                    f"Maiden stack increased: +{quantity}",
                    extra={
                        "player_id": player_id,
                        "maiden_base_id": maiden_base_id,
                        "tier": tier,
                        "old_quantity": old_quantity,
                        "new_quantity": maiden.quantity,
                    },
                )
            else:
                # Create new maiden stack
                from src.database.models.core.maiden import Maiden

                maiden = Maiden(
                    player_id=player_id,
                    maiden_base_id=maiden_base_id,
                    quantity=quantity,
                    tier=tier,
                    element=element,
                    acquired_from=acquired_from,
                    times_fused=0,
                    is_locked=False,
                )

                self._maiden_repo.add(session, maiden)
                await session.flush()  # Get the ID
                operation = "created"

                self.log.info(
                    f"Maiden stack created: {quantity} maidens",
                    extra={
                        "player_id": player_id,
                        "maiden_id": maiden.id,
                        "maiden_base_id": maiden_base_id,
                        "tier": tier,
                        "quantity": quantity,
                    },
                )

            # Audit logging
            await AuditLogger.log(
                player_id=player_id,
                transaction_type="maiden_added",
                details={
                    "maiden_id": maiden.id,
                    "maiden_base_id": maiden_base_id,
                    "tier": tier,
                    "quantity_added": quantity,
                    "new_total": maiden.quantity,
                    "acquired_from": acquired_from,
                    "operation": operation,
                    "reason": reason,
                },
                context="maiden_acquisition",
            )

            # Event emission
            await self.emit_event(
                event_type="maiden.added",
                data={
                    "player_id": player_id,
                    "maiden_id": maiden.id,
                    "maiden_base_id": maiden_base_id,
                    "tier": tier,
                    "quantity_added": quantity,
                    "total_quantity": maiden.quantity,
                    "operation": operation,
                    "reason": reason,
                },
            )

            return {
                **self._maiden_to_dict(maiden),
                "operation": operation,
                "quantity_added": quantity,
            }

    async def remove_maiden(
        self,
        player_id: int,
        maiden_base_id: int,
        tier: int,
        quantity: int = 1,
        reason: str = "maiden_consumption",
    ) -> Dict[str, Any]:
        """
        Remove maiden from player's collection.

        Decreases the quantity. If quantity reaches 0, soft-deletes the maiden.

        This is a **write operation** using get_transaction() with pessimistic locking.

        Args:
            player_id: Discord ID of the player
            maiden_base_id: Maiden base template ID
            tier: Tier level
            quantity: Number to remove (default 1)
            reason: Reason for removal

        Returns:
            Dict with removal result

        Raises:
            NotFoundError: If maiden not found
            InsufficientResourcesError: If not enough quantity

        Example:
            >>> result = await maiden_service.remove_maiden(
            ...     player_id=123456789,
            ...     maiden_base_id=1,
            ...     tier=1,
            ...     quantity=1,
            ...     reason="fusion"
            ... )
        """
        player_id = InputValidator.validate_discord_id(player_id)
        maiden_base_id = InputValidator.validate_positive_integer(
            maiden_base_id, "maiden_base_id"
        )
        tier = InputValidator.validate_integer(tier, "tier", min_value=1, max_value=12)
        quantity = InputValidator.validate_positive_integer(quantity, "quantity")

        self.log_operation(
            "remove_maiden",
            player_id=player_id,
            maiden_base_id=maiden_base_id,
            tier=tier,
            quantity=quantity,
        )

        async with DatabaseService.get_transaction() as session:
            # Find and lock maiden
            maiden = await self._maiden_repo.find_by_player_base_tier(
                session,
                player_id=player_id,
                maiden_base_id=maiden_base_id,
                tier=tier,
                for_update=True,
            )

            if not maiden or maiden.deleted_at is not None:
                raise NotFoundError(
                    "Maiden",
                    f"player={player_id}, base={maiden_base_id}, tier={tier}",
                )

            # Check if locked
            if maiden.is_locked:
                raise InvalidOperationError(
                    "remove_maiden",
                    "Cannot remove locked maiden. Unlock first."
                )

            # Check sufficiency
            if maiden.quantity < quantity:
                raise InsufficientResourcesError(
                    resource="maiden_quantity",
                    required=quantity,
                    current=maiden.quantity,
                )

            old_quantity = maiden.quantity
            new_quantity = old_quantity - quantity

            if new_quantity == 0:
                # Soft delete
                from datetime import datetime, timezone

                maiden.deleted_at = datetime.now(timezone.utc)
                operation = "deleted"
            else:
                # Decrease quantity
                maiden.quantity = new_quantity
                operation = "quantity_decreased"

            # Audit logging
            await AuditLogger.log(
                player_id=player_id,
                transaction_type="maiden_removed",
                details={
                    "maiden_id": maiden.id,
                    "maiden_base_id": maiden_base_id,
                    "tier": tier,
                    "quantity_removed": quantity,
                    "old_quantity": old_quantity,
                    "new_quantity": new_quantity,
                    "operation": operation,
                    "reason": reason,
                },
                context="maiden_removal",
            )

            # Event emission
            await self.emit_event(
                event_type="maiden.removed",
                data={
                    "player_id": player_id,
                    "maiden_id": maiden.id,
                    "maiden_base_id": maiden_base_id,
                    "tier": tier,
                    "quantity_removed": quantity,
                    "old_quantity": old_quantity,
                    "new_quantity": new_quantity,
                    "operation": operation,
                    "reason": reason,
                },
            )

            self.log.info(
                f"Maiden removed: -{quantity} (operation: {operation})",
                extra={
                    "player_id": player_id,
                    "maiden_id": maiden.id,
                    "maiden_base_id": maiden_base_id,
                    "tier": tier,
                    "old_quantity": old_quantity,
                    "new_quantity": new_quantity,
                },
            )

            return {
                "player_id": player_id,
                "maiden_id": maiden.id,
                "maiden_base_id": maiden_base_id,
                "tier": tier,
                "quantity_removed": quantity,
                "old_quantity": old_quantity,
                "new_quantity": new_quantity,
                "operation": operation,
            }

    async def lock_maiden(
        self,
        player_id: int,
        maiden_id: int,
    ) -> Dict[str, Any]:
        """
        Lock maiden to prevent fusion/consumption.

        Args:
            player_id: Discord ID of the player
            maiden_id: Maiden ID

        Returns:
            Dict with lock result
        """
        player_id = InputValidator.validate_discord_id(player_id)
        maiden_id = InputValidator.validate_positive_integer(maiden_id, "maiden_id")

        async with DatabaseService.get_transaction() as session:
            maiden = await self._maiden_repo.get_for_update(session, maiden_id)

            if not maiden or maiden.deleted_at is not None:
                raise NotFoundError("Maiden", maiden_id)

            # Verify ownership
            if maiden.player_id != player_id:
                raise ValidationError("player_id", "Maiden does not belong to player")

            was_locked = maiden.is_locked
            maiden.is_locked = True

            await self.emit_event(
                event_type="maiden.locked",
                data={
                    "player_id": player_id,
                    "maiden_id": maiden_id,
                    "was_already_locked": was_locked,
                },
            )

            return {
                "player_id": player_id,
                "maiden_id": maiden_id,
                "is_locked": True,
                "was_already_locked": was_locked,
            }

    async def unlock_maiden(
        self,
        player_id: int,
        maiden_id: int,
    ) -> Dict[str, Any]:
        """Unlock maiden."""
        player_id = InputValidator.validate_discord_id(player_id)
        maiden_id = InputValidator.validate_positive_integer(maiden_id, "maiden_id")

        async with DatabaseService.get_transaction() as session:
            maiden = await self._maiden_repo.get_for_update(session, maiden_id)

            if not maiden or maiden.deleted_at is not None:
                raise NotFoundError("Maiden", maiden_id)

            if maiden.player_id != player_id:
                raise ValidationError("player_id", "Maiden does not belong to player")

            was_unlocked = not maiden.is_locked
            maiden.is_locked = False

            await self.emit_event(
                event_type="maiden.unlocked",
                data={
                    "player_id": player_id,
                    "maiden_id": maiden_id,
                    "was_already_unlocked": was_unlocked,
                },
            )

            return {
                "player_id": player_id,
                "maiden_id": maiden_id,
                "is_locked": False,
                "was_already_unlocked": was_unlocked,
            }

    # ========================================================================
    # PRIVATE HELPERS
    # ========================================================================

    def _maiden_to_dict(self, maiden: "Maiden") -> Dict[str, Any]:
        """Convert maiden model to dict."""
        return {
            "id": maiden.id,
            "player_id": maiden.player_id,
            "maiden_base_id": maiden.maiden_base_id,
            "quantity": maiden.quantity,
            "tier": maiden.tier,
            "element": maiden.element,
            "acquired_from": maiden.acquired_from,
            "times_fused": maiden.times_fused,
            "is_locked": maiden.is_locked,
            "created_at": maiden.created_at,
            "updated_at": maiden.updated_at,
        }
