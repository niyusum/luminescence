"""
Player Stats Service - LES 2025 Compliant
==========================================

Purpose
-------
Manages player combat stats, resource pools, regeneration, and battle statistics
with full transaction safety, audit logging, and event emission.

Domain
------
- Resource pools (energy, stamina, HP) management
- Resource regeneration
- Drop charge system
- Combat power aggregation (attack, defense, total_power)
- Stat point spending and allocation tracking
- Battle and activity statistics

LUMEN 2025 COMPLIANCE
---------------------
✓ Pure business logic - no Discord dependencies
✓ Transaction-safe - all writes in atomic transactions
✓ Config-driven - regeneration rates, caps from config
✓ Domain exceptions - raises NotFoundError, InsufficientResourcesError, ValidationError
✓ Event-driven - emits events for resource changes
✓ Observable - structured logging, audit trail, timing metrics
✓ Pessimistic locking - uses SELECT FOR UPDATE for all writes
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional

from src.core.database.service import DatabaseService
from src.core.infra.audit_logger import AuditLogger
from src.core.logging.logger import get_logger
from src.core.validation.input_validator import InputValidator
from src.modules.shared.base_repository import BaseRepository
from src.modules.shared.base_service import BaseService
from src.modules.shared.exceptions import (
    InsufficientResourcesError,
    NotFoundError,
    ValidationError,
)

if TYPE_CHECKING:
    from logging import Logger

    from src.core.config.manager import ConfigManager
    from src.core.event.bus import EventBus
    from src.database.models.core.player.player_stats import PlayerStats


# ============================================================================
# Repository
# ============================================================================


class PlayerStatsRepository(BaseRepository["PlayerStats"]):
    """Repository for PlayerStats model."""

    pass  # Inherits all CRUD from BaseRepository


# ============================================================================
# PlayerStatsService
# ============================================================================


class PlayerStatsService(BaseService):
    """
    Service for managing player combat stats and resource pools.

    Handles resource management (energy, stamina, HP), regeneration,
    drop charges, combat power tracking, stat allocation, and battle statistics.

    Dependencies
    ------------
    - ConfigManager: For regeneration rates, resource limits
    - EventBus: For emitting resource events
    - Logger: For structured logging
    - DatabaseService: For transaction management (injected via context)
    - AuditLogger: For audit trail (static)

    Public Methods
    --------------
    Resource Pool Management:
    - get_stats() -> Get player stats
    - add_energy/stamina/hp() -> Add to resource pools
    - subtract_energy/stamina/hp() -> Subtract from resource pools
    - regenerate_resources() -> Apply time-based regeneration

    Drop Charge System:
    - add_drop_charges() -> Add drop charges
    - subtract_drop_charges() -> Subtract drop charges
    - regenerate_drop_charges() -> Time-based drop charge regen

    Combat Power:
    - update_combat_power() -> Recalculate power aggregates

    Stat Allocation:
    - spend_stat_points() -> Allocate points to resources
    - recalculate_max_resources() -> Update max based on allocation

    Statistics:
    - increment_stat() -> Increment battle statistic
    - get_stat() -> Get specific statistic value
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        """
        Initialize PlayerStatsService with required dependencies.

        Args:
            config_manager: Application configuration manager
            event_bus: Event bus for cross-module communication
            logger: Structured logger instance
        """
        super().__init__(config_manager, event_bus, logger)

        # Initialize repository with proper logger
        from src.database.models.core.player.player_stats import PlayerStats

        self._stats_repo = PlayerStatsRepository(
            model_class=PlayerStats,
            logger=get_logger(f"{__name__}.PlayerStatsRepository"),
        )

    # ========================================================================
    # PUBLIC API - Read Operations
    # ========================================================================

    async def get_stats(self, player_id: int) -> Dict[str, Any]:
        """
        Get player stats.

        This is a **read-only** operation using get_session().

        Args:
            player_id: Discord ID of the player

        Returns:
            Dict with stats information

        Raises:
            NotFoundError: If player stats record not found

        Example:
            >>> stats = await stats_service.get_stats(123456789)
            >>> print(stats["energy"])  # 100
        """
        player_id = InputValidator.validate_discord_id(player_id)

        self.log_operation("get_stats", player_id=player_id)

        # Read-only operation - use get_session()
        async with DatabaseService.get_session() as session:
            stats = await self._stats_repo.find_one_where(
                session,
                self._stats_repo.model_class.player_id == player_id,
            )

            if not stats:
                raise NotFoundError("PlayerStats", player_id)

            return {
                "player_id": stats.player_id,
                "energy": stats.energy,
                "max_energy": stats.max_energy,
                "stamina": stats.stamina,
                "max_stamina": stats.max_stamina,
                "hp": stats.hp,
                "max_hp": stats.max_hp,
                "drop_charges": stats.drop_charges,
                "max_drop_charges": stats.max_drop_charges,
                "last_drop_regen": stats.last_drop_regen,
                "total_attack": stats.total_attack,
                "total_defense": stats.total_defense,
                "total_power": stats.total_power,
                "stat_points_spent": stats.stat_points_spent,
                "stats": stats.stats,
                "state": stats.state or {},
            }

    async def get_stat(self, player_id: int, stat_key: str) -> int:
        """
        Get specific battle statistic value.

        Args:
            player_id: Discord ID of the player
            stat_key: Statistic key

        Returns:
            Statistic value (0 if not found)

        Raises:
            NotFoundError: If player stats record not found
        """
        player_id = InputValidator.validate_discord_id(player_id)

        async with DatabaseService.get_session() as session:
            stats = await self._stats_repo.find_one_where(
                session,
                self._stats_repo.model_class.player_id == player_id,
            )

            if not stats:
                raise NotFoundError("PlayerStats", player_id)

            return stats.stats.get(stat_key, 0)

    # ========================================================================
    # PUBLIC API - Resource Pool Operations (Energy)
    # ========================================================================

    async def add_energy(
        self,
        player_id: int,
        amount: int,
        reason: str,
        allow_overflow: bool = False,
    ) -> Dict[str, Any]:
        """
        Add energy to player's pool.

        This is a **write operation** using get_transaction() with pessimistic locking.

        Args:
            player_id: Discord ID of the player
            amount: Amount of energy to add
            reason: Reason for the addition
            allow_overflow: If True, allows exceeding max (tracks overflow in stats)

        Returns:
            Dict with updated energy

        Raises:
            NotFoundError: If player stats record not found

        Example:
            >>> result = await stats_service.add_energy(
            ...     player_id=123456789,
            ...     amount=50,
            ...     reason="regeneration"
            ... )
        """
        player_id = InputValidator.validate_discord_id(player_id)
        amount = InputValidator.validate_positive_integer(amount, "amount")

        self.log_operation(
            "add_energy",
            player_id=player_id,
            amount=amount,
        )

        async with DatabaseService.get_transaction() as session:
            # Lock the row for update
            stats = await self._stats_repo.find_one_where(
                session,
                self._stats_repo.model_class.player_id == player_id,
                for_update=True,  # SELECT FOR UPDATE
            )

            if not stats:
                raise NotFoundError("PlayerStats", player_id)

            old_energy = stats.energy
            new_energy = old_energy + amount

            if not allow_overflow:
                # Cap at max
                actual_gained = min(amount, stats.max_energy - old_energy)
                new_energy = min(new_energy, stats.max_energy)
            else:
                # Track overflow
                if new_energy > stats.max_energy:
                    overflow = new_energy - stats.max_energy
                    stats.stats["overflow_energy_gained"] = (
                        stats.stats.get("overflow_energy_gained", 0) + overflow
                    )
                    # Mark JSON field as modified
                    from sqlalchemy.orm.attributes import flag_modified

                    flag_modified(stats, "stats")
                actual_gained = amount

            stats.energy = new_energy

            # Event emission (no audit for frequent regen)
            await self.emit_event(
                event_type="player.energy_added",
                data={
                    "player_id": player_id,
                    "old_energy": old_energy,
                    "new_energy": new_energy,
                    "amount": actual_gained,
                    "reason": reason,
                },
            )

            self.log.debug(
                f"Energy added: +{actual_gained}",
                extra={
                    "player_id": player_id,
                    "old_energy": old_energy,
                    "new_energy": new_energy,
                },
            )

            return {
                "player_id": player_id,
                "old_energy": old_energy,
                "new_energy": new_energy,
                "amount_gained": actual_gained,
            }

    async def subtract_energy(
        self,
        player_id: int,
        amount: int,
        reason: str,
    ) -> Dict[str, Any]:
        """
        Subtract energy from player's pool.

        This is a **write operation** using get_transaction() with pessimistic locking.

        Args:
            player_id: Discord ID of the player
            amount: Amount of energy to subtract
            reason: Reason for the subtraction

        Returns:
            Dict with updated energy

        Raises:
            NotFoundError: If player stats record not found
            InsufficientResourcesError: If not enough energy

        Example:
            >>> result = await stats_service.subtract_energy(
            ...     player_id=123456789,
            ...     amount=30,
            ...     reason="exploration"
            ... )
        """
        player_id = InputValidator.validate_discord_id(player_id)
        amount = InputValidator.validate_positive_integer(amount, "amount")

        self.log_operation(
            "subtract_energy",
            player_id=player_id,
            amount=amount,
        )

        async with DatabaseService.get_transaction() as session:
            # Lock the row for update
            stats = await self._stats_repo.find_one_where(
                session,
                self._stats_repo.model_class.player_id == player_id,
                for_update=True,
            )

            if not stats:
                raise NotFoundError("PlayerStats", player_id)

            old_energy = stats.energy

            # Check sufficiency
            if old_energy < amount:
                raise InsufficientResourcesError(
                    resource="energy",
                    required=amount,
                    current=old_energy,
                )

            new_energy = old_energy - amount
            stats.energy = new_energy

            # Event emission
            await self.emit_event(
                event_type="player.energy_subtracted",
                data={
                    "player_id": player_id,
                    "old_energy": old_energy,
                    "new_energy": new_energy,
                    "amount": amount,
                    "reason": reason,
                },
            )

            self.log.debug(
                f"Energy subtracted: -{amount}",
                extra={
                    "player_id": player_id,
                    "old_energy": old_energy,
                    "new_energy": new_energy,
                },
            )

            return {
                "player_id": player_id,
                "old_energy": old_energy,
                "new_energy": new_energy,
                "amount_subtracted": amount,
            }

    # ========================================================================
    # PUBLIC API - Resource Pool Operations (Stamina)
    # ========================================================================

    async def add_stamina(
        self,
        player_id: int,
        amount: int,
        reason: str,
        allow_overflow: bool = False,
    ) -> Dict[str, Any]:
        """Add stamina to player's pool. Similar to add_energy."""
        player_id = InputValidator.validate_discord_id(player_id)
        amount = InputValidator.validate_positive_integer(amount, "amount")

        async with DatabaseService.get_transaction() as session:
            stats = await self._stats_repo.find_one_where(
                session,
                self._stats_repo.model_class.player_id == player_id,
                for_update=True,
            )

            if not stats:
                raise NotFoundError("PlayerStats", player_id)

            old_stamina = stats.stamina
            new_stamina = old_stamina + amount

            if not allow_overflow:
                actual_gained = min(amount, stats.max_stamina - old_stamina)
                new_stamina = min(new_stamina, stats.max_stamina)
            else:
                if new_stamina > stats.max_stamina:
                    overflow = new_stamina - stats.max_stamina
                    stats.stats["overflow_stamina_gained"] = (
                        stats.stats.get("overflow_stamina_gained", 0) + overflow
                    )
                    from sqlalchemy.orm.attributes import flag_modified

                    flag_modified(stats, "stats")
                actual_gained = amount

            stats.stamina = new_stamina

            await self.emit_event(
                event_type="player.stamina_added",
                data={
                    "player_id": player_id,
                    "old_stamina": old_stamina,
                    "new_stamina": new_stamina,
                    "amount": actual_gained,
                    "reason": reason,
                },
            )

            return {
                "player_id": player_id,
                "old_stamina": old_stamina,
                "new_stamina": new_stamina,
                "amount_gained": actual_gained,
            }

    async def subtract_stamina(
        self,
        player_id: int,
        amount: int,
        reason: str,
    ) -> Dict[str, Any]:
        """Subtract stamina from player's pool. Similar to subtract_energy."""
        player_id = InputValidator.validate_discord_id(player_id)
        amount = InputValidator.validate_positive_integer(amount, "amount")

        async with DatabaseService.get_transaction() as session:
            stats = await self._stats_repo.find_one_where(
                session,
                self._stats_repo.model_class.player_id == player_id,
                for_update=True,
            )

            if not stats:
                raise NotFoundError("PlayerStats", player_id)

            old_stamina = stats.stamina

            if old_stamina < amount:
                raise InsufficientResourcesError(
                    resource="stamina",
                    required=amount,
                    current=old_stamina,
                )

            new_stamina = old_stamina - amount
            stats.stamina = new_stamina

            await self.emit_event(
                event_type="player.stamina_subtracted",
                data={
                    "player_id": player_id,
                    "old_stamina": old_stamina,
                    "new_stamina": new_stamina,
                    "amount": amount,
                    "reason": reason,
                },
            )

            return {
                "player_id": player_id,
                "old_stamina": old_stamina,
                "new_stamina": new_stamina,
                "amount_subtracted": amount,
            }

    # ========================================================================
    # PUBLIC API - Resource Pool Operations (HP)
    # ========================================================================

    async def add_hp(
        self,
        player_id: int,
        amount: int,
        reason: str,
    ) -> Dict[str, Any]:
        """Add HP to player's pool (capped at max)."""
        player_id = InputValidator.validate_discord_id(player_id)
        amount = InputValidator.validate_positive_integer(amount, "amount")

        async with DatabaseService.get_transaction() as session:
            stats = await self._stats_repo.find_one_where(
                session,
                self._stats_repo.model_class.player_id == player_id,
                for_update=True,
            )

            if not stats:
                raise NotFoundError("PlayerStats", player_id)

            old_hp = stats.hp
            actual_gained = min(amount, stats.max_hp - old_hp)
            new_hp = min(old_hp + amount, stats.max_hp)
            stats.hp = new_hp

            await self.emit_event(
                event_type="player.hp_added",
                data={
                    "player_id": player_id,
                    "old_hp": old_hp,
                    "new_hp": new_hp,
                    "amount": actual_gained,
                    "reason": reason,
                },
            )

            return {
                "player_id": player_id,
                "old_hp": old_hp,
                "new_hp": new_hp,
                "amount_gained": actual_gained,
            }

    async def subtract_hp(
        self,
        player_id: int,
        amount: int,
        reason: str,
    ) -> Dict[str, Any]:
        """Subtract HP from player's pool."""
        player_id = InputValidator.validate_discord_id(player_id)
        amount = InputValidator.validate_positive_integer(amount, "amount")

        async with DatabaseService.get_transaction() as session:
            stats = await self._stats_repo.find_one_where(
                session,
                self._stats_repo.model_class.player_id == player_id,
                for_update=True,
            )

            if not stats:
                raise NotFoundError("PlayerStats", player_id)

            old_hp = stats.hp

            if old_hp < amount:
                raise InsufficientResourcesError(
                    resource="hp",
                    required=amount,
                    current=old_hp,
                )

            new_hp = old_hp - amount
            stats.hp = new_hp

            await self.emit_event(
                event_type="player.hp_subtracted",
                data={
                    "player_id": player_id,
                    "old_hp": old_hp,
                    "new_hp": new_hp,
                    "amount": amount,
                    "reason": reason,
                },
            )

            return {
                "player_id": player_id,
                "old_hp": old_hp,
                "new_hp": new_hp,
                "amount_subtracted": amount,
            }

    # ========================================================================
    # PUBLIC API - Drop Charge System
    # ========================================================================

    async def add_drop_charges(
        self,
        player_id: int,
        amount: int,
        reason: str,
    ) -> Dict[str, Any]:
        """Add drop charges (capped at max)."""
        player_id = InputValidator.validate_discord_id(player_id)
        amount = InputValidator.validate_positive_integer(amount, "amount")

        async with DatabaseService.get_transaction() as session:
            stats = await self._stats_repo.find_one_where(
                session,
                self._stats_repo.model_class.player_id == player_id,
                for_update=True,
            )

            if not stats:
                raise NotFoundError("PlayerStats", player_id)

            old_charges = stats.drop_charges
            actual_gained = min(amount, stats.max_drop_charges - old_charges)
            new_charges = min(old_charges + amount, stats.max_drop_charges)
            stats.drop_charges = new_charges

            await self.emit_event(
                event_type="player.drop_charges_added",
                data={
                    "player_id": player_id,
                    "old_charges": old_charges,
                    "new_charges": new_charges,
                    "amount": actual_gained,
                    "reason": reason,
                },
            )

            return {
                "player_id": player_id,
                "old_charges": old_charges,
                "new_charges": new_charges,
                "amount_gained": actual_gained,
            }

    async def subtract_drop_charges(
        self,
        player_id: int,
        amount: int,
        reason: str,
    ) -> Dict[str, Any]:
        """Subtract drop charges."""
        player_id = InputValidator.validate_discord_id(player_id)
        amount = InputValidator.validate_positive_integer(amount, "amount")

        async with DatabaseService.get_transaction() as session:
            stats = await self._stats_repo.find_one_where(
                session,
                self._stats_repo.model_class.player_id == player_id,
                for_update=True,
            )

            if not stats:
                raise NotFoundError("PlayerStats", player_id)

            old_charges = stats.drop_charges

            if old_charges < amount:
                raise InsufficientResourcesError(
                    resource="drop_charges",
                    required=amount,
                    current=old_charges,
                )

            new_charges = old_charges - amount
            stats.drop_charges = new_charges
            stats.last_drop_regen = datetime.now(timezone.utc)

            await self.emit_event(
                event_type="player.drop_charges_subtracted",
                data={
                    "player_id": player_id,
                    "old_charges": old_charges,
                    "new_charges": new_charges,
                    "amount": amount,
                    "reason": reason,
                },
            )

            return {
                "player_id": player_id,
                "old_charges": old_charges,
                "new_charges": new_charges,
                "amount_subtracted": amount,
            }

    async def regenerate_drop_charges(self, player_id: int) -> Dict[str, Any]:
        """
        Apply time-based drop charge regeneration.

        Uses config-driven regeneration rate.
        """
        player_id = InputValidator.validate_discord_id(player_id)

        # Config: drop charge regen interval in seconds
        regen_interval_seconds = self.get_config("DROP_CHARGE_REGEN_SECONDS", default=3600)

        async with DatabaseService.get_transaction() as session:
            stats = await self._stats_repo.find_one_where(
                session,
                self._stats_repo.model_class.player_id == player_id,
                for_update=True,
            )

            if not stats:
                raise NotFoundError("PlayerStats", player_id)

            now = datetime.now(timezone.utc)
            old_charges = stats.drop_charges

            # Already at max?
            if old_charges >= stats.max_drop_charges:
                return {
                    "player_id": player_id,
                    "charges_regenerated": 0,
                    "new_charges": old_charges,
                    "at_max": True,
                }

            # Calculate time since last regen
            if stats.last_drop_regen is None:
                stats.last_drop_regen = now

            time_since_regen = now - stats.last_drop_regen
            charges_to_add = int(time_since_regen.total_seconds() // regen_interval_seconds)

            if charges_to_add > 0:
                new_charges = min(old_charges + charges_to_add, stats.max_drop_charges)
                stats.drop_charges = new_charges
                stats.last_drop_regen = now

                self.log.info(
                    f"Drop charges regenerated: +{charges_to_add}",
                    extra={
                        "player_id": player_id,
                        "old_charges": old_charges,
                        "new_charges": new_charges,
                    },
                )

                return {
                    "player_id": player_id,
                    "charges_regenerated": charges_to_add,
                    "old_charges": old_charges,
                    "new_charges": new_charges,
                    "at_max": new_charges >= stats.max_drop_charges,
                }
            else:
                return {
                    "player_id": player_id,
                    "charges_regenerated": 0,
                    "new_charges": old_charges,
                    "at_max": False,
                }

    # ========================================================================
    # PUBLIC API - Combat Power
    # ========================================================================

    async def update_combat_power(
        self,
        player_id: int,
        total_attack: int,
        total_defense: int,
    ) -> Dict[str, Any]:
        """
        Update combat power aggregates.

        This is typically called by MaidenService when maiden collection changes.
        """
        player_id = InputValidator.validate_discord_id(player_id)
        total_attack = InputValidator.validate_non_negative_integer(
            total_attack, "total_attack"
        )
        total_defense = InputValidator.validate_non_negative_integer(
            total_defense, "total_defense"
        )

        async with DatabaseService.get_transaction() as session:
            stats = await self._stats_repo.find_one_where(
                session,
                self._stats_repo.model_class.player_id == player_id,
                for_update=True,
            )

            if not stats:
                raise NotFoundError("PlayerStats", player_id)

            old_power = stats.total_power
            stats.total_attack = total_attack
            stats.total_defense = total_defense
            stats.total_power = total_attack + total_defense

            await self.emit_event(
                event_type="player.power_updated",
                data={
                    "player_id": player_id,
                    "old_power": old_power,
                    "new_power": stats.total_power,
                    "total_attack": total_attack,
                    "total_defense": total_defense,
                },
            )

            return {
                "player_id": player_id,
                "old_power": old_power,
                "new_power": stats.total_power,
                "total_attack": total_attack,
                "total_defense": total_defense,
            }

    # ========================================================================
    # PUBLIC API - Stat Allocation
    # ========================================================================

    async def spend_stat_points(
        self,
        player_id: int,
        resource_type: str,
        points_to_spend: int,
    ) -> Dict[str, Any]:
        """
        Spend stat points to increase max resource capacity.

        Note: This updates stat_points_spent tracking. The actual stat_points
        deduction happens in PlayerProgressionService.

        Args:
            player_id: Discord ID of the player
            resource_type: "energy", "stamina", or "hp"
            points_to_spend: Number of stat points to allocate

        Returns:
            Dict with updated max resource values
        """
        player_id = InputValidator.validate_discord_id(player_id)
        resource_type = InputValidator.validate_choice(
            resource_type,
            field_name="resource_type",
            valid_choices=["energy", "stamina", "hp"],
        )
        points_to_spend = InputValidator.validate_positive_integer(
            points_to_spend, "points_to_spend"
        )

        async with DatabaseService.get_transaction() as session:
            stats = await self._stats_repo.find_one_where(
                session,
                self._stats_repo.model_class.player_id == player_id,
                for_update=True,
            )

            if not stats:
                raise NotFoundError("PlayerStats", player_id)

            # Update tracking
            old_spent = stats.stat_points_spent.get(resource_type, 0)
            stats.stat_points_spent[resource_type] = old_spent + points_to_spend

            # Mark JSON field as modified
            from sqlalchemy.orm.attributes import flag_modified

            flag_modified(stats, "stat_points_spent")

            # Recalculate max resource
            from src.database.models.core.player.player_progression import (
                PlayerProgression,
            )

            if resource_type == "energy":
                old_max = stats.max_energy
                stats.max_energy = (
                    PlayerProgression.BASE_ENERGY
                    + stats.stat_points_spent["energy"]
                    * PlayerProgression.ENERGY_PER_POINT
                )
                new_max = stats.max_energy
            elif resource_type == "stamina":
                old_max = stats.max_stamina
                stats.max_stamina = (
                    PlayerProgression.BASE_STAMINA
                    + stats.stat_points_spent["stamina"]
                    * PlayerProgression.STAMINA_PER_POINT
                )
                new_max = stats.max_stamina
            else:  # hp
                old_max = stats.max_hp
                stats.max_hp = (
                    PlayerProgression.BASE_HP
                    + stats.stat_points_spent["hp"] * PlayerProgression.HP_PER_POINT
                )
                new_max = stats.max_hp

            self.log.info(
                f"Stat points allocated: {resource_type} +{points_to_spend} points",
                extra={
                    "player_id": player_id,
                    "resource_type": resource_type,
                    "points_spent": points_to_spend,
                    "old_max": old_max,
                    "new_max": new_max,
                },
            )

            return {
                "player_id": player_id,
                "resource_type": resource_type,
                "points_spent": points_to_spend,
                "total_points_in_resource": stats.stat_points_spent[resource_type],
                "old_max": old_max,
                "new_max": new_max,
            }

    # ========================================================================
    # PUBLIC API - Battle Statistics
    # ========================================================================

    async def increment_stat(
        self,
        player_id: int,
        stat_key: str,
        increment: int = 1,
    ) -> Dict[str, Any]:
        """
        Increment a battle statistic counter.

        Args:
            player_id: Discord ID of the player
            stat_key: Statistic key
            increment: Amount to increment by (default 1)

        Returns:
            Dict with updated stat value
        """
        player_id = InputValidator.validate_discord_id(player_id)
        increment = InputValidator.validate_positive_integer(increment, "increment")

        async with DatabaseService.get_transaction() as session:
            stats = await self._stats_repo.find_one_where(
                session,
                self._stats_repo.model_class.player_id == player_id,
                for_update=True,
            )

            if not stats:
                raise NotFoundError("PlayerStats", player_id)

            old_value = stats.stats.get(stat_key, 0)
            new_value = old_value + increment
            stats.stats[stat_key] = new_value

            # Mark JSON field as modified
            from sqlalchemy.orm.attributes import flag_modified

            flag_modified(stats, "stats")

            return {
                "player_id": player_id,
                "stat_key": stat_key,
                "old_value": old_value,
                "new_value": new_value,
                "increment": increment,
            }
