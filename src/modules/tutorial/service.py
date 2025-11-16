"""
Tutorial Service - LES 2025 Compliant
======================================

Purpose
-------
Manages player tutorial progression with step tracking, reward distribution,
and completion validation.

Domain
------
- Track tutorial step completion
- Validate sequential step progression
- Award tutorial rewards
- Determine next tutorial step
- Detect full tutorial completion
- Handle tutorial state initialization

LUMEN 2025 COMPLIANCE
---------------------
✓ Pure business logic - no Discord dependencies
✓ Transaction-safe - all writes in atomic transactions
✓ Config-driven - tutorial steps and rewards from config
✓ Domain exceptions - raises NotFoundError, ValidationError, BusinessRuleViolation
✓ Event-driven - emits tutorial.* events
✓ Observable - structured logging, audit trail
✓ Pessimistic locking - uses SELECT FOR UPDATE for writes
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from sqlalchemy import select
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
    from src.database.models.progression.tutorial import TutorialProgress


# ============================================================================
# Repository
# ============================================================================


class TutorialProgressRepository(BaseRepository["TutorialProgress"]):
    """Repository for TutorialProgress model."""

    pass


# ============================================================================
# TutorialService
# ============================================================================


class TutorialService(BaseService):
    """
    Service for managing player tutorial progression.

    Handles tutorial step completion, reward distribution, and onboarding flow
    with full validation and event emission.

    Public Methods
    --------------
    - get_tutorial_progress() -> Get player's current tutorial state
    - start_tutorial() -> Initialize tutorial for a new player
    - complete_step() -> Mark a tutorial step as completed
    - claim_reward() -> Claim a tutorial step reward
    - get_next_step() -> Determine next uncompleted step
    - is_tutorial_complete() -> Check if all steps are completed
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        """
        Initialize TutorialService with required dependencies.

        Args:
            config_manager: Application configuration manager
            event_bus: Event bus for cross-module communication
            logger: Structured logger instance
        """
        super().__init__(config_manager, event_bus, logger)

        from src.database.models.progression.tutorial import TutorialProgress

        self._tutorial_repo = TutorialProgressRepository(
            model_class=TutorialProgress,
            logger=get_logger(f"{__name__}.TutorialProgressRepository"),
        )

    # ========================================================================
    # PUBLIC API - Read Operations
    # ========================================================================

    async def get_tutorial_progress(self, player_id: int) -> Dict[str, Any]:
        """
        Get player's current tutorial progress.

        This is a **read-only** operation using get_session().

        Args:
            player_id: Discord ID of the player

        Returns:
            Dict containing:
                - player_id: Player's Discord ID
                - steps_completed: Dict of step_id -> bool
                - rewards_claimed: Dict of step_id -> bool
                - started_at: When tutorial started
                - completed_at: When tutorial completed (None if incomplete)
                - is_complete: Whether all steps are done
                - next_step: Next uncompleted step (None if complete)

        Raises:
            NotFoundError: If player has no tutorial record

        Example:
            >>> progress = await service.get_tutorial_progress(123)
            >>> print(progress["next_step"])
            "first_summon"
        """
        player_id = InputValidator.validate_discord_id(player_id)

        self.log_operation("get_tutorial_progress", player_id=player_id)

        async with DatabaseService.get_session() as session:
            from src.database.models.progression.tutorial import TutorialProgress

            tutorial = await self._tutorial_repo.find_one_where(
                session,
                TutorialProgress.player_id == player_id,
            )

            if not tutorial:
                raise NotFoundError("TutorialProgress", player_id)

            # Get tutorial step order from config
            step_order = self.get_config("tutorial.step_order", default=[])
            next_step = self._determine_next_step(tutorial.steps_completed, step_order)

            return {
                "player_id": tutorial.player_id,
                "steps_completed": tutorial.steps_completed,
                "rewards_claimed": tutorial.rewards_claimed,
                "started_at": tutorial.started_at.isoformat(),
                "completed_at": tutorial.completed_at.isoformat()
                if tutorial.completed_at
                else None,
                "is_complete": tutorial.completed_at is not None,
                "next_step": next_step,
            }

    async def is_tutorial_complete(self, player_id: int) -> bool:
        """
        Check if player has completed the tutorial.

        This is a **read-only** operation using get_session().

        Args:
            player_id: Discord ID of the player

        Returns:
            True if tutorial is complete, False otherwise

        Example:
            >>> complete = await service.is_tutorial_complete(123)
            >>> if complete:
            ...     # Show advanced features
        """
        player_id = InputValidator.validate_discord_id(player_id)

        async with DatabaseService.get_session() as session:
            from src.database.models.progression.tutorial import TutorialProgress

            tutorial = await self._tutorial_repo.find_one_where(
                session,
                TutorialProgress.player_id == player_id,
            )

            if not tutorial:
                return False

            return tutorial.completed_at is not None

    async def get_next_step(self, player_id: int) -> Optional[str]:
        """
        Get the next uncompleted tutorial step.

        This is a **read-only** operation using get_session().

        Args:
            player_id: Discord ID of the player

        Returns:
            Next step ID or None if tutorial is complete

        Raises:
            NotFoundError: If player has no tutorial record

        Example:
            >>> next_step = await service.get_next_step(123)
            >>> if next_step:
            ...     # Show next tutorial prompt
        """
        player_id = InputValidator.validate_discord_id(player_id)

        async with DatabaseService.get_session() as session:
            from src.database.models.progression.tutorial import TutorialProgress

            tutorial = await self._tutorial_repo.find_one_where(
                session,
                TutorialProgress.player_id == player_id,
            )

            if not tutorial:
                raise NotFoundError("TutorialProgress", player_id)

            if tutorial.completed_at:
                return None

            step_order = self.get_config("tutorial.step_order", default=[])
            return self._determine_next_step(tutorial.steps_completed, step_order)

    # ========================================================================
    # PUBLIC API - Write Operations
    # ========================================================================

    async def start_tutorial(
        self,
        player_id: int,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Initialize tutorial progress for a new player.

        This is a **write operation** using get_transaction().

        Args:
            player_id: Discord ID of the player
            context: Optional command/system context

        Returns:
            Dict containing created tutorial record

        Raises:
            ValidationError: If player_id is invalid
            BusinessRuleViolation: If player already has a tutorial record

        Example:
            >>> result = await service.start_tutorial(
            ...     player_id=123,
            ...     context="/start"
            ... )
        """
        player_id = InputValidator.validate_discord_id(player_id)

        self.log_operation("start_tutorial", player_id=player_id)

        async with DatabaseService.get_transaction() as session:
            from src.database.models.progression.tutorial import TutorialProgress

            # Check if tutorial already exists
            existing = await self._tutorial_repo.find_one_where(
                session,
                TutorialProgress.player_id == player_id,
            )

            if existing:
                raise InvalidOperationError(
                    "start_tutorial",
                    f"Player {player_id} already has a tutorial record"
                )

            # Create new tutorial record
            now = datetime.now(timezone.utc)
            tutorial = TutorialProgress(
                player_id=player_id,
                steps_completed={},
                rewards_claimed={},
                started_at=now,
                completed_at=None,
            )

            session.add(tutorial)

            # Audit logging
            await AuditLogger.log(
                player_id=player_id,
                transaction_type="tutorial_started",
                details={"started_at": now.isoformat()},
                context=context,
            )

            # Event emission
            await self.emit_event(
                event_type="tutorial.started",
                data={
                    "player_id": player_id,
                    "started_at": now.isoformat(),
                },
            )

            self.log.info(
                f"Tutorial started for player {player_id}",
                extra={"player_id": player_id},
            )

            return {
                "player_id": tutorial.player_id,
                "steps_completed": tutorial.steps_completed,
                "rewards_claimed": tutorial.rewards_claimed,
                "started_at": tutorial.started_at.isoformat(),
                "completed_at": None,
            }

    async def complete_step(
        self,
        player_id: int,
        step_id: str,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Mark a tutorial step as completed.

        This is a **write operation** using get_transaction() with pessimistic locking.

        Validates that:
        - Previous steps are completed (sequential progression)
        - Step is not already completed
        - Step exists in tutorial configuration

        Args:
            player_id: Discord ID of the player
            step_id: Tutorial step identifier
            context: Optional command/system context

        Returns:
            Dict containing:
                - step_id: Completed step ID
                - player_id: Player's Discord ID
                - all_complete: Whether tutorial is now complete
                - next_step: Next step to complete (None if done)

        Raises:
            NotFoundError: If player has no tutorial record
            ValidationError: If step_id is invalid
            BusinessRuleViolation: If step is already completed or prerequisites not met

        Example:
            >>> result = await service.complete_step(
            ...     player_id=123,
            ...     step_id="first_summon",
            ...     context="/summon"
            ... )
        """
        player_id = InputValidator.validate_discord_id(player_id)
        step_id = InputValidator.validate_string(
            step_id, field_name="step_id", min_length=1, max_length=100
        )

        self.log_operation(
            "complete_step",
            player_id=player_id,
            step_id=step_id,
        )

        # Get tutorial configuration
        step_order = self.get_config("tutorial.step_order", default=[])
        if step_id not in step_order:
            raise ValidationError("step_id", f"Invalid tutorial step: {step_id}")

        async with DatabaseService.get_transaction() as session:
            from src.database.models.progression.tutorial import TutorialProgress

            # Lock tutorial record
            tutorial = await self._tutorial_repo.find_one_where(
                session,
                TutorialProgress.player_id == player_id,
                for_update=True,
            )

            if not tutorial:
                raise NotFoundError("TutorialProgress", player_id)

            # Check if already completed
            if tutorial.steps_completed.get(step_id, False):
                raise InvalidOperationError(
                    "complete_step",
                    f"Tutorial step '{step_id}' is already completed"
                )

            # Validate prerequisites (sequential progression)
            step_index = step_order.index(step_id)
            for i in range(step_index):
                prerequisite = step_order[i]
                if not tutorial.steps_completed.get(prerequisite, False):
                    raise InvalidOperationError(
                        "complete_step",
                        f"Cannot complete '{step_id}': prerequisite '{prerequisite}' not completed"
                    )

            # Mark step as completed
            tutorial.steps_completed[step_id] = True
            flag_modified(tutorial, "steps_completed")

            # Check if all steps are now complete
            all_complete = all(
                tutorial.steps_completed.get(step, False) for step in step_order
            )

            if all_complete and tutorial.completed_at is None:
                completed_time = datetime.now(timezone.utc)
                tutorial.completed_at = completed_time

                # Event emission for full completion
                await self.emit_event(
                    event_type="tutorial.completed",
                    data={
                        "player_id": player_id,
                        "completed_at": completed_time.isoformat(),
                    },
                )

            # Audit logging
            await AuditLogger.log(
                player_id=player_id,
                transaction_type="tutorial_step_completed",
                details={
                    "step_id": step_id,
                    "all_complete": all_complete,
                },
                context=context,
            )

            # Event emission for step completion
            await self.emit_event(
                event_type="tutorial.step_completed",
                data={
                    "player_id": player_id,
                    "step_id": step_id,
                    "all_complete": all_complete,
                },
            )

            self.log.info(
                f"Tutorial step '{step_id}' completed for player {player_id}",
                extra={
                    "player_id": player_id,
                    "step_id": step_id,
                    "all_complete": all_complete,
                },
            )

            next_step = self._determine_next_step(tutorial.steps_completed, step_order)

            return {
                "step_id": step_id,
                "player_id": player_id,
                "all_complete": all_complete,
                "next_step": next_step,
            }

    async def claim_reward(
        self,
        player_id: int,
        step_id: str,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Claim reward for a completed tutorial step.

        This is a **write operation** using get_transaction() with pessimistic locking.

        Args:
            player_id: Discord ID of the player
            step_id: Tutorial step identifier
            context: Optional command/system context

        Returns:
            Dict containing:
                - step_id: Step ID
                - player_id: Player's Discord ID
                - rewards: Reward data from config

        Raises:
            NotFoundError: If player has no tutorial record
            ValidationError: If step_id is invalid
            BusinessRuleViolation: If step not completed or reward already claimed

        Example:
            >>> result = await service.claim_reward(
            ...     player_id=123,
            ...     step_id="first_summon",
            ...     context="/tutorial claim"
            ... )
        """
        player_id = InputValidator.validate_discord_id(player_id)
        step_id = InputValidator.validate_string(
            step_id, field_name="step_id", min_length=1, max_length=100
        )

        self.log_operation(
            "claim_reward",
            player_id=player_id,
            step_id=step_id,
        )

        # Get reward configuration
        rewards = self.get_config(f"tutorial.rewards.{step_id}", default=None)
        if rewards is None:
            raise ValidationError("step_id", f"No reward configured for step: {step_id}")

        async with DatabaseService.get_transaction() as session:
            from src.database.models.progression.tutorial import TutorialProgress

            # Lock tutorial record
            tutorial = await self._tutorial_repo.find_one_where(
                session,
                TutorialProgress.player_id == player_id,
                for_update=True,
            )

            if not tutorial:
                raise NotFoundError("TutorialProgress", player_id)

            # Check if step is completed
            if not tutorial.steps_completed.get(step_id, False):
                raise InvalidOperationError(
                    "claim_reward",
                    f"Cannot claim reward: tutorial step '{step_id}' not completed"
                )

            # Check if reward already claimed
            if tutorial.rewards_claimed.get(step_id, False):
                raise InvalidOperationError(
                    "claim_reward",
                    f"Reward for tutorial step '{step_id}' already claimed"
                )

            # Mark reward as claimed
            tutorial.rewards_claimed[step_id] = True
            flag_modified(tutorial, "rewards_claimed")

            # Audit logging
            await AuditLogger.log(
                player_id=player_id,
                transaction_type="tutorial_reward_claimed",
                details={
                    "step_id": step_id,
                    "rewards": rewards,
                },
                context=context,
            )

            # Event emission
            await self.emit_event(
                event_type="tutorial.reward_claimed",
                data={
                    "player_id": player_id,
                    "step_id": step_id,
                    "rewards": rewards,
                },
            )

            self.log.info(
                f"Tutorial reward claimed for step '{step_id}' by player {player_id}",
                extra={
                    "player_id": player_id,
                    "step_id": step_id,
                    "rewards": rewards,
                },
            )

            return {
                "step_id": step_id,
                "player_id": player_id,
                "rewards": rewards,
            }

    # ========================================================================
    # PRIVATE HELPERS
    # ========================================================================

    def _determine_next_step(
        self, steps_completed: Dict[str, bool], step_order: List[str]
    ) -> Optional[str]:
        """
        Determine the next uncompleted tutorial step.

        Args:
            steps_completed: Dict of completed steps
            step_order: Ordered list of tutorial steps

        Returns:
            Next step ID or None if all complete
        """
        for step in step_order:
            if not steps_completed.get(step, False):
                return step
        return None
