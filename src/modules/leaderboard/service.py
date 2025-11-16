"""
Leaderboard Service - LES 2025 Compliant
=========================================

Purpose
-------
Manages leaderboard snapshot generation, ranking computation, and leaderboard queries
with support for multiple categories and rank change tracking.

Domain
------
- Generate leaderboard snapshots
- Compute rankings for different categories
- Sort and calculate rank changes
- Query top players by category
- Handle leaderboard expiration and cleanup
- Format rank display with change indicators

LUMEN 2025 COMPLIANCE
---------------------
✓ Pure business logic - no Discord dependencies
✓ Transaction-safe - all writes in atomic transactions
✓ Config-driven - category definitions from config
✓ Domain exceptions - raises NotFoundError, ValidationError
✓ Event-driven - emits leaderboard.* events
✓ Observable - structured logging
✓ Efficient queries - optimized for leaderboard rankings
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from sqlalchemy import desc, select

from src.core.database.service import DatabaseService
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
    from src.database.models.progression.leaderboard import LeaderboardSnapshot


# ============================================================================
# Repository
# ============================================================================


class LeaderboardSnapshotRepository(BaseRepository["LeaderboardSnapshot"]):
    """Repository for LeaderboardSnapshot model."""

    pass


# ============================================================================
# LeaderboardService
# ============================================================================


class LeaderboardService(BaseService):
    """
    Service for managing leaderboard snapshots and rankings.

    Handles snapshot generation, ranking queries, and leaderboard display
    with support for multiple categories and rank change tracking.

    Public Methods
    --------------
    - get_leaderboard() -> Get top players for a category
    - get_player_rank() -> Get specific player's rank in a category
    - update_player_snapshot() -> Update player's leaderboard entry
    - generate_category_snapshot() -> Regenerate entire category leaderboard
    - get_rank_display() -> Format rank with change indicator
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        """
        Initialize LeaderboardService with required dependencies.

        Args:
            config_manager: Application configuration manager
            event_bus: Event bus for cross-module communication
            logger: Structured logger instance
        """
        super().__init__(config_manager, event_bus, logger)

        from src.database.models.progression.leaderboard import LeaderboardSnapshot

        self._leaderboard_repo = LeaderboardSnapshotRepository(
            model_class=LeaderboardSnapshot,
            logger=get_logger(f"{__name__}.LeaderboardSnapshotRepository"),
        )

    # ========================================================================
    # PUBLIC API - Read Operations
    # ========================================================================

    async def get_leaderboard(
        self,
        category: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Get top players for a leaderboard category.

        This is a **read-only** operation using get_session().

        Args:
            category: Leaderboard category (e.g., "ascension", "collection", "wealth")
            limit: Maximum number of entries to return
            offset: Number of entries to skip

        Returns:
            List of leaderboard entries, each containing:
                - rank: Player's current rank
                - player_id: Player's Discord ID
                - username: Player's username
                - value: Leaderboard value (e.g., highest floor, total maidens)
                - rank_change: Change from previous snapshot
                - snapshot_version: Snapshot version number

        Raises:
            ValidationError: If category is invalid or limit/offset are invalid

        Example:
            >>> leaderboard = await service.get_leaderboard("ascension", limit=10)
            >>> for entry in leaderboard:
            ...     print(f"{entry['rank']}. {entry['username']}: {entry['value']}")
        """
        category = self._validate_category(category)
        limit = InputValidator.validate_positive_integer(limit, field_name="limit")

        if limit > 100:
            raise ValidationError("limit", "Limit cannot exceed 100")

        if offset < 0:
            raise ValidationError("offset", "Offset cannot be negative")

        self.log_operation(
            "get_leaderboard",
            category=category,
            limit=limit,
            offset=offset,
        )

        async with DatabaseService.get_session() as session:
            from src.database.models.progression.leaderboard import (
                LeaderboardSnapshot,
            )

            # Query leaderboard ordered by rank
            stmt = (
                select(LeaderboardSnapshot)
                .where(LeaderboardSnapshot.category == category)
                .order_by(LeaderboardSnapshot.rank)
                .limit(limit)
                .offset(offset)
            )

            result = await session.execute(stmt)
            snapshots = result.scalars().all()

            return [
                {
                    "rank": snapshot.rank,
                    "player_id": snapshot.player_id,
                    "username": snapshot.username,
                    "value": snapshot.value,
                    "rank_change": snapshot.rank_change,
                    "snapshot_version": snapshot.snapshot_version,
                }
                for snapshot in snapshots
            ]

    async def get_player_rank(
        self, player_id: int, category: str
    ) -> Dict[str, Any]:
        """
        Get a specific player's rank in a category.

        This is a **read-only** operation using get_session().

        Args:
            player_id: Discord ID of the player
            category: Leaderboard category

        Returns:
            Dict containing:
                - rank: Player's current rank
                - player_id: Player's Discord ID
                - username: Player's username
                - value: Leaderboard value
                - rank_change: Change from previous snapshot
                - category: Leaderboard category

        Raises:
            NotFoundError: If player not found in leaderboard

        Example:
            >>> rank = await service.get_player_rank(123, "ascension")
            >>> print(f"Rank #{rank['rank']}")
        """
        player_id = InputValidator.validate_discord_id(player_id)
        category = self._validate_category(category)

        self.log_operation(
            "get_player_rank",
            player_id=player_id,
            category=category,
        )

        async with DatabaseService.get_session() as session:
            from src.database.models.progression.leaderboard import (
                LeaderboardSnapshot,
            )

            snapshot = await self._leaderboard_repo.find_one_where(
                session,
                LeaderboardSnapshot.player_id == player_id,
                LeaderboardSnapshot.category == category,
            )

            if not snapshot:
                raise NotFoundError(
                    "LeaderboardSnapshot",
                    f"player_id={player_id}, category={category}",
                )

            return {
                "rank": snapshot.rank,
                "player_id": snapshot.player_id,
                "username": snapshot.username,
                "value": snapshot.value,
                "rank_change": snapshot.rank_change,
                "category": snapshot.category,
            }

    # ========================================================================
    # PUBLIC API - Write Operations
    # ========================================================================

    async def update_player_snapshot(
        self,
        player_id: int,
        username: str,
        category: str,
        value: int,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Update or create a player's leaderboard snapshot entry.

        This is a **write operation** using get_transaction().

        Note: This updates the individual entry but does NOT recalculate ranks
        across the entire leaderboard. Use generate_category_snapshot() for that.

        Args:
            player_id: Discord ID of the player
            username: Player's current username
            category: Leaderboard category
            value: New leaderboard value
            context: Optional command/system context

        Returns:
            Dict containing updated snapshot entry

        Raises:
            ValidationError: If inputs are invalid

        Example:
            >>> result = await service.update_player_snapshot(
            ...     player_id=123,
            ...     username="PlayerName",
            ...     category="ascension",
            ...     value=42,
            ...     context="/ascend"
            ... )
        """
        player_id = InputValidator.validate_discord_id(player_id)
        username = InputValidator.validate_string(
            username, field_name="username", min_length=1, max_length=100
        )
        category = self._validate_category(category)

        if value < 0:
            raise ValidationError("value", "Value cannot be negative")

        self.log_operation(
            "update_player_snapshot",
            player_id=player_id,
            category=category,
            value=value,
        )

        async with DatabaseService.get_transaction() as session:
            from src.database.models.progression.leaderboard import (
                LeaderboardSnapshot,
            )

            # Try to find existing snapshot
            snapshot = await self._leaderboard_repo.find_one_where(
                session,
                LeaderboardSnapshot.player_id == player_id,
                LeaderboardSnapshot.category == category,
                for_update=True,
            )

            if snapshot:
                # Update existing
                old_rank = snapshot.rank
                old_value = snapshot.value

                snapshot.username = username
                snapshot.value = value
                # Note: rank and rank_change should be recalculated by generate_category_snapshot()

                self.log.info(
                    f"Leaderboard snapshot updated: {category}",
                    extra={
                        "player_id": player_id,
                        "category": category,
                        "old_value": old_value,
                        "new_value": value,
                    },
                )
            else:
                # Create new snapshot
                # Initially place at rank 0 (unranked)
                # Rank will be calculated by generate_category_snapshot()
                snapshot = LeaderboardSnapshot(
                    player_id=player_id,
                    username=username,
                    category=category,
                    rank=0,
                    rank_change=0,
                    value=value,
                    snapshot_version=1,
                )
                session.add(snapshot)

                self.log.info(
                    f"Leaderboard snapshot created: {category}",
                    extra={
                        "player_id": player_id,
                        "category": category,
                        "value": value,
                    },
                )

            # Event emission
            await self.emit_event(
                event_type="leaderboard.snapshot_updated",
                data={
                    "player_id": player_id,
                    "category": category,
                    "value": value,
                },
            )

            return {
                "player_id": snapshot.player_id,
                "username": snapshot.username,
                "category": snapshot.category,
                "rank": snapshot.rank,
                "value": snapshot.value,
            }

    async def generate_category_snapshot(
        self,
        category: str,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Regenerate rankings for an entire leaderboard category.

        This is a **write operation** using get_transaction().

        Recalculates all ranks based on current values and updates rank_change
        based on previous ranks.

        Args:
            category: Leaderboard category to regenerate
            context: Optional command/system context

        Returns:
            Dict containing:
                - category: Leaderboard category
                - total_entries: Number of entries ranked
                - snapshot_version: New snapshot version number

        Example:
            >>> result = await service.generate_category_snapshot("ascension")
            >>> print(f"Ranked {result['total_entries']} players")
        """
        category = self._validate_category(category)

        self.log_operation("generate_category_snapshot", category=category)

        async with DatabaseService.get_transaction() as session:
            from src.database.models.progression.leaderboard import (
                LeaderboardSnapshot,
            )

            # Get all snapshots for this category, ordered by value descending
            stmt = (
                select(LeaderboardSnapshot)
                .where(LeaderboardSnapshot.category == category)
                .order_by(desc(LeaderboardSnapshot.value))
                .with_for_update()
            )

            result = await session.execute(stmt)
            snapshots = result.scalars().all()

            # Calculate new ranks
            new_version = 1
            if snapshots:
                new_version = max(s.snapshot_version for s in snapshots) + 1

            for i, snapshot in enumerate(snapshots, start=1):
                old_rank = snapshot.rank
                new_rank = i

                rank_change = old_rank - new_rank if old_rank > 0 else 0

                snapshot.rank = new_rank
                snapshot.rank_change = rank_change
                snapshot.snapshot_version = new_version

            # Event emission
            await self.emit_event(
                event_type="leaderboard.category_regenerated",
                data={
                    "category": category,
                    "total_entries": len(snapshots),
                    "snapshot_version": new_version,
                },
            )

            self.log.info(
                f"Leaderboard category regenerated: {category}",
                extra={
                    "category": category,
                    "total_entries": len(snapshots),
                    "snapshot_version": new_version,
                },
            )

            return {
                "category": category,
                "total_entries": len(snapshots),
                "snapshot_version": new_version,
            }

    # ========================================================================
    # PRIVATE HELPERS
    # ========================================================================

    def _validate_category(self, category: str) -> str:
        """
        Validate leaderboard category against allowed categories.

        Args:
            category: Category to validate

        Returns:
            Validated category (lowercased)

        Raises:
            ValidationError: If category is invalid
        """
        category = InputValidator.validate_string(
            category, field_name="category", min_length=1, max_length=50
        ).lower()

        valid_categories = self.get_config(
            "leaderboards.categories",
            default=["ascension", "collection", "wealth", "combat"],
        )

        if category not in valid_categories:
            raise ValidationError(
                "category",
                f"Invalid leaderboard category: {category}. "
                f"Valid categories: {', '.join(valid_categories)}"
            )

        return category

    def _format_rank_change(self, rank_change: int) -> str:
        """
        Format rank change with arrow indicator.

        Args:
            rank_change: Rank change value (positive = moved up, negative = moved down)

        Returns:
            Formatted string (e.g., "↑5", "↓2", "−")
        """
        if rank_change > 0:
            return f"↑{rank_change}"
        elif rank_change < 0:
            return f"↓{abs(rank_change)}"
        else:
            return "−"
