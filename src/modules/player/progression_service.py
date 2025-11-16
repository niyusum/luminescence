"""
Player Progression Service - LES 2025 Compliant
================================================

Purpose
-------
Manages player progression including leveling, XP, class selection, stat allocation,
milestones, fusion tracking, gacha pity, and tutorial progress with full transaction
safety, audit logging, and event emission.

Domain
------
- Level and XP management with configurable curves
- Class selection (destroyer, adapter, invoker)
- Stat point allocation tracking
- Milestone tracking (highest sector, floor, tier)
- Fusion system counters
- Gacha pity counter
- Tutorial progression

LUMEN 2025 COMPLIANCE
---------------------
✓ Pure business logic - no Discord dependencies
✓ Transaction-safe - all writes in atomic transactions
✓ Config-driven - XP curves, level rewards from config
✓ Domain exceptions - raises NotFoundError, ValidationError, BusinessRuleViolation
✓ Event-driven - emits events for progression milestones
✓ Observable - structured logging, audit trail, timing metrics
✓ Pessimistic locking - uses SELECT FOR UPDATE for all writes
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.core.database.service import DatabaseService
from src.core.infra.audit_logger import AuditLogger
from src.core.logging.logger import get_logger
from src.core.validation.input_validator import InputValidator
from src.modules.shared.base_repository import BaseRepository
from src.modules.shared.base_service import BaseService
from src.modules.shared.exceptions import (
    InvalidOperationError,
    NotFoundError,
    ValidationError,
)

if TYPE_CHECKING:
    from logging import Logger

    from src.core.config.manager import ConfigManager
    from src.core.event.bus import EventBus
    from src.database.models.core.player.player_progression import PlayerProgression


# ============================================================================
# Repository
# ============================================================================


class PlayerProgressionRepository(BaseRepository["PlayerProgression"]):
    """Repository for PlayerProgression model."""

    pass  # Inherits all CRUD from BaseRepository


# ============================================================================
# PlayerProgressionService
# ============================================================================


class PlayerProgressionService(BaseService):
    """
    Service for managing player progression and milestone tracking.

    Handles leveling, XP, class selection, stat allocation, milestone achievements,
    fusion tracking, gacha pity, and tutorial progress.

    Dependencies
    ------------
    - ConfigManager: For XP curves, level rewards, class bonuses
    - EventBus: For emitting progression events
    - Logger: For structured logging
    - DatabaseService: For transaction management (injected via context)
    - AuditLogger: For audit trail (static)

    Public Methods
    --------------
    - get_progression() -> Get player progression data
    - add_xp() -> Add XP and handle level-ups
    - select_class() -> Select player class (one-time only)
    - add_stat_points() -> Award unallocated stat points
    - update_milestone() -> Update highest sector/floor/tier
    - update_fusion_counters() -> Track fusion attempts
    - update_summon_counter() -> Track summons
    - update_pity_counter() -> Manage gacha pity
    - reset_pity_counter() -> Reset gacha pity
    - advance_tutorial() -> Progress tutorial step
    - complete_tutorial() -> Mark tutorial as complete
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        """
        Initialize PlayerProgressionService with required dependencies.

        Args:
            config_manager: Application configuration manager
            event_bus: Event bus for cross-module communication
            logger: Structured logger instance
        """
        super().__init__(config_manager, event_bus, logger)

        # Initialize repository with proper logger
        from src.database.models.core.player.player_progression import (
            PlayerProgression,
        )

        self._progression_repo = PlayerProgressionRepository(
            model_class=PlayerProgression,
            logger=get_logger(f"{__name__}.PlayerProgressionRepository"),
        )

    # ========================================================================
    # PUBLIC API - Read Operations
    # ========================================================================

    async def get_progression(self, player_id: int) -> Dict[str, Any]:
        """
        Get player progression data.

        This is a **read-only** operation using get_session().

        Args:
            player_id: Discord ID of the player

        Returns:
            Dict with progression information

        Raises:
            NotFoundError: If player progression record not found

        Example:
            >>> prog = await progression_service.get_progression(123456789)
            >>> print(prog["level"])  # 25
        """
        player_id = InputValidator.validate_discord_id(player_id)

        self.log_operation("get_progression", player_id=player_id)

        # Read-only operation - use get_session()
        async with DatabaseService.get_session() as session:
            progression = await self._progression_repo.find_one_where(
                session,
                self._progression_repo.model_class.player_id == player_id,
            )

            if not progression:
                raise NotFoundError("PlayerProgression", player_id)

            return {
                "player_id": progression.player_id,
                "level": progression.level,
                "xp": progression.xp,
                "last_level_up": progression.last_level_up,
                "class_name": progression.class_name,
                "stat_points": progression.stat_points,
                "highest_sector": progression.highest_sector,
                "highest_floor": progression.highest_floor,
                "highest_tier": progression.highest_tier,
                "total_fusions": progression.total_fusions,
                "successful_fusions": progression.successful_fusions,
                "failed_fusions": progression.failed_fusions,
                "total_summons": progression.total_summons,
                "pity_counter": progression.pity_counter,
                "tutorial_completed": progression.tutorial_completed,
                "tutorial_step": progression.tutorial_step,
                "state": progression.state or {},
            }

    # ========================================================================
    # PUBLIC API - Write Operations (XP & Leveling)
    # ========================================================================

    async def add_xp(
        self,
        player_id: int,
        xp_amount: int,
        reason: str,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Add XP to player and handle level-ups.

        This is a **write operation** using get_transaction() with pessimistic locking.

        Handles cascading level-ups if XP gain causes multiple levels.
        Awards stat points based on POINTS_PER_LEVEL config.

        Args:
            player_id: Discord ID of the player
            xp_amount: Amount of XP to add
            reason: Reason for XP gain
            context: Optional command/system context

        Returns:
            Dict with XP and level changes:
                {
                    "player_id": int,
                    "old_xp": int,
                    "new_xp": int,
                    "old_level": int,
                    "new_level": int,
                    "levels_gained": int,
                    "stat_points_awarded": int
                }

        Raises:
            NotFoundError: If player progression record not found

        Example:
            >>> result = await progression_service.add_xp(
            ...     player_id=123456789,
            ...     xp_amount=1000,
            ...     reason="quest_completion",
            ...     context="/quest"
            ... )
        """
        player_id = InputValidator.validate_discord_id(player_id)
        xp_amount = InputValidator.validate_positive_integer(xp_amount, "xp_amount")

        self.log_operation(
            "add_xp",
            player_id=player_id,
            xp_amount=xp_amount,
            reason=reason,
        )

        async with DatabaseService.get_transaction() as session:
            # Lock the row for update
            progression = await self._progression_repo.find_one_where(
                session,
                self._progression_repo.model_class.player_id == player_id,
                for_update=True,  # SELECT FOR UPDATE
            )

            if not progression:
                raise NotFoundError("PlayerProgression", player_id)

            old_xp = progression.xp
            old_level = progression.level

            # Add XP
            progression.xp = old_xp + xp_amount

            # Check for level-ups (can cascade)
            levels_gained = 0
            points_per_level = self.get_config("POINTS_PER_LEVEL", default=5)

            while True:
                xp_required = self._calculate_xp_for_level(progression.level + 1)
                if progression.xp >= xp_required:
                    progression.level += 1
                    levels_gained += 1
                    progression.stat_points += points_per_level
                    progression.last_level_up = datetime.now(timezone.utc)
                else:
                    break

            stat_points_awarded = levels_gained * points_per_level

            # Audit logging
            await AuditLogger.log(
                player_id=player_id,
                transaction_type="xp_added",
                details={
                    "old_xp": old_xp,
                    "new_xp": progression.xp,
                    "xp_amount": xp_amount,
                    "old_level": old_level,
                    "new_level": progression.level,
                    "levels_gained": levels_gained,
                    "stat_points_awarded": stat_points_awarded,
                    "reason": reason,
                },
                context=context or "xp_gain",
            )

            # Event emission
            await self.emit_event(
                event_type="player.xp_added",
                data={
                    "player_id": player_id,
                    "old_xp": old_xp,
                    "new_xp": progression.xp,
                    "xp_amount": xp_amount,
                    "reason": reason,
                },
            )

            # Level-up events
            if levels_gained > 0:
                await self.emit_event(
                    event_type="player.leveled_up",
                    data={
                        "player_id": player_id,
                        "old_level": old_level,
                        "new_level": progression.level,
                        "levels_gained": levels_gained,
                        "stat_points_awarded": stat_points_awarded,
                    },
                )

            self.log.info(
                f"XP added: +{xp_amount} XP, {levels_gained} levels gained",
                extra={
                    "player_id": player_id,
                    "old_xp": old_xp,
                    "new_xp": progression.xp,
                    "old_level": old_level,
                    "new_level": progression.level,
                    "levels_gained": levels_gained,
                    "stat_points_awarded": stat_points_awarded,
                },
            )

            return {
                "player_id": player_id,
                "old_xp": old_xp,
                "new_xp": progression.xp,
                "xp_amount": xp_amount,
                "old_level": old_level,
                "new_level": progression.level,
                "levels_gained": levels_gained,
                "stat_points_awarded": stat_points_awarded,
            }

    # ========================================================================
    # PUBLIC API - Class Selection
    # ========================================================================

    async def select_class(
        self,
        player_id: int,
        class_name: str,
    ) -> Dict[str, Any]:
        """
        Select player class (one-time only).

        This is a **write operation** using get_transaction() with pessimistic locking.

        Args:
            player_id: Discord ID of the player
            class_name: Class to select ("destroyer", "adapter", "invoker")

        Returns:
            Dict with class selection confirmation

        Raises:
            NotFoundError: If player progression record not found
            ValidationError: If class_name invalid
            BusinessRuleViolation: If class already selected

        Example:
            >>> result = await progression_service.select_class(
            ...     player_id=123456789,
            ...     class_name="destroyer"
            ... )
        """
        player_id = InputValidator.validate_discord_id(player_id)

        # Validate class name
        from src.database.models.core.player.player_progression import (
            PlayerProgression,
        )

        valid_classes = PlayerProgression.VALID_CLASSES
        class_name = InputValidator.validate_choice(
            class_name,
            field_name="class_name",
            valid_choices=valid_classes,
        )

        self.log_operation(
            "select_class",
            player_id=player_id,
            class_name=class_name,
        )

        async with DatabaseService.get_transaction() as session:
            # Lock the row for update
            progression = await self._progression_repo.find_one_where(
                session,
                self._progression_repo.model_class.player_id == player_id,
                for_update=True,
            )

            if not progression:
                raise NotFoundError("PlayerProgression", player_id)

            # Check if class already selected
            if progression.class_name is not None:
                raise InvalidOperationError(
                    action="select_class",
                    reason=f"Class already selected: {progression.class_name}. Class selection is permanent."
                )

            progression.class_name = class_name

            # Audit logging
            await AuditLogger.log(
                player_id=player_id,
                transaction_type="class_selected",
                details={"class_name": class_name},
                context="class_selection",
            )

            # Event emission
            await self.emit_event(
                event_type="player.class_selected",
                data={
                    "player_id": player_id,
                    "class_name": class_name,
                },
            )

            self.log.info(
                f"Class selected: {class_name}",
                extra={
                    "player_id": player_id,
                    "class_name": class_name,
                },
            )

            return {
                "player_id": player_id,
                "class_name": class_name,
            }

    # ========================================================================
    # PUBLIC API - Stat Points
    # ========================================================================

    async def add_stat_points(
        self,
        player_id: int,
        points_amount: int,
        reason: str,
    ) -> Dict[str, Any]:
        """
        Award unallocated stat points to player.

        This is a **write operation** using get_transaction() with pessimistic locking.

        Args:
            player_id: Discord ID of the player
            points_amount: Number of stat points to add
            reason: Reason for the award

        Returns:
            Dict with updated stat points

        Raises:
            NotFoundError: If player progression record not found

        Example:
            >>> result = await progression_service.add_stat_points(
            ...     player_id=123456789,
            ...     points_amount=10,
            ...     reason="special_event"
            ... )
        """
        player_id = InputValidator.validate_discord_id(player_id)
        points_amount = InputValidator.validate_positive_integer(
            points_amount, "points_amount"
        )

        self.log_operation(
            "add_stat_points",
            player_id=player_id,
            points_amount=points_amount,
        )

        async with DatabaseService.get_transaction() as session:
            # Lock the row for update
            progression = await self._progression_repo.find_one_where(
                session,
                self._progression_repo.model_class.player_id == player_id,
                for_update=True,
            )

            if not progression:
                raise NotFoundError("PlayerProgression", player_id)

            old_points = progression.stat_points
            progression.stat_points = old_points + points_amount

            # Audit logging
            await AuditLogger.log(
                player_id=player_id,
                transaction_type="stat_points_awarded",
                details={
                    "old_points": old_points,
                    "new_points": progression.stat_points,
                    "points_amount": points_amount,
                    "reason": reason,
                },
                context="stat_point_award",
            )

            # Event emission
            await self.emit_event(
                event_type="player.stat_points_awarded",
                data={
                    "player_id": player_id,
                    "old_points": old_points,
                    "new_points": progression.stat_points,
                    "points_amount": points_amount,
                    "reason": reason,
                },
            )

            self.log.info(
                f"Stat points awarded: +{points_amount}",
                extra={
                    "player_id": player_id,
                    "old_points": old_points,
                    "new_points": progression.stat_points,
                },
            )

            return {
                "player_id": player_id,
                "old_points": old_points,
                "new_points": progression.stat_points,
                "points_amount": points_amount,
            }

    # ========================================================================
    # PUBLIC API - Milestones
    # ========================================================================

    async def update_milestone(
        self,
        player_id: int,
        milestone_type: str,
        new_value: int,
    ) -> Dict[str, Any]:
        """
        Update progression milestone (only if new value is higher).

        This is a **write operation** using get_transaction() with pessimistic locking.

        Args:
            player_id: Discord ID of the player
            milestone_type: "sector", "floor", or "tier"
            new_value: New milestone value

        Returns:
            Dict with milestone update result

        Raises:
            NotFoundError: If player progression record not found
            ValidationError: If milestone_type invalid

        Example:
            >>> result = await progression_service.update_milestone(
            ...     player_id=123456789,
            ...     milestone_type="sector",
            ...     new_value=5
            ... )
        """
        player_id = InputValidator.validate_discord_id(player_id)
        milestone_type = InputValidator.validate_choice(
            milestone_type,
            field_name="milestone_type",
            valid_choices=["sector", "floor", "tier"],
        )
        new_value = InputValidator.validate_non_negative_integer(new_value, "new_value")

        self.log_operation(
            "update_milestone",
            player_id=player_id,
            milestone_type=milestone_type,
            new_value=new_value,
        )

        # Map milestone type to field name
        field_map = {
            "sector": "highest_sector",
            "floor": "highest_floor",
            "tier": "highest_tier",
        }
        field_name = field_map[milestone_type]

        async with DatabaseService.get_transaction() as session:
            # Lock the row for update
            progression = await self._progression_repo.find_one_where(
                session,
                self._progression_repo.model_class.player_id == player_id,
                for_update=True,
            )

            if not progression:
                raise NotFoundError("PlayerProgression", player_id)

            old_value = getattr(progression, field_name)

            # Only update if new value is higher
            if new_value > old_value:
                setattr(progression, field_name, new_value)
                updated = True

                # Audit logging
                await AuditLogger.log(
                    player_id=player_id,
                    transaction_type="milestone_updated",
                    details={
                        "milestone_type": milestone_type,
                        "old_value": old_value,
                        "new_value": new_value,
                    },
                    context="milestone_achievement",
                )

                # Event emission
                await self.emit_event(
                    event_type="player.milestone_reached",
                    data={
                        "player_id": player_id,
                        "milestone_type": milestone_type,
                        "old_value": old_value,
                        "new_value": new_value,
                    },
                )

                self.log.info(
                    f"Milestone updated: {milestone_type} {old_value} -> {new_value}",
                    extra={
                        "player_id": player_id,
                        "milestone_type": milestone_type,
                        "old_value": old_value,
                        "new_value": new_value,
                    },
                )
            else:
                updated = False

            return {
                "player_id": player_id,
                "milestone_type": milestone_type,
                "old_value": old_value,
                "new_value": getattr(progression, field_name),
                "updated": updated,
            }

    # ========================================================================
    # PUBLIC API - Fusion Tracking
    # ========================================================================

    async def update_fusion_counters(
        self,
        player_id: int,
        success: bool,
    ) -> Dict[str, Any]:
        """
        Update fusion attempt counters.

        This is a **write operation** using get_transaction() with pessimistic locking.

        Args:
            player_id: Discord ID of the player
            success: True if fusion succeeded, False if failed

        Returns:
            Dict with updated fusion counters

        Raises:
            NotFoundError: If player progression record not found

        Example:
            >>> result = await progression_service.update_fusion_counters(
            ...     player_id=123456789,
            ...     success=True
            ... )
        """
        player_id = InputValidator.validate_discord_id(player_id)

        self.log_operation(
            "update_fusion_counters",
            player_id=player_id,
            success=success,
        )

        async with DatabaseService.get_transaction() as session:
            # Lock the row for update
            progression = await self._progression_repo.find_one_where(
                session,
                self._progression_repo.model_class.player_id == player_id,
                for_update=True,
            )

            if not progression:
                raise NotFoundError("PlayerProgression", player_id)

            progression.total_fusions += 1

            if success:
                progression.successful_fusions += 1
            else:
                progression.failed_fusions += 1

            # Event emission (no audit logging - tracked by fusion service)
            await self.emit_event(
                event_type="player.fusion_counted",
                data={
                    "player_id": player_id,
                    "success": success,
                    "total_fusions": progression.total_fusions,
                    "successful_fusions": progression.successful_fusions,
                    "failed_fusions": progression.failed_fusions,
                },
            )

            self.log.info(
                f"Fusion counter updated: {'success' if success else 'failure'}",
                extra={
                    "player_id": player_id,
                    "success": success,
                    "total_fusions": progression.total_fusions,
                },
            )

            return {
                "player_id": player_id,
                "success": success,
                "total_fusions": progression.total_fusions,
                "successful_fusions": progression.successful_fusions,
                "failed_fusions": progression.failed_fusions,
            }

    # ========================================================================
    # PUBLIC API - Gacha/Summon Tracking
    # ========================================================================

    async def update_summon_counter(self, player_id: int) -> Dict[str, Any]:
        """
        Increment total summons counter.

        This is a **write operation** using get_transaction() with pessimistic locking.

        Args:
            player_id: Discord ID of the player

        Returns:
            Dict with updated summon count

        Raises:
            NotFoundError: If player progression record not found

        Example:
            >>> result = await progression_service.update_summon_counter(123456789)
        """
        player_id = InputValidator.validate_discord_id(player_id)

        self.log_operation("update_summon_counter", player_id=player_id)

        async with DatabaseService.get_transaction() as session:
            # Lock the row for update
            progression = await self._progression_repo.find_one_where(
                session,
                self._progression_repo.model_class.player_id == player_id,
                for_update=True,
            )

            if not progression:
                raise NotFoundError("PlayerProgression", player_id)

            progression.total_summons += 1

            self.log.info(
                "Summon counter updated",
                extra={
                    "player_id": player_id,
                    "total_summons": progression.total_summons,
                },
            )

            return {
                "player_id": player_id,
                "total_summons": progression.total_summons,
            }

    async def update_pity_counter(
        self,
        player_id: int,
        increment: int = 1,
    ) -> Dict[str, Any]:
        """
        Increment pity counter.

        This is a **write operation** using get_transaction() with pessimistic locking.

        Args:
            player_id: Discord ID of the player
            increment: Amount to increment by (default 1)

        Returns:
            Dict with updated pity counter

        Raises:
            NotFoundError: If player progression record not found

        Example:
            >>> result = await progression_service.update_pity_counter(123456789)
        """
        player_id = InputValidator.validate_discord_id(player_id)
        increment = InputValidator.validate_positive_integer(increment, "increment")

        self.log_operation(
            "update_pity_counter",
            player_id=player_id,
            increment=increment,
        )

        async with DatabaseService.get_transaction() as session:
            # Lock the row for update
            progression = await self._progression_repo.find_one_where(
                session,
                self._progression_repo.model_class.player_id == player_id,
                for_update=True,
            )

            if not progression:
                raise NotFoundError("PlayerProgression", player_id)

            old_pity = progression.pity_counter
            progression.pity_counter = old_pity + increment

            self.log.info(
                f"Pity counter updated: +{increment}",
                extra={
                    "player_id": player_id,
                    "old_pity": old_pity,
                    "new_pity": progression.pity_counter,
                },
            )

            return {
                "player_id": player_id,
                "old_pity": old_pity,
                "new_pity": progression.pity_counter,
                "increment": increment,
            }

    async def reset_pity_counter(self, player_id: int) -> Dict[str, Any]:
        """
        Reset pity counter to zero.

        This is a **write operation** using get_transaction() with pessimistic locking.

        Args:
            player_id: Discord ID of the player

        Returns:
            Dict with reset confirmation

        Raises:
            NotFoundError: If player progression record not found

        Example:
            >>> result = await progression_service.reset_pity_counter(123456789)
        """
        player_id = InputValidator.validate_discord_id(player_id)

        self.log_operation("reset_pity_counter", player_id=player_id)

        async with DatabaseService.get_transaction() as session:
            # Lock the row for update
            progression = await self._progression_repo.find_one_where(
                session,
                self._progression_repo.model_class.player_id == player_id,
                for_update=True,
            )

            if not progression:
                raise NotFoundError("PlayerProgression", player_id)

            old_pity = progression.pity_counter
            progression.pity_counter = 0

            self.log.info(
                "Pity counter reset",
                extra={
                    "player_id": player_id,
                    "old_pity": old_pity,
                },
            )

            return {
                "player_id": player_id,
                "old_pity": old_pity,
                "new_pity": 0,
            }

    # ========================================================================
    # PUBLIC API - Tutorial Tracking
    # ========================================================================

    async def advance_tutorial(
        self,
        player_id: int,
        new_step: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Advance tutorial to next step.

        This is a **write operation** using get_transaction() with pessimistic locking.

        Args:
            player_id: Discord ID of the player
            new_step: Specific step to set (defaults to current + 1)

        Returns:
            Dict with tutorial progress

        Raises:
            NotFoundError: If player progression record not found

        Example:
            >>> result = await progression_service.advance_tutorial(123456789)
        """
        player_id = InputValidator.validate_discord_id(player_id)

        if new_step is not None:
            new_step = InputValidator.validate_non_negative_integer(new_step, "new_step")

        self.log_operation("advance_tutorial", player_id=player_id)

        async with DatabaseService.get_transaction() as session:
            # Lock the row for update
            progression = await self._progression_repo.find_one_where(
                session,
                self._progression_repo.model_class.player_id == player_id,
                for_update=True,
            )

            if not progression:
                raise NotFoundError("PlayerProgression", player_id)

            old_step = progression.tutorial_step

            if new_step is not None:
                progression.tutorial_step = new_step
            else:
                progression.tutorial_step = old_step + 1

            self.log.info(
                f"Tutorial advanced: step {old_step} -> {progression.tutorial_step}",
                extra={
                    "player_id": player_id,
                    "old_step": old_step,
                    "new_step": progression.tutorial_step,
                },
            )

            return {
                "player_id": player_id,
                "old_step": old_step,
                "new_step": progression.tutorial_step,
            }

    async def complete_tutorial(self, player_id: int) -> Dict[str, Any]:
        """
        Mark tutorial as completed.

        This is a **write operation** using get_transaction() with pessimistic locking.

        Args:
            player_id: Discord ID of the player

        Returns:
            Dict with completion confirmation

        Raises:
            NotFoundError: If player progression record not found

        Example:
            >>> result = await progression_service.complete_tutorial(123456789)
        """
        player_id = InputValidator.validate_discord_id(player_id)

        self.log_operation("complete_tutorial", player_id=player_id)

        async with DatabaseService.get_transaction() as session:
            # Lock the row for update
            progression = await self._progression_repo.find_one_where(
                session,
                self._progression_repo.model_class.player_id == player_id,
                for_update=True,
            )

            if not progression:
                raise NotFoundError("PlayerProgression", player_id)

            was_completed = progression.tutorial_completed
            progression.tutorial_completed = True

            # Event emission
            if not was_completed:
                await self.emit_event(
                    event_type="player.tutorial_completed",
                    data={"player_id": player_id},
                )

            self.log.info(
                "Tutorial completed",
                extra={
                    "player_id": player_id,
                    "was_completed": was_completed,
                },
            )

            return {
                "player_id": player_id,
                "tutorial_completed": True,
                "was_already_completed": was_completed,
            }

    # ========================================================================
    # PRIVATE HELPERS
    # ========================================================================

    def _calculate_xp_for_level(self, target_level: int) -> int:
        """
        Calculate XP required to reach a target level.

        Uses config-driven XP curve (exponential, polynomial, or logarithmic).

        Args:
            target_level: Target level

        Returns:
            Total XP required
        """
        # Config-driven XP curve
        curve_type = self.get_config("XP_CURVE_TYPE", default="exponential")
        base_xp = self.get_config("XP_CURVE_BASE", default=100)
        exponent = self.get_config("XP_CURVE_EXPONENT", default=1.5)

        if curve_type == "exponential":
            # XP = base * (level ^ exponent)
            return int(base_xp * (target_level**exponent))
        elif curve_type == "polynomial":
            # XP = base * level * exponent
            return int(base_xp * target_level * exponent)
        elif curve_type == "logarithmic":
            # XP = base * log(level + 1) * exponent
            import math

            return int(base_xp * math.log(target_level + 1) * exponent)
        else:
            # Default to exponential
            return int(base_xp * (target_level**exponent))
