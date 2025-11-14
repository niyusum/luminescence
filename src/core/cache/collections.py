"""
Collection caching operations for Lumen (2025).

Purpose
-------
- Cache maiden collections for players.
- Cache fusion rates and leader bonuses (global collections).
- Cache daily quests and drop charges.
- Cache leaderboards.

Responsibilities
----------------
- Maiden collection caching with TTL management.
- Global collection caching (fusion, leader bonuses).
- Daily quest and drop charge caching.
- Leaderboard caching.

Non-Responsibilities
--------------------
- Player-specific resources (handled by player module).
- Batch operations (handled by operations module).
- Metrics tracking (handled by metrics module).

Lumen 2025 Compliance
---------------------
- **Config-driven**: TTLs managed via ConfigManager (Article V).
- **Observability**: Structured logging for all operations (Article X).
- **Graceful degradation**: Handles Redis failures gracefully (Article IX).

Architecture Notes
------------------
- Uses RedisService for storage backend.
- Longer TTLs for rarely-changing data (fusion rates, leader bonuses).
- Shorter TTLs for frequently-updated data (leaderboards).

Dependencies
------------
- RedisService for Redis operations.
- ConfigManager for TTL configuration.
- CacheMetrics for metrics tracking.
- Logger for structured logging.
"""

import time
from typing import Any, Dict, Optional

from src.core.cache.metrics import CacheMetrics
from src.core.config import ConfigManager
from src.core.logging.logger import get_logger
from src.core.redis.service import RedisService

logger = get_logger(__name__)


class CollectionCache:
    """Collection caching operations."""

    # Key templates
    MAIDEN_COLLECTION_KEY = "lumen:v1:player:{player_id}:maidens"
    FUSION_RATES_KEY = "lumen:v1:fusion:rates:{tier}"
    LEADER_BONUSES_KEY = "lumen:v1:leader:{maiden_base_id}:{tier}"
    DAILY_QUEST_KEY = "lumen:v1:daily:{player_id}:{date}"
    DROP_CHARGES_KEY = "lumen:v1:drop:{player_id}"
    LEADERBOARDS_KEY = "lumen:v1:leaderboard:{type}:{period}"

    @classmethod
    def _get_ttl(cls, cache_type: str) -> int:
        """
        Get TTL for specific cache type from ConfigManager.

        Parameters
        ----------
        cache_type:
            Cache type (maiden_collection, fusion_rates, etc.).

        Returns
        -------
        int
            TTL in seconds from config or sensible default.
        """
        defaults = {
            "maiden_collection": 300,  # 5 minutes
            "fusion_rates": 3600,  # 1 hour (rarely changes)
            "leader_bonuses": 3600,  # 1 hour (rarely changes)
            "daily_quest": 86400,  # 24 hours
            "DROP_CHARGES": 300,  # 5 minutes
            "leaderboards": 600,  # 10 minutes
        }

        config_key = f"cache.ttl.{cache_type}"
        return ConfigManager.get(config_key, defaults.get(cache_type, 300))

    # =========================================================================
    # MAIDEN COLLECTION CACHING
    # =========================================================================

    @classmethod
    async def cache_maiden_collection(
        cls,
        player_id: int,
        collection_data: Dict[str, Any],
        ttl: Optional[int] = None,
    ) -> bool:
        """
        Cache player's maiden collection.

        Parameters
        ----------
        player_id:
            Player's Discord ID.
        collection_data:
            Maiden collection data.
        ttl:
            Optional TTL override (uses ConfigManager default if None).

        Returns
        -------
        bool
            True if cached successfully.
        """
        start_time = time.perf_counter()
        key = cls.MAIDEN_COLLECTION_KEY.format(player_id=player_id)

        # Get TTL from ConfigManager if not provided
        if ttl is None:
            ttl = cls._get_ttl("maiden_collection")

        try:
            success = await RedisService.set(key, collection_data, ttl=ttl)

            if success:
                CacheMetrics.record_set()

                elapsed_ms = (time.perf_counter() - start_time) * 1000
                CacheMetrics.record_set_time(elapsed_ms)

                logger.debug(
                    f"Cached maiden collection: player={player_id} ttl={ttl}s "
                    f"time={elapsed_ms:.2f}ms"
                )

            return success

        except Exception as e:
            CacheMetrics.record_error()
            logger.error(
                f"Failed to cache maiden collection: player={player_id} error={e}",
                exc_info=True,
            )
            return False

    @classmethod
    async def get_cached_maiden_collection(
        cls, player_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Get cached maiden collection.

        Parameters
        ----------
        player_id:
            Player's Discord ID.

        Returns
        -------
        Optional[Dict[str, Any]]
            Cached collection data or None.
        """
        start_time = time.perf_counter()
        key = cls.MAIDEN_COLLECTION_KEY.format(player_id=player_id)

        try:
            data = await RedisService.get(key)

            elapsed_ms = (time.perf_counter() - start_time) * 1000
            CacheMetrics.record_get_time(elapsed_ms)

            if data:
                CacheMetrics.record_hit()
                logger.debug(
                    f"Cache HIT: maiden_collection player={player_id} time={elapsed_ms:.2f}ms"
                )
                return data
            else:
                CacheMetrics.record_miss()
                logger.debug(
                    f"Cache MISS: maiden_collection player={player_id} time={elapsed_ms:.2f}ms"
                )
                return None

        except Exception as e:
            CacheMetrics.record_error()
            CacheMetrics.record_miss()
            logger.error(
                f"Error getting cached maiden collection: player={player_id} error={e}",
                exc_info=True,
            )
            return None

    # =========================================================================
    # FUSION RATES CACHING
    # =========================================================================

    @classmethod
    async def cache_fusion_rates(
        cls, tier: str, rates_data: Dict[str, Any], ttl: Optional[int] = None
    ) -> bool:
        """
        Cache fusion rates for a tier.

        Parameters
        ----------
        tier:
            Tier identifier.
        rates_data:
            Fusion rates data.
        ttl:
            Optional TTL override (uses ConfigManager default if None).

        Returns
        -------
        bool
            True if cached successfully.
        """
        key = cls.FUSION_RATES_KEY.format(tier=tier)

        if ttl is None:
            ttl = cls._get_ttl("fusion_rates")

        try:
            success = await RedisService.set(key, rates_data, ttl=ttl)

            if success:
                CacheMetrics.record_set()
                logger.debug(f"Cached fusion rates: tier={tier} ttl={ttl}s")

            return success

        except Exception as e:
            CacheMetrics.record_error()
            logger.error(
                f"Failed to cache fusion rates: tier={tier} error={e}", exc_info=True
            )
            return False

    @classmethod
    async def get_cached_fusion_rates(cls, tier: str) -> Optional[Dict[str, Any]]:
        """
        Get cached fusion rates.

        Parameters
        ----------
        tier:
            Tier identifier.

        Returns
        -------
        Optional[Dict[str, Any]]
            Cached rates data or None.
        """
        key = cls.FUSION_RATES_KEY.format(tier=tier)

        try:
            data = await RedisService.get(key)

            if data:
                CacheMetrics.record_hit()
                logger.debug(f"Cache HIT: fusion_rates tier={tier}")
                return data
            else:
                CacheMetrics.record_miss()
                logger.debug(f"Cache MISS: fusion_rates tier={tier}")
                return None

        except Exception as e:
            CacheMetrics.record_error()
            CacheMetrics.record_miss()
            logger.error(
                f"Error getting cached fusion rates: tier={tier} error={e}",
                exc_info=True,
            )
            return None

    # =========================================================================
    # LEADER BONUSES CACHING
    # =========================================================================

    @classmethod
    async def cache_leader_bonuses(
        cls,
        maiden_base_id: int,
        tier: str,
        bonuses_data: Dict[str, Any],
        ttl: Optional[int] = None,
    ) -> bool:
        """
        Cache leader bonuses for a maiden.

        Parameters
        ----------
        maiden_base_id:
            Maiden base ID.
        tier:
            Tier identifier.
        bonuses_data:
            Leader bonuses data.
        ttl:
            Optional TTL override (uses ConfigManager default if None).

        Returns
        -------
        bool
            True if cached successfully.
        """
        key = cls.LEADER_BONUSES_KEY.format(maiden_base_id=maiden_base_id, tier=tier)

        if ttl is None:
            ttl = cls._get_ttl("leader_bonuses")

        try:
            success = await RedisService.set(key, bonuses_data, ttl=ttl)

            if success:
                CacheMetrics.record_set()
                logger.debug(
                    f"Cached leader bonuses: maiden={maiden_base_id} tier={tier} ttl={ttl}s"
                )

            return success

        except Exception as e:
            CacheMetrics.record_error()
            logger.error(
                f"Failed to cache leader bonuses: maiden={maiden_base_id} tier={tier} error={e}",
                exc_info=True,
            )
            return False

    @classmethod
    async def get_cached_leader_bonuses(
        cls, maiden_base_id: int, tier: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get cached leader bonuses.

        Parameters
        ----------
        maiden_base_id:
            Maiden base ID.
        tier:
            Tier identifier.

        Returns
        -------
        Optional[Dict[str, Any]]
            Cached bonuses data or None.
        """
        key = cls.LEADER_BONUSES_KEY.format(maiden_base_id=maiden_base_id, tier=tier)

        try:
            data = await RedisService.get(key)

            if data:
                CacheMetrics.record_hit()
                logger.debug(f"Cache HIT: leader_bonuses maiden={maiden_base_id} tier={tier}")
                return data
            else:
                CacheMetrics.record_miss()
                logger.debug(
                    f"Cache MISS: leader_bonuses maiden={maiden_base_id} tier={tier}"
                )
                return None

        except Exception as e:
            CacheMetrics.record_error()
            CacheMetrics.record_miss()
            logger.error(
                f"Error getting cached leader bonuses: maiden={maiden_base_id} tier={tier} error={e}",
                exc_info=True,
            )
            return None

    # =========================================================================
    # DROP CHARGES CACHING
    # =========================================================================

    @classmethod
    async def cache_drop_charges(
        cls, player_id: int, charges_data: Dict[str, Any], ttl: Optional[int] = None
    ) -> bool:
        """
        Cache player's drop charges.

        Parameters
        ----------
        player_id:
            Player's Discord ID.
        charges_data:
            Drop charges data.
        ttl:
            Optional TTL override (uses ConfigManager default if None).

        Returns
        -------
        bool
            True if cached successfully.
        """
        key = cls.DROP_CHARGES_KEY.format(player_id=player_id)

        if ttl is None:
            ttl = cls._get_ttl("DROP_CHARGES")

        try:
            success = await RedisService.set(key, charges_data, ttl=ttl)

            if success:
                CacheMetrics.record_set()
                logger.debug(f"Cached drop charges: player={player_id} ttl={ttl}s")

            return success

        except Exception as e:
            CacheMetrics.record_error()
            logger.error(
                f"Failed to cache drop charges: player={player_id} error={e}",
                exc_info=True,
            )
            return False

    @classmethod
    async def get_cached_drop_charges(
        cls, player_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Get cached drop charges.

        Parameters
        ----------
        player_id:
            Player's Discord ID.

        Returns
        -------
        Optional[Dict[str, Any]]
            Cached charges data or None.
        """
        key = cls.DROP_CHARGES_KEY.format(player_id=player_id)

        try:
            data = await RedisService.get(key)

            if data:
                CacheMetrics.record_hit()
                logger.debug(f"Cache HIT: drop_charges player={player_id}")
                return data
            else:
                CacheMetrics.record_miss()
                logger.debug(f"Cache MISS: drop_charges player={player_id}")
                return None

        except Exception as e:
            CacheMetrics.record_error()
            CacheMetrics.record_miss()
            logger.error(
                f"Error getting cached drop charges: player={player_id} error={e}",
                exc_info=True,
            )
            return None
