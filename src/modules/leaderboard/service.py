"""
Leaderboard ranking system with cached snapshots.

Provides real-time ranking queries and periodic snapshot updates for performance.
Supports multiple ranking categories: power, level, ascension, fusion count, etc.

LUMEN LAW Compliance:
    - Article III: Pure business logic service (no Discord dependencies)
    - Article IV: Ranking categories configurable
    - Article VII: Stateless @staticmethod pattern
"""

from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from datetime import datetime, timedelta

from src.database.models.core.player import Player
from src.database.models.progression.leaderboard import LeaderboardSnapshot
from src.core.config import ConfigManager
from src.core.logging.logger import get_logger

logger = get_logger(__name__)


class LeaderboardService:
    """
    Leaderboard ranking system with snapshot caching.

    Supports multiple ranking categories with periodic snapshot updates
    to avoid expensive real-time queries.
    """

    # Available ranking categories
    CATEGORIES = {
        "total_power": {
            "name": "Total Power",
            "field": "total_power",
            "icon": "⚔️",
            "format": "{:,}"
        },
        "level": {
            "name": "Level",
            "field": "level",
            "icon": "📊",
            "format": "{:,}"
        },
        "highest_floor": {
            "name": "Ascension Floor",
            "field": "highest_floor",
            "icon": "🏰",
            "format": "Floor {:,}"
        },
        "total_fusions": {
            "name": "Fusions Performed",
            "field": "total_fusions",
            "icon": "🔥",
            "format": "{:,}"
        },
        "lumees": {
            "name": "Wealth (Lumees)",
            "field": "lumees",
            "icon": "💰",
            "format": "{:,}"
        }
    }

    # ========================================================================
    # REAL-TIME RANKING (Expensive - Use Sparingly)
    # ========================================================================

    @staticmethod
    async def get_realtime_rank(
        session: AsyncSession,
        player_id: int,
        category: str
    ) -> Dict[str, Any]:
        """
        Calculate player's current rank in real-time.

        WARNING: Expensive operation. Use get_cached_rank() when possible.

        Args:
            session: Database session
            player_id: Player's Discord ID
            category: Ranking category

        Returns:
            {
                "player_id": int,
                "rank": int,
                "value": int,
                "total_players": int,
                "category": str,
                "percentile": float
            }

        Raises:
            ValueError: Invalid category
        """
        if category not in LeaderboardService.CATEGORIES:
            raise ValueError(f"Invalid category: {category}")

        category_info = LeaderboardService.CATEGORIES[category]
        field_name = category_info["field"]

        # Get player's value
        player = await session.get(Player, player_id)
        if not player:
            raise ValueError(f"Player {player_id} not found")

        player_value = getattr(player, field_name)

        # Count players with higher values
        stmt = select(func.count()).select_from(Player).where(
            getattr(Player, field_name) > player_value
        )
        rank = (await session.execute(stmt)).scalar_one() + 1

        # Get total players
        stmt = select(func.count()).select_from(Player)
        total_players = (await session.execute(stmt)).scalar_one()

        percentile = (rank / total_players * 100) if total_players > 0 else 0.0

        return {
            "player_id": player_id,
            "rank": rank,
            "value": player_value,
            "total_players": total_players,
            "category": category,
            "percentile": percentile
        }

    @staticmethod
    async def get_top_players(
        session: AsyncSession,
        category: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get top N players for a category in real-time.

        Args:
            session: Database session
            category: Ranking category
            limit: Number of top players to return

        Returns:
            List of player data with ranks

        Raises:
            ValueError: Invalid category
        """
        if category not in LeaderboardService.CATEGORIES:
            raise ValueError(f"Invalid category: {category}")

        category_info = LeaderboardService.CATEGORIES[category]
        field_name = category_info["field"]

        # Query top players
        stmt = (
            select(Player)
            .order_by(desc(getattr(Player, field_name)))
            .limit(limit)
        )
        result = await session.execute(stmt)
        players = result.scalars().all()

        # Build results with ranks
        leaderboard = []
        for rank, player in enumerate(players, start=1):
            leaderboard.append({
                "rank": rank,
                "player_id": player.discord_id,
                "username": player.username or "Unknown",
                "value": getattr(player, field_name),
                "level": player.level
            })

        return leaderboard

    # ========================================================================
    # CACHED SNAPSHOTS (Performant)
    # ========================================================================

    @staticmethod
    async def get_cached_rank(
        session: AsyncSession,
        player_id: int,
        category: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get player's cached rank from latest snapshot.

        Args:
            session: Database session
            player_id: Player's Discord ID
            category: Ranking category

        Returns:
            Cached rank data or None if not found
        """
        stmt = select(LeaderboardSnapshot).where(
            LeaderboardSnapshot.player_id == player_id,
            LeaderboardSnapshot.category == category
        ).order_by(desc(LeaderboardSnapshot.updated_at)).limit(1)

        result = await session.execute(stmt)
        snapshot = result.scalar_one_or_none()

        if not snapshot:
            return None

        return {
            "rank": snapshot.rank,
            "value": snapshot.value,
            "rank_change": snapshot.rank_change,
            "updated_at": snapshot.updated_at,
            "category": category
        }

    @staticmethod
    async def get_cached_leaderboard(
        session: AsyncSession,
        category: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get top N players from cached snapshots.

        Args:
            session: Database session
            category: Ranking category
            limit: Number of players to return

        Returns:
            List of cached player rankings
        """
        # Get latest snapshot version
        stmt = (
            select(func.max(LeaderboardSnapshot.snapshot_version))
            .where(LeaderboardSnapshot.category == category)
        )
        latest_version = (await session.execute(stmt)).scalar_one_or_none() or 1

        # Query top players from latest snapshot
        stmt = (
            select(LeaderboardSnapshot)
            .where(
                LeaderboardSnapshot.category == category,
                LeaderboardSnapshot.snapshot_version == latest_version
            )
            .order_by(LeaderboardSnapshot.rank)
            .limit(limit)
        )
        result = await session.execute(stmt)
        snapshots = result.scalars().all()

        return [
            {
                "rank": snap.rank,
                "player_id": snap.player_id,
                "username": snap.username,
                "value": snap.value,
                "rank_change": snap.rank_change
            }
            for snap in snapshots
        ]

    # ========================================================================
    # SNAPSHOT MANAGEMENT (Admin/Background Job)
    # ========================================================================

    @staticmethod
    async def update_leaderboard_snapshot(
        session: AsyncSession,
        category: str
    ) -> int:
        """
        Regenerate leaderboard snapshot for a category.

        Should be called periodically (e.g., every 10 minutes) by a background job.

        Args:
            session: Database session with transaction
            category: Category to update

        Returns:
            Number of players ranked

        Raises:
            ValueError: Invalid category
        """
        if category not in LeaderboardService.CATEGORIES:
            raise ValueError(f"Invalid category: {category}")

        category_info = LeaderboardService.CATEGORIES[category]
        field_name = category_info["field"]

        # Get current snapshot version
        stmt = (
            select(func.max(LeaderboardSnapshot.snapshot_version))
            .where(LeaderboardSnapshot.category == category)
        )
        current_version = (await session.execute(stmt)).scalar_one_or_none() or 0
        new_version = current_version + 1

        # Get old ranks for rank_change calculation
        stmt = (
            select(LeaderboardSnapshot)
            .where(
                LeaderboardSnapshot.category == category,
                LeaderboardSnapshot.snapshot_version == current_version
            )
        )
        result = await session.execute(stmt)
        old_snapshots = {snap.player_id: snap.rank for snap in result.scalars().all()}

        # Query all players ordered by category field
        stmt = (
            select(Player)
            .order_by(desc(getattr(Player, field_name)))
        )
        result = await session.execute(stmt)
        players = result.scalars().all()

        # Create new snapshots
        new_snapshots = []
        for rank, player in enumerate(players, start=1):
            old_rank = old_snapshots.get(player.discord_id)
            rank_change = old_rank - rank if old_rank else 0

            snapshot = LeaderboardSnapshot(
                player_id=player.discord_id,
                username=player.username or f"Player#{player.discord_id}",
                category=category,
                rank=rank,
                rank_change=rank_change,
                value=getattr(player, field_name),
                snapshot_version=new_version,
                updated_at=datetime.utcnow()
            )
            new_snapshots.append(snapshot)

        # Bulk insert
        session.add_all(new_snapshots)
        await session.flush()

        logger.info(
            f"Updated leaderboard snapshot: category={category} version={new_version} players={len(new_snapshots)}"
        )

        return len(new_snapshots)

    @staticmethod
    async def cleanup_old_snapshots(
        session: AsyncSession,
        keep_versions: int = 3
    ) -> int:
        """
        Delete old snapshot versions to save database space.

        Args:
            session: Database session with transaction
            keep_versions: Number of recent versions to keep per category

        Returns:
            Number of snapshots deleted
        """
        deleted_count = 0

        for category in LeaderboardService.CATEGORIES.keys():
            # Get versions to keep
            stmt = (
                select(LeaderboardSnapshot.snapshot_version)
                .where(LeaderboardSnapshot.category == category)
                .distinct()
                .order_by(desc(LeaderboardSnapshot.snapshot_version))
                .limit(keep_versions)
            )
            result = await session.execute(stmt)
            keep_versions_list = [row[0] for row in result.all()]

            if not keep_versions_list:
                continue

            # Delete old versions
            stmt = select(LeaderboardSnapshot).where(
                LeaderboardSnapshot.category == category,
                LeaderboardSnapshot.snapshot_version.not_in(keep_versions_list)
            )
            result = await session.execute(stmt)
            old_snapshots = result.scalars().all()

            for snapshot in old_snapshots:
                await session.delete(snapshot)
                deleted_count += 1

        if deleted_count > 0:
            await session.flush()
            logger.info(f"Cleaned up {deleted_count} old leaderboard snapshots")

        return deleted_count
