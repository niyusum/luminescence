"""
Daily Quest Service - LES 2025 Compliant
=========================================

Purpose
-------
Manages daily quest progression, completion tracking, reward distribution,
and streak management with automatic daily reset.

Domain
------
- Track quest completion state
- Update quest progress counters
- Award quest rewards
- Manage completion streaks
- Handle daily resets at UTC midnight
- Auto-generate quest sets
- Prevent double-claim exploits

LUMEN 2025 COMPLIANCE
---------------------
✓ Pure business logic - no Discord dependencies
✓ Transaction-safe - all writes in atomic transactions
✓ Config-driven - quest definitions and rewards from config
✓ Domain exceptions - raises NotFoundError, ValidationError, BusinessRuleViolation
✓ Event-driven - emits daily_quest.* events
✓ Observable - structured logging, audit trail
✓ Pessimistic locking - uses SELECT FOR UPDATE for writes
"""

from __future__ import annotations

from datetime import date, datetime, timezone
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
    from src.database.models.progression.daily_quest import DailyQuest
    from src.modules.player.currencies_service import PlayerCurrenciesService
    from src.modules.player.progression_service import PlayerProgressionService


# ============================================================================
# Repository
# ============================================================================


class DailyQuestRepository(BaseRepository["DailyQuest"]):
    """Repository for DailyQuest model."""

    pass


# ============================================================================
# DailyQuestService
# ============================================================================


class DailyQuestService(BaseService):
    """
    Service for managing daily quest progression and rewards.

    Handles quest progress tracking, completion validation, reward distribution,
    and automatic daily resets with full transaction safety.

    Public Methods
    --------------
    - get_daily_quests() -> Get player's current daily quests
    - update_quest_progress() -> Increment quest progress counter
    - complete_quest() -> Mark a quest as completed
    - claim_daily_rewards() -> Claim rewards for all completed quests
    - get_or_create_today_quests() -> Get or generate today's quest set
    - reset_expired_quests() -> Reset quests from previous days
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        event_bus: EventBus,
        logger: Logger,
        player_currencies_service: PlayerCurrenciesService,
        player_progression_service: PlayerProgressionService,
    ) -> None:
        """
        Initialize DailyQuestService with required dependencies.

        Args:
            config_manager: Application configuration manager
            event_bus: Event bus for cross-module communication
            logger: Structured logger instance
            player_currencies_service: Service for currency operations
            player_progression_service: Service for XP operations
        """
        super().__init__(config_manager, event_bus, logger)

        from src.database.models.progression.daily_quest import DailyQuest

        self._daily_quest_repo = DailyQuestRepository(
            model_class=DailyQuest,
            logger=get_logger(f"{__name__}.DailyQuestRepository"),
        )

        # SAFETY: Store service dependencies for reward distribution
        self._player_currencies = player_currencies_service
        self._player_progression = player_progression_service

    # ========================================================================
    # PUBLIC API - Read Operations
    # ========================================================================

    async def get_daily_quests(
        self, player_id: int, quest_date: Optional[date] = None
    ) -> Dict[str, Any]:
        """
        Get player's daily quests for a specific date.

        This is a **read-only** operation using get_session().

        Args:
            player_id: Discord ID of the player
            quest_date: Date to query (defaults to today)

        Returns:
            Dict containing:
                - player_id: Player's Discord ID
                - quest_date: Date of quests
                - quests_completed: Dict of quest_id -> bool
                - quest_progress: Dict of quest_id -> current_progress
                - rewards_claimed: Whether rewards have been claimed
                - bonus_streak: Current completion streak
                - all_complete: Whether all quests are done

        Raises:
            NotFoundError: If no quests found for this date

        Example:
            >>> quests = await service.get_daily_quests(123)
            >>> print(quests["bonus_streak"])
            5
        """
        player_id = InputValidator.validate_discord_id(player_id)
        if quest_date is None:
            quest_date = date.today()

        self.log_operation(
            "get_daily_quests",
            player_id=player_id,
            quest_date=str(quest_date),
        )

        async with DatabaseService.get_session() as session:
            from src.database.models.progression.daily_quest import DailyQuest

            daily_quest = await self._daily_quest_repo.find_one_where(
                session,
                DailyQuest.player_id == player_id,
                DailyQuest.quest_date == quest_date,
            )

            if not daily_quest:
                raise NotFoundError(
                    "DailyQuest", f"player_id={player_id}, date={quest_date}"
                )

            # Calculate if all quests are complete
            all_complete = (
                all(daily_quest.quests_completed.values())
                if daily_quest.quests_completed
                else False
            )

            return {
                "player_id": daily_quest.player_id,
                "quest_date": str(daily_quest.quest_date),
                "quests_completed": daily_quest.quests_completed,
                "quest_progress": daily_quest.quest_progress,
                "rewards_claimed": daily_quest.rewards_claimed,
                "bonus_streak": daily_quest.bonus_streak,
                "all_complete": all_complete,
            }

    # ========================================================================
    # PUBLIC API - Write Operations
    # ========================================================================

    async def get_or_create_today_quests(
        self,
        player_id: int,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get or create today's daily quest record for a player.

        This is a **write operation** using get_transaction() to create if needed.

        Automatically generates a new quest set if one doesn't exist for today.

        Args:
            player_id: Discord ID of the player
            context: Optional command/system context

        Returns:
            Dict containing today's quest record

        Example:
            >>> quests = await service.get_or_create_today_quests(123)
        """
        player_id = InputValidator.validate_discord_id(player_id)
        today = date.today()

        self.log_operation("get_or_create_today_quests", player_id=player_id)

        async with DatabaseService.get_transaction() as session:
            from src.database.models.progression.daily_quest import DailyQuest

            # Try to find existing record
            daily_quest = await self._daily_quest_repo.find_one_where(
                session,
                DailyQuest.player_id == player_id,
                DailyQuest.quest_date == today,
            )

            if daily_quest:
                # Already exists, return it
                all_complete = (
                    all(daily_quest.quests_completed.values())
                    if daily_quest.quests_completed
                    else False
                )

                return {
                    "player_id": daily_quest.player_id,
                    "quest_date": str(daily_quest.quest_date),
                    "quests_completed": daily_quest.quests_completed,
                    "quest_progress": daily_quest.quest_progress,
                    "rewards_claimed": daily_quest.rewards_claimed,
                    "bonus_streak": daily_quest.bonus_streak,
                    "all_complete": all_complete,
                }

            # Generate new quest set
            quest_definitions = self.get_config("daily_quests.quest_pool", default=[])
            if not quest_definitions:
                raise ValidationError("quest_pool", "not configured")

            # Initialize quest state
            quests_completed = {q["id"]: False for q in quest_definitions}
            quest_progress = {q["id"]: 0 for q in quest_definitions}

            # Get previous day's streak
            from sqlalchemy import desc, select

            stmt = (
                select(DailyQuest)
                .where(DailyQuest.player_id == player_id)
                .order_by(desc(DailyQuest.quest_date))
                .limit(1)
            )
            result = await session.execute(stmt)
            previous_quest = result.scalar_one_or_none()

            # Calculate streak
            bonus_streak = 0
            if previous_quest:
                # Check if previous day was completed
                prev_all_complete = (
                    all(previous_quest.quests_completed.values())
                    if previous_quest.quests_completed
                    else False
                )

                # Check if it was yesterday (consecutive)
                from datetime import timedelta

                yesterday = today - timedelta(days=1)
                if prev_all_complete and previous_quest.quest_date == yesterday:
                    bonus_streak = previous_quest.bonus_streak + 1

            # Create new daily quest record
            daily_quest = DailyQuest(
                player_id=player_id,
                quest_date=today,
                quests_completed=quests_completed,
                quest_progress=quest_progress,
                rewards_claimed=False,
                bonus_streak=bonus_streak,
            )

            session.add(daily_quest)

            # Audit logging
            await AuditLogger.log(
                player_id=player_id,
                transaction_type="daily_quests_generated",
                details={
                    "quest_date": str(today),
                    "quest_count": len(quest_definitions),
                    "bonus_streak": bonus_streak,
                },
                context=context,
            )

            # Event emission
            await self.emit_event(
                event_type="daily_quest.generated",
                data={
                    "player_id": player_id,
                    "quest_date": str(today),
                    "bonus_streak": bonus_streak,
                },
            )

            self.log.info(
                f"Daily quests generated for player {player_id} (streak: {bonus_streak})",
                extra={
                    "player_id": player_id,
                    "quest_date": str(today),
                    "bonus_streak": bonus_streak,
                },
            )

            return {
                "player_id": daily_quest.player_id,
                "quest_date": str(daily_quest.quest_date),
                "quests_completed": daily_quest.quests_completed,
                "quest_progress": daily_quest.quest_progress,
                "rewards_claimed": daily_quest.rewards_claimed,
                "bonus_streak": daily_quest.bonus_streak,
                "all_complete": False,
            }

    async def update_quest_progress(
        self,
        player_id: int,
        quest_id: str,
        progress_amount: int = 1,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Update progress for a specific quest.

        This is a **write operation** using get_transaction() with pessimistic locking.

        Automatically completes the quest when progress reaches the goal.

        Args:
            player_id: Discord ID of the player
            quest_id: Quest identifier
            progress_amount: Amount to increment (default 1)
            context: Optional command/system context

        Returns:
            Dict containing:
                - quest_id: Quest identifier
                - old_progress: Previous progress value
                - new_progress: Updated progress value
                - goal: Quest goal from config
                - is_complete: Whether quest is now complete

        Raises:
            NotFoundError: If no daily quest record exists for today
            ValidationError: If quest_id is invalid or progress_amount is invalid
            BusinessRuleViolation: If quest is already completed

        Example:
            >>> result = await service.update_quest_progress(
            ...     player_id=123,
            ...     quest_id="defeat_10_enemies",
            ...     progress_amount=1,
            ...     context="/battle"
            ... )
        """
        player_id = InputValidator.validate_discord_id(player_id)
        quest_id = InputValidator.validate_string(
            quest_id, field_name="quest_id", min_length=1, max_length=100
        )
        progress_amount = InputValidator.validate_positive_integer(
            progress_amount, field_name="progress_amount"
        )

        self.log_operation(
            "update_quest_progress",
            player_id=player_id,
            quest_id=quest_id,
            progress_amount=progress_amount,
        )

        # Get quest configuration
        quest_pool = self.get_config("daily_quests.quest_pool", default=[])
        quest_config = next((q for q in quest_pool if q["id"] == quest_id), None)
        if not quest_config:
            raise ValidationError("quest_id", f"Invalid: {quest_id}")

        quest_goal = quest_config.get("goal", 1)

        today = date.today()

        async with DatabaseService.get_transaction() as session:
            from src.database.models.progression.daily_quest import DailyQuest

            # Lock daily quest record
            daily_quest = await self._daily_quest_repo.find_one_where(
                session,
                DailyQuest.player_id == player_id,
                DailyQuest.quest_date == today,
                for_update=True,
            )

            if not daily_quest:
                raise NotFoundError("DailyQuest", f"player_id={player_id}, date={today}")

            # Check if already completed
            if daily_quest.quests_completed.get(quest_id, False):
                raise InvalidOperationError("complete_quest", f"Quest '{quest_id}' is already completed")

            # Update progress
            old_progress = daily_quest.quest_progress.get(quest_id, 0)
            new_progress = old_progress + progress_amount

            daily_quest.quest_progress[quest_id] = new_progress
            flag_modified(daily_quest, "quest_progress")

            # Check if quest is now complete
            is_complete = new_progress >= quest_goal

            if is_complete:
                daily_quest.quests_completed[quest_id] = True
                flag_modified(daily_quest, "quests_completed")

                # Event emission for quest completion
                await self.emit_event(
                    event_type="daily_quest.quest_completed",
                    data={
                        "player_id": player_id,
                        "quest_id": quest_id,
                        "progress": new_progress,
                        "goal": quest_goal,
                    },
                )

            # Audit logging
            await AuditLogger.log(
                player_id=player_id,
                transaction_type="daily_quest_progress_updated",
                details={
                    "quest_id": quest_id,
                    "old_progress": old_progress,
                    "new_progress": new_progress,
                    "progress_amount": progress_amount,
                    "is_complete": is_complete,
                },
                context=context,
            )

            self.log.info(
                f"Quest progress updated: {quest_id} ({old_progress} -> {new_progress}/{quest_goal})",
                extra={
                    "player_id": player_id,
                    "quest_id": quest_id,
                    "old_progress": old_progress,
                    "new_progress": new_progress,
                    "is_complete": is_complete,
                },
            )

            return {
                "quest_id": quest_id,
                "old_progress": old_progress,
                "new_progress": new_progress,
                "goal": quest_goal,
                "is_complete": is_complete,
            }

    async def claim_daily_rewards(
        self,
        player_id: int,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Claim rewards for all completed daily quests.

        This is a **write operation** using get_transaction() with pessimistic locking.

        Args:
            player_id: Discord ID of the player
            context: Optional command/system context

        Returns:
            Dict containing:
                - player_id: Player's Discord ID
                - quests_completed_count: Number of completed quests
                - base_rewards: Base reward data
                - streak_bonus: Streak bonus data
                - total_rewards: Combined rewards

        Raises:
            NotFoundError: If no daily quest record exists for today
            BusinessRuleViolation: If no quests completed or rewards already claimed

        Example:
            >>> rewards = await service.claim_daily_rewards(
            ...     player_id=123,
            ...     context="/daily claim"
            ... )
        """
        player_id = InputValidator.validate_discord_id(player_id)

        self.log_operation("claim_daily_rewards", player_id=player_id)

        today = date.today()

        # SAFETY: Observability - Wrap in try-except for error path logging
        try:
            async with DatabaseService.get_transaction() as session:
                from src.database.models.progression.daily_quest import DailyQuest

                # Lock daily quest record
                daily_quest = await self._daily_quest_repo.find_one_where(
                    session,
                    DailyQuest.player_id == player_id,
                    DailyQuest.quest_date == today,
                    for_update=True,
                )

                if not daily_quest:
                    raise NotFoundError("DailyQuest", f"player_id={player_id}, date={today}")

                # SAFETY: idempotency - Check if rewards already claimed (with pessimistic lock)
                # This prevents duplicate reward claims even under concurrent requests
                if daily_quest.rewards_claimed:
                    raise InvalidOperationError("claim_rewards", "Daily quest rewards already claimed")

                # Check if any quests are completed
                completed_count = sum(
                    1 for completed in daily_quest.quests_completed.values() if completed
                )

                if completed_count == 0:
                    raise InvalidOperationError("claim_rewards", "No quests completed yet")

                # Get reward configuration
                base_rewards = self.get_config("daily_quests.base_rewards", default={})
                streak_bonus_pct = self.get_config(
                    "daily_quests.streak_bonus_pct", default=0.1
                )

                # Calculate total rewards
                # Apply streak bonus if applicable
                streak_multiplier = 1.0 + (daily_quest.bonus_streak * streak_bonus_pct)

                # SAFETY: Atomicity - Distribute rewards within same transaction
                # Calculate final reward amounts
                final_rewards = {}
                for reward_type, base_amount in base_rewards.items():
                    final_amount = int(base_amount * streak_multiplier)
                    final_rewards[reward_type] = final_amount

                    # Distribute rewards based on type
                    if reward_type == "lumees":
                        await self._player_currencies.add_resource(
                            player_id=player_id,
                            resource_type="lumees",
                            amount=final_amount,
                            reason="daily_quest_completion",
                            context=f"completed_{completed_count}_quests",
                            session=session,  # SAFETY: Pass session for atomicity
                        )
                    elif reward_type == "xp":
                        await self._player_progression.add_xp(
                            player_id=player_id,
                            xp_amount=final_amount,
                            reason="daily_quest_completion",
                            context=f"completed_{completed_count}_quests",
                            session=session,  # SAFETY: Pass session for atomicity
                        )
                    elif reward_type == "auric_coin":
                        await self._player_currencies.add_resource(
                            player_id=player_id,
                            resource_type="auric_coin",
                            amount=final_amount,
                            reason="daily_quest_completion",
                            context=f"completed_{completed_count}_quests",
                            session=session,  # SAFETY: Pass session for atomicity
                        )

                # SAFETY: idempotency - Mark rewards as claimed to prevent duplicate claims
                daily_quest.rewards_claimed = True

                # Audit logging
                await AuditLogger.log(
                    player_id=player_id,
                    transaction_type="daily_quest_rewards_claimed",
                    details={
                        "quests_completed": completed_count,
                        "base_rewards": base_rewards,
                        "final_rewards": final_rewards,
                        "bonus_streak": daily_quest.bonus_streak,
                        "streak_multiplier": streak_multiplier,
                    },
                    context=context,
                )

            # Event emission (outside transaction)
            await self.emit_event(
                event_type="daily_quest.rewards_claimed",
                data={
                    "player_id": player_id,
                    "quests_completed": completed_count,
                    "bonus_streak": daily_quest.bonus_streak,
                    "base_rewards": base_rewards,
                    "final_rewards": final_rewards,
                },
            )

            # SAFETY: observability - Log success with full economic context
            self.log.info(
                f"Daily quest rewards claimed by player {player_id} ({completed_count} quests, {daily_quest.bonus_streak} streak)",
                extra={
                    "player_id": player_id,
                    "quests_completed": completed_count,
                    "bonus_streak": daily_quest.bonus_streak,
                    "base_rewards": base_rewards,
                    "final_rewards": final_rewards,
                    "streak_multiplier": streak_multiplier,
                    "success": True,  # SAFETY: Explicit success flag
                    "error": None,  # SAFETY: Explicit null error
                    "reason": "daily_quest_completion",
                },
            )

            return {
                "player_id": player_id,
                "quests_completed_count": completed_count,
                "base_rewards": base_rewards,
                "final_rewards": final_rewards,
                "streak_bonus": daily_quest.bonus_streak,
                "streak_multiplier": streak_multiplier,
            }

        except Exception as e:
            # SAFETY: Observability - Exception path logging
            self.log.error(
                f"Failed to claim daily quest rewards: {e}",
                extra={
                    "player_id": player_id,
                    "reason": "daily_quest_completion",
                    "success": False,  # SAFETY: Explicit failure flag
                    "error": str(e),  # SAFETY: Explicit error message
                },
                exc_info=True,
            )
            raise
