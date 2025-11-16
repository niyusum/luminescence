"""
Ascension Progress Service - LES 2025 Compliant
================================================

Purpose
-------
Manages infinite tower (ascension) progression with floor tracking, combat statistics,
reward calculations, and leaderboard integration.

Domain
------
- Track current and highest floor reached
- Record combat attempts, victories, and defeats
- Calculate floor-based rewards (XP, lumees)
- Apply floor scaling formulas
- Check floor eligibility
- Update floor records and trigger leaderboard submissions
- Calculate win rates and statistics

LUMEN 2025 COMPLIANCE
---------------------
✓ Pure business logic - no Discord dependencies
✓ Transaction-safe - all writes in atomic transactions
✓ Config-driven - floor scaling and rewards from config
✓ Domain exceptions - raises NotFoundError, ValidationError, BusinessRuleViolation
✓ Event-driven - emits ascension.* events
✓ Observable - structured logging, audit trail
✓ Pessimistic locking - uses SELECT FOR UPDATE for writes
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional

from src.core.database.service import DatabaseService
from src.core.infra.audit_logger import AuditLogger
from src.core.logging.logger import get_logger
from src.core.validation.input_validator import InputValidator
from src.modules.shared.base_repository import BaseRepository
from src.modules.shared.base_service import BaseService
from src.modules.shared.exceptions import (
    NotFoundError,
    ValidationError,
)

if TYPE_CHECKING:
    from logging import Logger

    from src.core.config.manager import ConfigManager
    from src.core.event.bus import EventBus
    from src.database.models.progression.ascension_progress import AscensionProgress


# ============================================================================
# Repository
# ============================================================================


class AscensionProgressRepository(BaseRepository["AscensionProgress"]):
    """Repository for AscensionProgress model."""

    pass


# ============================================================================
# AscensionProgressService
# ============================================================================


class AscensionProgressService(BaseService):
    """
    Service for managing ascension tower progression.

    Handles floor progression, combat tracking, reward calculations,
    and leaderboard integration with full transaction safety.

    Public Methods
    --------------
    - get_ascension_progress() -> Get player's ascension stats
    - record_floor_attempt() -> Record a floor battle attempt
    - record_floor_victory() -> Record a floor victory and advance
    - record_floor_defeat() -> Record a floor defeat
    - calculate_floor_rewards() -> Calculate rewards for a floor
    - get_win_rate() -> Calculate overall win rate
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        """
        Initialize AscensionProgressService with required dependencies.

        Args:
            config_manager: Application configuration manager
            event_bus: Event bus for cross-module communication
            logger: Structured logger instance
        """
        super().__init__(config_manager, event_bus, logger)

        from src.database.models.progression.ascension_progress import (
            AscensionProgress,
        )

        self._ascension_repo = AscensionProgressRepository(
            model_class=AscensionProgress,
            logger=get_logger(f"{__name__}.AscensionProgressRepository"),
        )

    # ========================================================================
    # PUBLIC API - Read Operations
    # ========================================================================

    async def get_ascension_progress(self, player_id: int) -> Dict[str, Any]:
        """
        Get player's ascension tower progress and statistics.

        This is a **read-only** operation using get_session().

        Args:
            player_id: Discord ID of the player

        Returns:
            Dict containing:
                - player_id: Player's Discord ID
                - current_floor: Current floor number
                - highest_floor: Highest floor ever reached
                - total_floors_cleared: Lifetime floors cleared
                - total_attempts: Total battle attempts
                - total_victories: Total victories
                - total_defeats: Total defeats
                - total_lumees_earned: Lifetime lumees from ascension
                - total_xp_earned: Lifetime XP from ascension
                - win_rate: Victory percentage (0.0-1.0)
                - last_attempt: Last attempt timestamp
                - last_victory: Last victory timestamp

        Raises:
            NotFoundError: If player has no ascension record

        Example:
            >>> progress = await service.get_ascension_progress(123)
            >>> print(progress["highest_floor"])
            42
        """
        player_id = InputValidator.validate_discord_id(player_id)

        self.log_operation("get_ascension_progress", player_id=player_id)

        async with DatabaseService.get_session() as session:
            from src.database.models.progression.ascension_progress import (
                AscensionProgress,
            )

            ascension = await self._ascension_repo.find_one_where(
                session,
                AscensionProgress.player_id == player_id,
            )

            if not ascension:
                raise NotFoundError("AscensionProgress", player_id)

            # Calculate win rate
            win_rate = (
                ascension.total_victories / ascension.total_attempts
                if ascension.total_attempts > 0
                else 0.0
            )

            return {
                "player_id": ascension.player_id,
                "current_floor": ascension.current_floor,
                "highest_floor": ascension.highest_floor,
                "total_floors_cleared": ascension.total_floors_cleared,
                "total_attempts": ascension.total_attempts,
                "total_victories": ascension.total_victories,
                "total_defeats": ascension.total_defeats,
                "total_lumees_earned": ascension.total_lumees_earned,
                "total_xp_earned": ascension.total_xp_earned,
                "win_rate": win_rate,
                "last_attempt": ascension.last_attempt.isoformat()
                if ascension.last_attempt
                else None,
                "last_victory": ascension.last_victory.isoformat()
                if ascension.last_victory
                else None,
            }

    async def get_win_rate(self, player_id: int) -> float:
        """
        Calculate player's overall ascension win rate.

        This is a **read-only** operation using get_session().

        Args:
            player_id: Discord ID of the player

        Returns:
            Win rate as decimal (0.0-1.0)

        Example:
            >>> win_rate = await service.get_win_rate(123)
            >>> print(f"{win_rate:.1%}")  # "75.0%"
        """
        player_id = InputValidator.validate_discord_id(player_id)

        async with DatabaseService.get_session() as session:
            from src.database.models.progression.ascension_progress import (
                AscensionProgress,
            )

            ascension = await self._ascension_repo.find_one_where(
                session,
                AscensionProgress.player_id == player_id,
            )

            if not ascension or ascension.total_attempts == 0:
                return 0.0

            return ascension.total_victories / ascension.total_attempts

    # ========================================================================
    # PUBLIC API - Write Operations
    # ========================================================================

    async def record_floor_victory(
        self,
        player_id: int,
        floor: int,
        lumees_earned: int = 0,
        xp_earned: int = 0,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Record a floor victory and advance to the next floor.

        This is a **write operation** using get_transaction() with pessimistic locking.

        Creates ascension record if it doesn't exist. Updates statistics and advances
        to the next floor. Triggers leaderboard update if new high floor.

        Args:
            player_id: Discord ID of the player
            floor: Floor that was defeated
            lumees_earned: Lumees reward from floor
            xp_earned: XP reward from floor
            context: Optional command/system context

        Returns:
            Dict containing:
                - player_id: Player's Discord ID
                - floor_defeated: Floor that was defeated
                - next_floor: New current floor
                - is_new_high_floor: Whether this is a new record
                - highest_floor: Current highest floor
                - lumees_earned: Lumees from this victory
                - xp_earned: XP from this victory

        Raises:
            ValidationError: If floor or rewards are invalid

        Example:
            >>> result = await service.record_floor_victory(
            ...     player_id=123,
            ...     floor=10,
            ...     lumees_earned=500,
            ...     xp_earned=250,
            ...     context="/ascend"
            ... )
        """
        player_id = InputValidator.validate_discord_id(player_id)
        floor = InputValidator.validate_positive_integer(floor, field_name="floor")

        if lumees_earned < 0:
            raise ValidationError("lumees_earned", "cannot be negative")
        if xp_earned < 0:
            raise ValidationError("xp_earned", "cannot be negative")

        self.log_operation(
            "record_floor_victory",
            player_id=player_id,
            floor=floor,
        )

        now = datetime.now(timezone.utc)

        async with DatabaseService.get_transaction() as session:
            from src.database.models.progression.ascension_progress import (
                AscensionProgress,
            )

            # Try to find existing record (with lock if exists)
            ascension = await self._ascension_repo.find_one_where(
                session,
                AscensionProgress.player_id == player_id,
                for_update=True,
            )

            if not ascension:
                # Create new ascension record
                ascension = AscensionProgress(
                    player_id=player_id,
                    current_floor=0,
                    highest_floor=0,
                    total_floors_cleared=0,
                    total_attempts=0,
                    total_victories=0,
                    total_defeats=0,
                    total_lumees_earned=0,
                    total_xp_earned=0,
                    last_attempt=None,
                    last_victory=None,
                )
                session.add(ascension)

            # Update statistics
            ascension.total_attempts += 1
            ascension.total_victories += 1
            ascension.total_floors_cleared += 1
            ascension.total_lumees_earned += lumees_earned
            ascension.total_xp_earned += xp_earned
            ascension.last_attempt = now
            ascension.last_victory = now

            # Advance to next floor
            next_floor = floor + 1
            ascension.current_floor = next_floor

            # Check if new high floor
            is_new_high_floor = floor > ascension.highest_floor
            if is_new_high_floor:
                ascension.highest_floor = floor

                # Trigger leaderboard update event
                await self.emit_event(
                    event_type="ascension.new_high_floor",
                    data={
                        "player_id": player_id,
                        "highest_floor": floor,
                        "timestamp": now.isoformat(),
                    },
                )

            # Audit logging
            await AuditLogger.log(
                player_id=player_id,
                transaction_type="ascension_floor_victory",
                details={
                    "floor_defeated": floor,
                    "next_floor": next_floor,
                    "is_new_high_floor": is_new_high_floor,
                    "lumees_earned": lumees_earned,
                    "xp_earned": xp_earned,
                },
                context=context,
            )

            # Event emission
            await self.emit_event(
                event_type="ascension.floor_victory",
                data={
                    "player_id": player_id,
                    "floor_defeated": floor,
                    "next_floor": next_floor,
                    "is_new_high_floor": is_new_high_floor,
                    "lumees_earned": lumees_earned,
                    "xp_earned": xp_earned,
                },
            )

            self.log.info(
                f"Floor {floor} defeated, advancing to floor {next_floor}",
                extra={
                    "player_id": player_id,
                    "floor_defeated": floor,
                    "next_floor": next_floor,
                    "is_new_high_floor": is_new_high_floor,
                },
            )

            return {
                "player_id": player_id,
                "floor_defeated": floor,
                "next_floor": next_floor,
                "is_new_high_floor": is_new_high_floor,
                "highest_floor": ascension.highest_floor,
                "lumees_earned": lumees_earned,
                "xp_earned": xp_earned,
            }

    async def record_floor_defeat(
        self,
        player_id: int,
        floor: int,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Record a floor defeat.

        This is a **write operation** using get_transaction() with pessimistic locking.

        Updates defeat statistics without advancing floors.

        Args:
            player_id: Discord ID of the player
            floor: Floor where defeat occurred
            context: Optional command/system context

        Returns:
            Dict containing defeat statistics

        Raises:
            ValidationError: If floor is invalid

        Example:
            >>> result = await service.record_floor_defeat(
            ...     player_id=123,
            ...     floor=10,
            ...     context="/ascend"
            ... )
        """
        player_id = InputValidator.validate_discord_id(player_id)
        floor = InputValidator.validate_positive_integer(floor, field_name="floor")

        self.log_operation(
            "record_floor_defeat",
            player_id=player_id,
            floor=floor,
        )

        now = datetime.now(timezone.utc)

        async with DatabaseService.get_transaction() as session:
            from src.database.models.progression.ascension_progress import (
                AscensionProgress,
            )

            # Lock ascension record
            ascension = await self._ascension_repo.find_one_where(
                session,
                AscensionProgress.player_id == player_id,
                for_update=True,
            )

            if not ascension:
                # Create new record with a defeat
                ascension = AscensionProgress(
                    player_id=player_id,
                    current_floor=0,
                    highest_floor=0,
                    total_floors_cleared=0,
                    total_attempts=1,
                    total_victories=0,
                    total_defeats=1,
                    total_lumees_earned=0,
                    total_xp_earned=0,
                    last_attempt=now,
                    last_victory=None,
                )
                session.add(ascension)
            else:
                # Update statistics
                ascension.total_attempts += 1
                ascension.total_defeats += 1
                ascension.last_attempt = now

            # Audit logging
            await AuditLogger.log(
                player_id=player_id,
                transaction_type="ascension_floor_defeat",
                details={
                    "floor": floor,
                    "total_defeats": ascension.total_defeats,
                },
                context=context,
            )

            # Event emission
            await self.emit_event(
                event_type="ascension.floor_defeat",
                data={
                    "player_id": player_id,
                    "floor": floor,
                    "timestamp": now.isoformat(),
                },
            )

            self.log.info(
                f"Floor {floor} defeat",
                extra={
                    "player_id": player_id,
                    "floor": floor,
                    "total_defeats": ascension.total_defeats,
                },
            )

            return {
                "player_id": player_id,
                "floor": floor,
                "total_defeats": ascension.total_defeats,
                "total_attempts": ascension.total_attempts,
            }

    # ========================================================================
    # PRIVATE HELPERS
    # ========================================================================

    def _calculate_floor_rewards(self, floor: int) -> Dict[str, int]:
        """
        Calculate rewards for defeating a floor.

        Args:
            floor: Floor number

        Returns:
            Dict with lumees and xp amounts
        """
        # Get base values from config
        base_lumees = self.get_config("ascension.base_lumees_per_floor", default=50)
        base_xp = self.get_config("ascension.base_xp_per_floor", default=25)

        # Apply exponential scaling
        scaling_exponent = self.get_config("ascension.reward_scaling_exponent", default=1.1)

        lumees = int(base_lumees * (floor ** scaling_exponent))
        xp = int(base_xp * (floor ** scaling_exponent))

        return {"lumees": lumees, "xp": xp}
