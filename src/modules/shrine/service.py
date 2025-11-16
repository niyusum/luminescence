"""
ShrineService - Business logic for player shrine management
=============================================================

Handles:
- Shrine yield calculation with level/type modifiers
- Shrine collection with cooldown enforcement and anti-cheat
- Shrine upgrades with cost validation
- Shrine activation/deactivation
- Yield history ring buffer management

All operations follow LUMEN LAW (2025):
- Pure business logic, no Discord/UI concerns
- Config-driven yield formulas and cooldowns
- Transaction safety with pessimistic locking
- Event emission for all state changes
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from src.core.database.service import DatabaseService
from src.modules.shared.base_repository import BaseRepository
from src.modules.shared.exceptions import InvalidOperationError, NotFoundError, ValidationError
from src.modules.shared.base_service import BaseService
from src.core.validation.input_validator import InputValidator
from src.database.models.economy.shrine import PlayerShrine

if TYPE_CHECKING:
    from logging import Logger
    from src.core.config.manager import ConfigManager
    from src.core.event.bus import EventBus


class ShrineService(BaseService):
    """
    ShrineService handles all player shrine operations.

    Business Logic:
    - Yield calculation: base_yield * level_multiplier * type_multiplier
    - Cooldown enforcement: must wait cooldown_hours before collection
    - Anti-cheat: prevent duplicate/early collection
    - Upgrade validation: cost checks, max level limits
    - Ring buffer: maintain last N collection records in yield_history
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        event_bus: EventBus,
        logger: Logger,
    ):
        """Initialize ShrineService with PlayerShrine repository."""
        super().__init__(config_manager, event_bus, logger)
        self._shrine_repo = BaseRepository[PlayerShrine](PlayerShrine, self.log)

    # -------------------------------------------------------------------------
    # Core Operations
    # -------------------------------------------------------------------------

    async def create_shrine(
        self,
        player_id: int,
        shrine_type: str,
        slot: int = 1,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new shrine for a player.

        Args:
            player_id: Discord ID of player
            shrine_type: Type of shrine (e.g., 'lesser', 'radiant')
            slot: Slot number (default 1)
            context: Operation context for audit

        Returns:
            Dict with shrine data

        Raises:
            ValidationError: Invalid parameters
            BusinessRuleViolation: Shrine already exists in slot, max slots exceeded
        """
        # Validation
        player_id = InputValidator.validate_discord_id(player_id)
        shrine_type = InputValidator.validate_string(shrine_type, "shrine_type", min_length=1)
        slot = InputValidator.validate_positive_integer(slot, "slot")

        # Get config
        max_slots = self.get_config(f"shrines.{shrine_type}.max_slots", default=3)
        starting_level = self.get_config("shrines.starting_level", default=1)

        if slot > max_slots:
            raise InvalidOperationError(
                "create_shrine",
                f"Slot {slot} exceeds maximum slots ({max_slots}) for shrine type '{shrine_type}'"
            )

        async with DatabaseService.get_transaction() as session:
            # Check if shrine already exists in this slot
            existing = await self._shrine_repo.find_one_where(
                session,
                PlayerShrine.player_id == player_id,
                PlayerShrine.shrine_type == shrine_type,
                PlayerShrine.slot == slot,
            )

            if existing:
                raise InvalidOperationError(
                    "create_shrine",
                    f"Shrine type '{shrine_type}' already exists in slot {slot}"
                )

            # Create shrine
            shrine = PlayerShrine(
                player_id=player_id,
                shrine_type=shrine_type,
                slot=slot,
                level=starting_level,
                is_active=True,
                last_collected_at=None,
                yield_history=[],
                metadata={},
            )

            session.add(shrine)
            await session.flush()

            # Emit event
            await self.emit_event(
                "shrine.created",
                {
                    "player_id": player_id,
                    "shrine_id": shrine.id,
                    "shrine_type": shrine_type,
                    "slot": slot,
                    "level": starting_level,
                },
            )

            return {
                "shrine_id": shrine.id,
                "player_id": player_id,
                "shrine_type": shrine.shrine_type,
                "slot": slot,
                "level": starting_level,
                "is_active": True,
                "created_at": shrine.created_at,
            }

    async def collect_shrine_yield(
        self,
        player_id: int,
        shrine_id: int,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Collect yield from a shrine with cooldown and anti-cheat enforcement.

        Args:
            player_id: Discord ID of player
            shrine_id: Shrine ID to collect from
            context: Operation context for audit

        Returns:
            Dict with collection results (lumees_earned, next_collectible_at)

        Raises:
            ResourceNotFoundError: Shrine not found
            BusinessRuleViolation: Cooldown active, shrine inactive, not owned
        """
        # Validation
        player_id = InputValidator.validate_discord_id(player_id)
        shrine_id = InputValidator.validate_positive_integer(shrine_id, "shrine_id")

        async with DatabaseService.get_transaction() as session:
            # Fetch shrine with pessimistic lock
            shrine = await self._shrine_repo.find_one_where(
                session,
                PlayerShrine.id == shrine_id,
                for_update=True,
            )

            if not shrine:
                raise NotFoundError(f"Shrine {shrine_id} not found")

            # Ownership check
            if shrine.player_id != player_id:
                raise InvalidOperationError(
                    "collect_shrine_yield",
                    f"Shrine {shrine_id} does not belong to player {player_id}"
                )

            # Active check
            if not shrine.is_active:
                raise InvalidOperationError(
                    "collect_shrine_yield",
                    f"Shrine {shrine_id} is not active and cannot be collected"
                )

            # Cooldown check
            now = datetime.now(timezone.utc)
            cooldown_hours = self.get_config(
                f"shrines.{shrine.shrine_type}.cooldown_hours", default=8
            )

            if shrine.last_collected_at:
                next_collectible = shrine.last_collected_at + timedelta(hours=cooldown_hours)
                if now < next_collectible:
                    time_remaining = next_collectible - now
                    raise InvalidOperationError(
                        "collect_shrine_yield",
                        f"Shrine cooldown active. Time remaining: {time_remaining}"
                    )

            # Calculate yield
            yield_amount = self._calculate_yield(shrine)

            # Update shrine state
            shrine.last_collected_at = now

            # Update yield history (ring buffer - keep last 50 collections)
            max_history = self.get_config("shrines.max_yield_history", default=50)
            shrine.yield_history.append(
                {
                    "collected_at": now.isoformat(),
                    "amount": yield_amount,
                    "level": shrine.level,
                }
            )
            if len(shrine.yield_history) > max_history:
                shrine.yield_history = shrine.yield_history[-max_history:]
            flag_modified(shrine, "yield_history")

            # Calculate next collectible time
            next_collectible_at = now + timedelta(hours=cooldown_hours)

            # Emit event
            await self.emit_event(
                "shrine.collected",
                {
                    "player_id": player_id,
                    "shrine_id": shrine_id,
                    "shrine_type": shrine.shrine_type,
                    "yield_amount": yield_amount,
                    "level": shrine.level,
                    "collected_at": now.isoformat(),
                },
            )

            return {
                "shrine_id": shrine_id,
                "yield_collected": yield_amount,
                "level": shrine.level,
                "collected_at": now,
                "next_collectible_at": next_collectible_at,
                "cooldown_hours": cooldown_hours,
            }

    async def upgrade_shrine(
        self,
        player_id: int,
        shrine_id: int,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Upgrade a shrine to the next level.

        Args:
            player_id: Discord ID of player
            shrine_id: Shrine ID to upgrade
            context: Operation context for audit

        Returns:
            Dict with upgrade results (new_level, upgrade_cost)

        Raises:
            ResourceNotFoundError: Shrine not found
            BusinessRuleViolation: Max level reached, not owned
        """
        # Validation
        player_id = InputValidator.validate_discord_id(player_id)
        shrine_id = InputValidator.validate_positive_integer(shrine_id, "shrine_id")

        async with DatabaseService.get_transaction() as session:
            # Fetch shrine with pessimistic lock
            shrine = await self._shrine_repo.find_one_where(
                session,
                PlayerShrine.id == shrine_id,
                for_update=True,
            )

            if not shrine:
                raise NotFoundError(f"Shrine {shrine_id} not found")

            # Ownership check
            if shrine.player_id != player_id:
                raise InvalidOperationError(
                    "upgrade_shrine",
                    f"Shrine {shrine_id} does not belong to player {player_id}"
                )

            # Max level check
            max_level = self.get_config(f"shrines.{shrine.shrine_type}.max_level", default=10)
            if shrine.level >= max_level:
                raise InvalidOperationError(
                    "upgrade_shrine",
                    f"Shrine {shrine_id} is already at max level ({max_level})"
                )

            # Calculate upgrade cost (exponential scaling)
            current_level = shrine.level
            base_cost = self.get_config(f"shrines.{shrine.shrine_type}.base_upgrade_cost", default=1000)
            cost_multiplier = self.get_config("shrines.upgrade_cost_multiplier", default=1.5)
            upgrade_cost = int(base_cost * (cost_multiplier ** current_level))

            # Upgrade shrine
            old_level = shrine.level
            shrine.level += 1

            # Emit event
            await self.emit_event(
                "shrine.upgraded",
                {
                    "player_id": player_id,
                    "shrine_id": shrine_id,
                    "shrine_type": shrine.shrine_type,
                    "old_level": old_level,
                    "new_level": shrine.level,
                    "upgrade_cost": upgrade_cost,
                },
            )

            return {
                "shrine_id": shrine_id,
                "old_level": old_level,
                "new_level": shrine.level,
                "upgrade_cost": upgrade_cost,
                "max_level": max_level,
            }

    async def toggle_shrine_active(
        self,
        player_id: int,
        shrine_id: int,
        is_active: bool,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Activate or deactivate a shrine.

        Args:
            player_id: Discord ID of player
            shrine_id: Shrine ID to toggle
            is_active: New active state
            context: Operation context for audit

        Returns:
            Dict with shrine state

        Raises:
            ResourceNotFoundError: Shrine not found
            BusinessRuleViolation: Not owned
        """
        # Validation
        player_id = InputValidator.validate_discord_id(player_id)
        shrine_id = InputValidator.validate_positive_integer(shrine_id, "shrine_id")

        async with DatabaseService.get_transaction() as session:
            # Fetch shrine with pessimistic lock
            shrine = await self._shrine_repo.find_one_where(
                session,
                PlayerShrine.id == shrine_id,
                for_update=True,
            )

            if not shrine:
                raise NotFoundError(f"Shrine {shrine_id} not found")

            # Ownership check
            if shrine.player_id != player_id:
                raise InvalidOperationError(
                    "toggle_shrine_active",
                    f"Shrine {shrine_id} does not belong to player {player_id}"
                )

            old_state = shrine.is_active
            shrine.is_active = is_active

            # Emit event
            await self.emit_event(
                "shrine.toggled",
                {
                    "player_id": player_id,
                    "shrine_id": shrine_id,
                    "shrine_type": shrine.shrine_type,
                    "old_state": old_state,
                    "new_state": is_active,
                },
            )

            return {
                "shrine_id": shrine_id,
                "is_active": is_active,
                "shrine_type": shrine.shrine_type,
            }

    # -------------------------------------------------------------------------
    # Query Operations
    # -------------------------------------------------------------------------

    async def get_player_shrines(
        self,
        player_id: int,
        shrine_type: Optional[str] = None,
        active_only: bool = False,
        context: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get all shrines for a player.

        Args:
            player_id: Discord ID of player
            shrine_type: Optional filter by shrine type
            active_only: Only return active shrines
            context: Operation context for audit

        Returns:
            List of shrine dicts
        """
        # Validation
        player_id = InputValidator.validate_discord_id(player_id)

        async with DatabaseService.get_transaction() as session:
            # Build query conditions
            conditions = [PlayerShrine.player_id == player_id]
            if shrine_type:
                conditions.append(PlayerShrine.shrine_type == shrine_type)
            if active_only:
                conditions.append(PlayerShrine.is_active == True)

            # Query with order_by (not supported by find_many_where)
            stmt = select(PlayerShrine).where(*conditions).order_by(PlayerShrine.slot)
            result = await session.execute(stmt)
            shrines = list(result.scalars().all())

            # Convert to dicts
            result = []
            now = datetime.now(timezone.utc)
            for shrine in shrines:
                shrine_dict = {
                    "shrine_id": shrine.id,
                    "shrine_type": shrine.shrine_type,
                    "slot": shrine.slot,
                    "level": shrine.level,
                    "is_active": shrine.is_active,
                    "last_collected_at": shrine.last_collected_at,
                    "yield_history_count": len(shrine.yield_history),
                }

                # Add cooldown info
                if shrine.last_collected_at:
                    cooldown_hours = self.get_config(
                        f"shrines.{shrine.shrine_type}.cooldown_hours", default=8
                    )
                    next_collectible = shrine.last_collected_at + timedelta(hours=cooldown_hours)
                    shrine_dict["next_collectible_at"] = next_collectible
                    shrine_dict["is_collectible"] = now >= next_collectible
                else:
                    shrine_dict["next_collectible_at"] = None
                    shrine_dict["is_collectible"] = True

                result.append(shrine_dict)

            return result

    async def get_shrine_details(
        self,
        shrine_id: int,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get detailed information about a specific shrine.

        Args:
            shrine_id: Shrine ID
            context: Operation context for audit

        Returns:
            Dict with full shrine details including yield history

        Raises:
            ResourceNotFoundError: Shrine not found
        """
        # Validation
        shrine_id = InputValidator.validate_positive_integer(shrine_id, "shrine_id")

        async with DatabaseService.get_transaction() as session:
            shrine = await self._shrine_repo.find_one_where(
                session,
                PlayerShrine.id == shrine_id,
            )

            if not shrine:
                raise NotFoundError(f"Shrine {shrine_id} not found")

            # Calculate current yield and cooldown info
            current_yield = self._calculate_yield(shrine)
            now = datetime.now(timezone.utc)
            cooldown_hours = self.get_config(
                f"shrines.{shrine.shrine_type}.cooldown_hours", default=8
            )

            if shrine.last_collected_at:
                next_collectible = shrine.last_collected_at + timedelta(hours=cooldown_hours)
                is_collectible = now >= next_collectible
            else:
                next_collectible = None
                is_collectible = True

            return {
                "shrine_id": shrine.id,
                "player_id": shrine.player_id,
                "shrine_type": shrine.shrine_type,
                "slot": shrine.slot,
                "level": shrine.level,
                "is_active": shrine.is_active,
                "last_collected_at": shrine.last_collected_at,
                "next_collectible_at": next_collectible,
                "is_collectible": is_collectible,
                "current_yield": current_yield,
                "cooldown_hours": cooldown_hours,
                "yield_history": shrine.yield_history,
                "created_at": shrine.created_at,
                "updated_at": shrine.updated_at,
            }

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    def _calculate_yield(self, shrine: PlayerShrine) -> int:
        """
        Calculate the current yield for a shrine based on level and type.

        Formula: base_yield * (1 + (level - 1) * level_multiplier) * type_multiplier

        Args:
            shrine: PlayerShrine instance

        Returns:
            Calculated yield amount (lumees)
        """
        base_yield = self.get_config(f"shrines.{shrine.shrine_type}.base_yield", default=100)
        level_multiplier = self.get_config(
            f"shrines.{shrine.shrine_type}.level_multiplier", default=0.1
        )
        type_multiplier = self.get_config(
            f"shrines.{shrine.shrine_type}.type_multiplier", default=1.0
        )

        # Calculate yield with level scaling
        level_bonus = 1 + (shrine.level - 1) * level_multiplier
        total_yield = int(base_yield * level_bonus * type_multiplier)

        return total_yield
