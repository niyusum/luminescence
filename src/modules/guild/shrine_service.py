"""
GuildShrineService - Business logic for guild shrine management
===============================================================

Handles:
- Guild shrine yield calculation with collective bonuses
- Guild shrine collection routing to guild treasury
- Guild shrine upgrades with guild fund management
- Guild shrine activation/deactivation
- Yield history tracking for guild shrines

All operations follow LUMEN LAW (2025):
- Pure business logic, no Discord/UI concerns
- Config-driven yield formulas and guild bonuses
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
from src.database.models.economy.guild_shrine import GuildShrine

if TYPE_CHECKING:
    from logging import Logger
    from src.core.config.manager import ConfigManager
    from src.core.event.bus import EventBus


class GuildShrineService(BaseService):
    """
    GuildShrineService handles all guild shrine operations.

    Business Logic:
    - Yield calculation: base_yield * level_multiplier * guild_member_bonus
    - Cooldown enforcement: must wait cooldown_hours before collection
    - Treasury routing: yields go to guild treasury, not individual collector
    - Upgrade validation: cost deducted from guild funds
    - Ring buffer: maintain last N collection records in yield_history
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        event_bus: EventBus,
        logger: Logger,
    ):
        """Initialize GuildShrineService with GuildShrine repository."""
        super().__init__(config_manager, event_bus, logger)
        self._guild_shrine_repo = BaseRepository[GuildShrine](GuildShrine, self.log)

    # -------------------------------------------------------------------------
    # Core Operations
    # -------------------------------------------------------------------------

    async def create_guild_shrine(
        self,
        guild_id: int,
        shrine_type: str,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new guild shrine.

        Args:
            guild_id: Guild ID
            shrine_type: Type of shrine (e.g., 'lesser', 'radiant')
            context: Operation context for audit

        Returns:
            Dict with shrine data

        Raises:
            ValidationError: Invalid parameters
            InvalidOperationError: Shrine already exists for this type
        """
        # Validation
        guild_id = InputValidator.validate_positive_integer(guild_id, "guild_id")
        shrine_type = InputValidator.validate_string(shrine_type, "shrine_type", min_length=1)

        # Get config
        starting_level = self.get_config("guild_shrines.starting_level", default=1)

        async with DatabaseService.get_transaction() as session:
            # Check if shrine already exists for this type
            existing = await self._guild_shrine_repo.find_one_where(
                session,
                GuildShrine.guild_id == guild_id,
                GuildShrine.shrine_type == shrine_type,
            )

            if existing:
                raise InvalidOperationError(
                    "create_guild_shrine",
                    f"Guild shrine type '{shrine_type}' already exists for guild {guild_id}"
                )

            # Create shrine
            shrine = GuildShrine(
                guild_id=guild_id,
                shrine_type=shrine_type,
                level=starting_level,
                is_active=True,
                last_collected_at=None,
                yield_history=[],
            )

            session.add(shrine)
            await session.flush()

            # Emit event
            await self.emit_event(
                "guild_shrine.created",
                {
                    "guild_id": guild_id,
                    "shrine_id": shrine.id,
                    "shrine_type": shrine_type,
                    "level": starting_level,
                },
            )

            return {
                "shrine_id": shrine.id,
                "guild_id": guild_id,
                "shrine_type": shrine_type,
                "level": starting_level,
                "is_active": True,
                "created_at": shrine.created_at,
            }

    async def collect_guild_shrine_yield(
        self,
        guild_id: int,
        shrine_id: int,
        collector_id: int,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Collect yield from a guild shrine and route to guild treasury.

        Args:
            guild_id: Guild ID
            shrine_id: Shrine ID to collect from
            collector_id: Discord ID of member collecting
            context: Operation context for audit

        Returns:
            Dict with collection results (lumees_to_treasury, next_collectible_at)

        Raises:
            NotFoundError: Shrine not found
            InvalidOperationError: Cooldown active, shrine inactive, wrong guild
        """
        # Validation
        guild_id = InputValidator.validate_positive_integer(guild_id, "guild_id")
        shrine_id = InputValidator.validate_positive_integer(shrine_id, "shrine_id")
        collector_id = InputValidator.validate_discord_id(collector_id)

        async with DatabaseService.get_transaction() as session:
            # Fetch shrine with pessimistic lock
            shrine = await self._guild_shrine_repo.find_one_where(
                session,
                GuildShrine.id == shrine_id,
                for_update=True,
            )

            if not shrine:
                raise NotFoundError(f"Guild shrine {shrine_id} not found")

            # Guild ownership check
            if shrine.guild_id != guild_id:
                raise InvalidOperationError(
                    "collect_guild_shrine_yield",
                    f"Guild shrine {shrine_id} does not belong to guild {guild_id}"
                )

            # Active check
            if not shrine.is_active:
                raise InvalidOperationError(
                    "collect_guild_shrine_yield",
                    f"Guild shrine {shrine_id} is not active and cannot be collected"
                )

            # Cooldown check
            now = datetime.now(timezone.utc)
            cooldown_hours = self.get_config(
                f"guild_shrines.{shrine.shrine_type}.cooldown_hours", default=12
            )

            if shrine.last_collected_at:
                next_collectible = shrine.last_collected_at + timedelta(hours=cooldown_hours)
                if now < next_collectible:
                    time_remaining = next_collectible - now
                    raise InvalidOperationError(
                        "collect_guild_shrine_yield",
                        f"Guild shrine cooldown active. Time remaining: {time_remaining}"
                    )

            # Calculate yield (includes guild member count bonus)
            yield_amount = await self._calculate_guild_yield(session, shrine, guild_id)

            # Update shrine state
            shrine.last_collected_at = now

            # Update yield history (ring buffer - keep last 100 collections)
            max_history = self.get_config("guild_shrines.max_yield_history", default=100)
            shrine.yield_history.append(
                {
                    "collected_at": now.isoformat(),
                    "amount": yield_amount,
                    "level": shrine.level,
                    "collector_id": collector_id,
                }
            )
            if len(shrine.yield_history) > max_history:
                shrine.yield_history = shrine.yield_history[-max_history:]
            flag_modified(shrine, "yield_history")

            # Calculate next collectible time
            next_collectible_at = now + timedelta(hours=cooldown_hours)

            # Emit event (treasury routing handled by listener)
            await self.emit_event(
                "guild_shrine.collected",
                {
                    "guild_id": guild_id,
                    "shrine_id": shrine_id,
                    "shrine_type": shrine.shrine_type,
                    "yield_amount": yield_amount,
                    "level": shrine.level,
                    "collector_id": collector_id,
                    "collected_at": now.isoformat(),
                },
            )

            return {
                "shrine_id": shrine_id,
                "yield_to_treasury": yield_amount,
                "level": shrine.level,
                "collected_by": collector_id,
                "collected_at": now,
                "next_collectible_at": next_collectible_at,
                "cooldown_hours": cooldown_hours,
            }

    async def upgrade_guild_shrine(
        self,
        guild_id: int,
        shrine_id: int,
        upgrader_id: int,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Upgrade a guild shrine to the next level.

        Args:
            guild_id: Guild ID
            shrine_id: Shrine ID to upgrade
            upgrader_id: Discord ID of member upgrading
            context: Operation context for audit

        Returns:
            Dict with upgrade results (new_level, upgrade_cost)

        Raises:
            NotFoundError: Shrine not found
            InvalidOperationError: Max level reached, wrong guild
        """
        # Validation
        guild_id = InputValidator.validate_positive_integer(guild_id, "guild_id")
        shrine_id = InputValidator.validate_positive_integer(shrine_id, "shrine_id")
        upgrader_id = InputValidator.validate_discord_id(upgrader_id)

        async with DatabaseService.get_transaction() as session:
            # Fetch shrine with pessimistic lock
            shrine = await self._guild_shrine_repo.find_one_where(
                session,
                GuildShrine.id == shrine_id,
                for_update=True,
            )

            if not shrine:
                raise NotFoundError(f"Guild shrine {shrine_id} not found")

            # Guild ownership check
            if shrine.guild_id != guild_id:
                raise InvalidOperationError(
                    "upgrade_guild_shrine",
                    f"Guild shrine {shrine_id} does not belong to guild {guild_id}"
                )

            # Max level check
            max_level = self.get_config(
                f"guild_shrines.{shrine.shrine_type}.max_level", default=20
            )
            if shrine.level >= max_level:
                raise InvalidOperationError(
                    "upgrade_guild_shrine",
                    f"Guild shrine {shrine_id} is already at max level ({max_level})"
                )

            # Calculate upgrade cost (exponential scaling)
            current_level = shrine.level
            base_cost = self.get_config(
                f"guild_shrines.{shrine.shrine_type}.base_upgrade_cost", default=5000
            )
            cost_multiplier = self.get_config("guild_shrines.upgrade_cost_multiplier", default=1.8)
            upgrade_cost = int(base_cost * (cost_multiplier ** current_level))

            # Upgrade shrine
            old_level = shrine.level
            shrine.level += 1

            # Emit event (guild fund deduction handled by listener)
            await self.emit_event(
                "guild_shrine.upgraded",
                {
                    "guild_id": guild_id,
                    "shrine_id": shrine_id,
                    "shrine_type": shrine.shrine_type,
                    "old_level": old_level,
                    "new_level": shrine.level,
                    "upgrade_cost": upgrade_cost,
                    "upgrader_id": upgrader_id,
                },
            )

            return {
                "shrine_id": shrine_id,
                "old_level": old_level,
                "new_level": shrine.level,
                "upgrade_cost": upgrade_cost,
                "max_level": max_level,
            }

    async def toggle_guild_shrine_active(
        self,
        guild_id: int,
        shrine_id: int,
        is_active: bool,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Activate or deactivate a guild shrine.

        Args:
            guild_id: Guild ID
            shrine_id: Shrine ID to toggle
            is_active: New active state
            context: Operation context for audit

        Returns:
            Dict with shrine state

        Raises:
            NotFoundError: Shrine not found
            InvalidOperationError: Wrong guild
        """
        # Validation
        guild_id = InputValidator.validate_positive_integer(guild_id, "guild_id")
        shrine_id = InputValidator.validate_positive_integer(shrine_id, "shrine_id")

        async with DatabaseService.get_transaction() as session:
            # Fetch shrine with pessimistic lock
            shrine = await self._guild_shrine_repo.find_one_where(
                session,
                GuildShrine.id == shrine_id,
                for_update=True,
            )

            if not shrine:
                raise NotFoundError(f"Guild shrine {shrine_id} not found")

            # Guild ownership check
            if shrine.guild_id != guild_id:
                raise InvalidOperationError(
                    "toggle_guild_shrine_active",
                    f"Guild shrine {shrine_id} does not belong to guild {guild_id}"
                )

            old_state = shrine.is_active
            shrine.is_active = is_active

            # Emit event
            await self.emit_event(
                "guild_shrine.toggled",
                {
                    "guild_id": guild_id,
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

    async def get_guild_shrines(
        self,
        guild_id: int,
        shrine_type: Optional[str] = None,
        active_only: bool = False,
        context: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get all shrines for a guild.

        Args:
            guild_id: Guild ID
            shrine_type: Optional filter by shrine type
            active_only: Only return active shrines
            context: Operation context for audit

        Returns:
            List of shrine dicts
        """
        # Validation
        guild_id = InputValidator.validate_positive_integer(guild_id, "guild_id")

        async with DatabaseService.get_transaction() as session:
            # Build query conditions
            conditions = [GuildShrine.guild_id == guild_id]
            if shrine_type:
                conditions.append(GuildShrine.shrine_type == shrine_type)
            if active_only:
                conditions.append(GuildShrine.is_active == True)

            # Query with order_by (not supported by find_many_where)
            stmt = select(GuildShrine).where(*conditions).order_by(GuildShrine.shrine_type)
            result = await session.execute(stmt)
            shrines = list(result.scalars().all())

            # Convert to dicts
            result = []
            now = datetime.now(timezone.utc)
            for shrine in shrines:
                shrine_dict = {
                    "shrine_id": shrine.id,
                    "shrine_type": shrine.shrine_type,
                    "level": shrine.level,
                    "is_active": shrine.is_active,
                    "last_collected_at": shrine.last_collected_at,
                    "yield_history_count": len(shrine.yield_history),
                }

                # Add cooldown info
                if shrine.last_collected_at:
                    cooldown_hours = self.get_config(
                        f"guild_shrines.{shrine.shrine_type}.cooldown_hours", default=12
                    )
                    next_collectible = shrine.last_collected_at + timedelta(hours=cooldown_hours)
                    shrine_dict["next_collectible_at"] = next_collectible
                    shrine_dict["is_collectible"] = now >= next_collectible
                else:
                    shrine_dict["next_collectible_at"] = None
                    shrine_dict["is_collectible"] = True

                result.append(shrine_dict)

            return result

    async def get_guild_shrine_details(
        self,
        shrine_id: int,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get detailed information about a specific guild shrine.

        Args:
            shrine_id: Shrine ID
            context: Operation context for audit

        Returns:
            Dict with full shrine details including yield history

        Raises:
            NotFoundError: Shrine not found
        """
        # Validation
        shrine_id = InputValidator.validate_positive_integer(shrine_id, "shrine_id")

        async with DatabaseService.get_transaction() as session:
            shrine = await self._guild_shrine_repo.find_one_where(
                session,
                GuildShrine.id == shrine_id,
            )

            if not shrine:
                raise NotFoundError(f"Guild shrine {shrine_id} not found")

            # Calculate current yield and cooldown info
            current_yield = await self._calculate_guild_yield(session, shrine, shrine.guild_id)
            now = datetime.now(timezone.utc)
            cooldown_hours = self.get_config(
                f"guild_shrines.{shrine.shrine_type}.cooldown_hours", default=12
            )

            if shrine.last_collected_at:
                next_collectible = shrine.last_collected_at + timedelta(hours=cooldown_hours)
                is_collectible = now >= next_collectible
            else:
                next_collectible = None
                is_collectible = True

            return {
                "shrine_id": shrine.id,
                "guild_id": shrine.guild_id,
                "shrine_type": shrine.shrine_type,
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

    async def _calculate_guild_yield(
        self, session, shrine: GuildShrine, guild_id: int
    ) -> int:
        """
        Calculate the current yield for a guild shrine based on level and member count.

        Formula: base_yield * (1 + (level - 1) * level_multiplier) * (1 + member_count * member_bonus)

        Args:
            session: Database session
            shrine: GuildShrine instance
            guild_id: Guild ID for member count lookup

        Returns:
            Calculated yield amount (lumees)
        """
        base_yield = self.get_config(
            f"guild_shrines.{shrine.shrine_type}.base_yield", default=500
        )
        level_multiplier = self.get_config(
            f"guild_shrines.{shrine.shrine_type}.level_multiplier", default=0.15
        )
        member_bonus = self.get_config(
            "guild_shrines.member_bonus_per_member", default=0.02
        )

        # Get guild member count (optional - may not have guild service yet)
        # For now, use a default or fetch from guild_members table
        from sqlalchemy import func
        from src.database.models.social.guild_member import GuildMember

        member_count_result = await session.execute(
            select(func.count(GuildMember.id)).where(GuildMember.guild_id == guild_id)
        )
        member_count = member_count_result.scalar() or 1  # Default to 1 if no members found

        # Calculate yield with level and member scaling
        level_bonus = 1 + (shrine.level - 1) * level_multiplier
        member_multiplier = 1 + (member_count * member_bonus)
        total_yield = int(base_yield * level_bonus * member_multiplier)

        return total_yield
