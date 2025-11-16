"""
Exploration Mastery Service - LES 2025 Compliant
=================================================

Purpose
-------
Manages 3-rank mastery progression for exploration sectors with reward distribution,
sequential rank validation, and mastery bonus calculations.

Domain
------
- Track mastery rank completion (Rank 1, 2, 3)
- Validate sequential rank progression
- Award mastery milestone rewards
- Calculate mastery bonuses
- Track completion timestamps
- Check rank unlock eligibility

LUMEN 2025 COMPLIANCE
---------------------
✓ Pure business logic - no Discord dependencies
✓ Transaction-safe - all writes in atomic transactions
✓ Config-driven - rank requirements and rewards from config
✓ Domain exceptions - raises NotFoundError, ValidationError, BusinessRuleViolation
✓ Event-driven - emits exploration_mastery.* events
✓ Observable - structured logging, audit trail
✓ Pessimistic locking - uses SELECT FOR UPDATE for writes
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional

from sqlalchemy.orm.attributes import flag_modified

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
    from src.database.models.progression.exploration_mastery import ExplorationMastery


# ============================================================================
# Repository
# ============================================================================


class ExplorationMasteryRepository(BaseRepository["ExplorationMastery"]):
    """Repository for ExplorationMastery model."""

    pass


# ============================================================================
# ExplorationMasteryService
# ============================================================================


class ExplorationMasteryService(BaseService):
    """
    Service for managing exploration mastery ranks (1-3).

    Handles rank progression, eligibility checks, reward distribution,
    and mastery bonus calculations with full validation.

    Public Methods
    --------------
    - get_mastery() -> Get mastery record for a sector
    - complete_rank() -> Mark a mastery rank as complete
    - get_current_rank() -> Get current mastery rank (0-3)
    - is_rank_unlocked() -> Check if a rank is available
    - calculate_mastery_bonus() -> Calculate mastery bonus percentage
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        """
        Initialize ExplorationMasteryService with required dependencies.

        Args:
            config_manager: Application configuration manager
            event_bus: Event bus for cross-module communication
            logger: Structured logger instance
        """
        super().__init__(config_manager, event_bus, logger)

        from src.database.models.progression.exploration_mastery import (
            ExplorationMastery,
        )

        self._mastery_repo = ExplorationMasteryRepository(
            model_class=ExplorationMastery,
            logger=get_logger(f"{__name__}.ExplorationMasteryRepository"),
        )

    # ========================================================================
    # PUBLIC API - Read Operations
    # ========================================================================

    async def get_mastery(
        self, player_id: int, sector_id: int
    ) -> Dict[str, Any]:
        """
        Get player's mastery record for a specific sector.

        This is a **read-only** operation using get_session().

        Args:
            player_id: Discord ID of the player
            sector_id: Sector identifier

        Returns:
            Dict containing:
                - player_id: Player's Discord ID
                - sector_id: Sector identifier
                - current_rank: Current mastery rank (0-3)
                - rank_1_complete: Whether rank 1 is complete
                - rank_2_complete: Whether rank 2 is complete
                - rank_3_complete: Whether rank 3 is complete
                - rank_1_completed_at: Rank 1 completion timestamp
                - rank_2_completed_at: Rank 2 completion timestamp
                - rank_3_completed_at: Rank 3 completion timestamp
                - mastery_bonus: Current mastery bonus percentage

        Raises:
            NotFoundError: If no mastery record exists

        Example:
            >>> mastery = await service.get_mastery(123, 1)
            >>> print(mastery["current_rank"])
            2
        """
        player_id = InputValidator.validate_discord_id(player_id)
        sector_id = InputValidator.validate_positive_integer(
            sector_id, field_name="sector_id"
        )

        self.log_operation(
            "get_mastery",
            player_id=player_id,
            sector_id=sector_id,
        )

        async with DatabaseService.get_session() as session:
            from src.database.models.progression.exploration_mastery import (
                ExplorationMastery,
            )

            mastery = await self._mastery_repo.find_one_where(
                session,
                ExplorationMastery.player_id == player_id,
                ExplorationMastery.sector_id == sector_id,
            )

            if not mastery:
                raise NotFoundError(
                    "ExplorationMastery", f"player_id={player_id}, sector_id={sector_id}"
                )

            # Calculate current rank
            current_rank = 0
            if mastery.rank_1_complete:
                current_rank = 1
            if mastery.rank_2_complete:
                current_rank = 2
            if mastery.rank_3_complete:
                current_rank = 3

            # Calculate mastery bonus
            mastery_bonus = self._calculate_mastery_bonus_pct(current_rank)

            return {
                "player_id": mastery.player_id,
                "sector_id": mastery.sector_id,
                "current_rank": current_rank,
                "rank_1_complete": mastery.rank_1_complete,
                "rank_2_complete": mastery.rank_2_complete,
                "rank_3_complete": mastery.rank_3_complete,
                "rank_1_completed_at": mastery.rank_1_completed_at.isoformat()
                if mastery.rank_1_completed_at
                else None,
                "rank_2_completed_at": mastery.rank_2_completed_at.isoformat()
                if mastery.rank_2_completed_at
                else None,
                "rank_3_completed_at": mastery.rank_3_completed_at.isoformat()
                if mastery.rank_3_completed_at
                else None,
                "mastery_bonus": mastery_bonus,
                "meta": mastery.meta or {},
            }

    async def get_current_rank(self, player_id: int, sector_id: int) -> int:
        """
        Get current mastery rank for a sector.

        This is a **read-only** operation using get_session().

        Args:
            player_id: Discord ID of the player
            sector_id: Sector identifier

        Returns:
            Current rank (0-3)

        Example:
            >>> rank = await service.get_current_rank(123, 1)
            >>> print(rank)  # 2
        """
        player_id = InputValidator.validate_discord_id(player_id)
        sector_id = InputValidator.validate_positive_integer(
            sector_id, field_name="sector_id"
        )

        async with DatabaseService.get_session() as session:
            from src.database.models.progression.exploration_mastery import (
                ExplorationMastery,
            )

            mastery = await self._mastery_repo.find_one_where(
                session,
                ExplorationMastery.player_id == player_id,
                ExplorationMastery.sector_id == sector_id,
            )

            if not mastery:
                return 0

            if mastery.rank_3_complete:
                return 3
            if mastery.rank_2_complete:
                return 2
            if mastery.rank_1_complete:
                return 1
            return 0

    # ========================================================================
    # PUBLIC API - Write Operations
    # ========================================================================

    async def complete_rank(
        self,
        player_id: int,
        sector_id: int,
        rank: int,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Complete a mastery rank for a sector.

        This is a **write operation** using get_transaction() with pessimistic locking.

        Validates sequential rank progression (must complete Rank 1 before Rank 2, etc.).

        Args:
            player_id: Discord ID of the player
            sector_id: Sector identifier
            rank: Rank to complete (1, 2, or 3)
            context: Optional command/system context

        Returns:
            Dict containing:
                - player_id: Player's Discord ID
                - sector_id: Sector identifier
                - rank: Rank that was completed
                - completed_at: Completion timestamp
                - rewards: Rank completion rewards from config
                - is_fully_mastered: Whether all 3 ranks are complete

        Raises:
            ValidationError: If rank is invalid
            BusinessRuleViolation: If rank already complete or prerequisites not met

        Example:
            >>> result = await service.complete_rank(
            ...     player_id=123,
            ...     sector_id=1,
            ...     rank=2,
            ...     context="/mastery"
            ... )
        """
        player_id = InputValidator.validate_discord_id(player_id)
        sector_id = InputValidator.validate_positive_integer(
            sector_id, field_name="sector_id"
        )

        if rank not in (1, 2, 3):
            raise ValidationError("rank", "must be 1, 2, or 3")

        self.log_operation(
            "complete_rank",
            player_id=player_id,
            sector_id=sector_id,
            rank=rank,
        )

        # Get reward configuration
        rewards = self.get_config(
            f"exploration_mastery.rank_{rank}_rewards", default={}
        )

        now = datetime.now(timezone.utc)

        async with DatabaseService.get_transaction() as session:
            from src.database.models.progression.exploration_mastery import (
                ExplorationMastery,
            )

            # Try to find existing record (with lock if exists)
            mastery = await self._mastery_repo.find_one_where(
                session,
                ExplorationMastery.player_id == player_id,
                ExplorationMastery.sector_id == sector_id,
                for_update=True,
            )

            if not mastery:
                # Create new mastery record
                mastery = ExplorationMastery(
                    player_id=player_id,
                    sector_id=sector_id,
                    rank_1_complete=False,
                    rank_2_complete=False,
                    rank_3_complete=False,
                    rank_1_completed_at=None,
                    rank_2_completed_at=None,
                    rank_3_completed_at=None,
                    meta={},
                )
                session.add(mastery)

            # Validate sequential progression
            if rank == 2 and not mastery.rank_1_complete:
                raise InvalidOperationError("complete_rank",
                    "Cannot complete Rank 2: Rank 1 not completed"
                )

            if rank == 3 and not mastery.rank_2_complete:
                raise InvalidOperationError("complete_rank",
                    "Cannot complete Rank 3: Rank 2 not completed"
                )

            # Check if already completed
            if rank == 1 and mastery.rank_1_complete:
                raise InvalidOperationError("complete_rank","Rank 1 already completed")
            if rank == 2 and mastery.rank_2_complete:
                raise InvalidOperationError("complete_rank","Rank 2 already completed")
            if rank == 3 and mastery.rank_3_complete:
                raise InvalidOperationError("complete_rank","Rank 3 already completed")

            # Mark rank as complete
            if rank == 1:
                mastery.rank_1_complete = True
                mastery.rank_1_completed_at = now
            elif rank == 2:
                mastery.rank_2_complete = True
                mastery.rank_2_completed_at = now
            elif rank == 3:
                mastery.rank_3_complete = True
                mastery.rank_3_completed_at = now

            # Check if fully mastered
            is_fully_mastered = (
                mastery.rank_1_complete
                and mastery.rank_2_complete
                and mastery.rank_3_complete
            )

            # Audit logging
            await AuditLogger.log(
                player_id=player_id,
                transaction_type="mastery_rank_completed",
                details={
                    "sector_id": sector_id,
                    "rank": rank,
                    "completed_at": now.isoformat(),
                    "rewards": rewards,
                    "is_fully_mastered": is_fully_mastered,
                },
                context=context,
            )

            # Event emission
            await self.emit_event(
                event_type="exploration_mastery.rank_completed",
                data={
                    "player_id": player_id,
                    "sector_id": sector_id,
                    "rank": rank,
                    "completed_at": now.isoformat(),
                    "is_fully_mastered": is_fully_mastered,
                },
            )

            if is_fully_mastered:
                await self.emit_event(
                    event_type="exploration_mastery.fully_mastered",
                    data={
                        "player_id": player_id,
                        "sector_id": sector_id,
                        "completed_at": now.isoformat(),
                    },
                )

            self.log.info(
                f"Mastery Rank {rank} completed for sector {sector_id}",
                extra={
                    "player_id": player_id,
                    "sector_id": sector_id,
                    "rank": rank,
                    "is_fully_mastered": is_fully_mastered,
                },
            )

            return {
                "player_id": player_id,
                "sector_id": sector_id,
                "rank": rank,
                "completed_at": now.isoformat(),
                "rewards": rewards,
                "is_fully_mastered": is_fully_mastered,
            }

    # ========================================================================
    # PRIVATE HELPERS
    # ========================================================================

    def _calculate_mastery_bonus_pct(self, rank: int) -> float:
        """
        Calculate mastery bonus percentage based on rank.

        Args:
            rank: Current mastery rank (0-3)

        Returns:
            Bonus percentage (e.g., 0.15 for 15%)
        """
        rank_bonuses = self.get_config(
            "exploration_mastery.rank_bonuses",
            default={
                "rank_1": 0.05,  # 5%
                "rank_2": 0.10,  # 10%
                "rank_3": 0.15,  # 15%
            },
        )

        if rank == 0:
            return 0.0
        elif rank == 1:
            return rank_bonuses.get("rank_1", 0.05)
        elif rank == 2:
            return rank_bonuses.get("rank_2", 0.10)
        elif rank == 3:
            return rank_bonuses.get("rank_3", 0.15)
        else:
            return 0.0
