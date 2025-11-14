"""
Player-specific caching operations for Lumen (2025).

Purpose
-------
- Cache player resources (lumees, energy, stamina, etc.).
- Cache active player modifiers (income boost, XP boost, etc.).
- Provide player-specific cache invalidation.

Responsibilities
----------------
- Player resource caching with automatic TTL management.
- Active modifier caching for performance optimization.
- Player cache invalidation for data consistency.
- Tag-based tracking for bulk invalidation.

Non-Responsibilities
--------------------
- Batch operations (handled by operations module).
- Metrics tracking (handled by metrics module).
- Generic caching utilities (handled by service module).

Lumen 2025 Compliance
---------------------
- **Config-driven**: TTLs managed via ConfigManager (Article V).
- **Observability**: Structured logging for all operations (Article X).
- **Graceful degradation**: Handles Redis failures gracefully (Article IX).

Architecture Notes
------------------
- Uses RedisService for storage backend.
- Automatic JSON serialization via RedisService.
- Tag-based tracking for invalidation support.
- ConfigManager-driven TTL defaults.

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


class PlayerCache:
    """Player-specific caching operations."""

    # Key templates
    PLAYER_RESOURCES_KEY = "lumen:v1:player:{player_id}:resources"
    ACTIVE_MODIFIERS_KEY = "lumen:v1:modifiers:{player_id}"

    @classmethod
    def _get_ttl(cls, cache_type: str) -> int:
        """
        Get TTL for specific cache type from ConfigManager.

        Parameters
        ----------
        cache_type:
            Cache type (player_resources, active_modifiers).

        Returns
        -------
        int
            TTL in seconds from config or sensible default.
        """
        defaults = {
            "player_resources": 300,  # 5 minutes
            "active_modifiers": 600,  # 10 minutes
        }

        config_key = f"cache.ttl.{cache_type}"
        return ConfigManager.get(config_key, defaults.get(cache_type, 300))

    # =========================================================================
    # PLAYER RESOURCES CACHING
    # =========================================================================

    @classmethod
    async def cache_player_resources(
        cls, player_id: int, resource_data: Dict[str, Any], ttl: Optional[int] = None
    ) -> bool:
        """
        Cache player resource summary with automatic compression.

        Parameters
        ----------
        player_id:
            Player's Discord ID.
        resource_data:
            Resource information to cache.
        ttl:
            Optional TTL override (uses ConfigManager default if None).

        Returns
        -------
        bool
            True if cached successfully, False otherwise.

        Example
        -------
        >>> await PlayerCache.cache_player_resources(
        ...     player_id=123456789,
        ...     resource_data={
        ...         "lumees": 1000,
        ...         "auric_coin": 500,
        ...         "energy": 50,
        ...         "stamina": 75
        ...     }
        ... )
        """
        start_time = time.perf_counter()
        key = cls.PLAYER_RESOURCES_KEY.format(player_id=player_id)

        # Get TTL from ConfigManager if not provided
        if ttl is None:
            ttl = cls._get_ttl("player_resources")

        try:
            # Use Redis's JSON support directly
            success = await RedisService.set(key, resource_data, ttl=ttl)

            if success:
                CacheMetrics.record_set()

                # Track timing
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                CacheMetrics.record_set_time(elapsed_ms)

                logger.debug(
                    f"Cached player resources: player={player_id} ttl={ttl}s time={elapsed_ms:.2f}ms"
                )

            return success

        except Exception as e:
            CacheMetrics.record_error()
            logger.error(
                f"Failed to cache player resources: player={player_id} error={e}",
                exc_info=True,
            )
            return False

    @classmethod
    async def get_cached_player_resources(
        cls, player_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Get cached player resources.

        Parameters
        ----------
        player_id:
            Player's Discord ID.

        Returns
        -------
        Optional[Dict[str, Any]]
            Cached resource data or None if not found/expired.
        """
        start_time = time.perf_counter()
        key = cls.PLAYER_RESOURCES_KEY.format(player_id=player_id)

        try:
            data = await RedisService.get(key)

            # Track timing
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            CacheMetrics.record_get_time(elapsed_ms)

            if data:
                CacheMetrics.record_hit()
                logger.debug(
                    f"Cache HIT: player_resources player={player_id} time={elapsed_ms:.2f}ms"
                )
                return data
            else:
                CacheMetrics.record_miss()
                logger.debug(
                    f"Cache MISS: player_resources player={player_id} time={elapsed_ms:.2f}ms"
                )
                return None

        except Exception as e:
            CacheMetrics.record_error()
            CacheMetrics.record_miss()
            logger.error(
                f"Error getting cached player resources: player={player_id} error={e}",
                exc_info=True,
            )
            return None

    @classmethod
    async def invalidate_player_resources(cls, player_id: int) -> bool:
        """
        Invalidate player resource cache.

        Parameters
        ----------
        player_id:
            Player's Discord ID.

        Returns
        -------
        bool
            True if invalidated successfully.
        """
        key = cls.PLAYER_RESOURCES_KEY.format(player_id=player_id)

        try:
            success = await RedisService.delete(key)

            if success:
                CacheMetrics.record_invalidation()
                logger.debug(f"Invalidated player resources: player={player_id}")

            return success

        except Exception as e:
            CacheMetrics.record_error()
            logger.error(
                f"Failed to invalidate player resources: player={player_id} error={e}",
                exc_info=True,
            )
            return False

    # =========================================================================
    # ACTIVE MODIFIERS CACHING
    # =========================================================================

    @classmethod
    async def cache_active_modifiers(
        cls, player_id: int, modifiers: Dict[str, float], ttl: Optional[int] = None
    ) -> bool:
        """
        Cache player's active modifiers.

        Parameters
        ----------
        player_id:
            Player's Discord ID.
        modifiers:
            Modifier data {"income_boost": 1.15, "xp_boost": 1.10}.
        ttl:
            Optional TTL override (uses ConfigManager default if None).

        Returns
        -------
        bool
            True if cached successfully.
        """
        start_time = time.perf_counter()
        key = cls.ACTIVE_MODIFIERS_KEY.format(player_id=player_id)

        # Get TTL from ConfigManager if not provided
        if ttl is None:
            ttl = cls._get_ttl("active_modifiers")

        try:
            success = await RedisService.set(key, modifiers, ttl=ttl)

            if success:
                CacheMetrics.record_set()

                elapsed_ms = (time.perf_counter() - start_time) * 1000
                CacheMetrics.record_set_time(elapsed_ms)

                logger.debug(
                    f"Cached active modifiers: player={player_id} count={len(modifiers)} "
                    f"ttl={ttl}s time={elapsed_ms:.2f}ms"
                )

            return success

        except Exception as e:
            CacheMetrics.record_error()
            logger.error(
                f"Failed to cache active modifiers: player={player_id} error={e}",
                exc_info=True,
            )
            return False

    @classmethod
    async def get_cached_modifiers(cls, player_id: int) -> Optional[Dict[str, float]]:
        """
        Get cached player modifiers.

        Parameters
        ----------
        player_id:
            Player's Discord ID.

        Returns
        -------
        Optional[Dict[str, float]]
            Cached modifier data or None.
        """
        start_time = time.perf_counter()
        key = cls.ACTIVE_MODIFIERS_KEY.format(player_id=player_id)

        try:
            data = await RedisService.get(key)

            elapsed_ms = (time.perf_counter() - start_time) * 1000
            CacheMetrics.record_get_time(elapsed_ms)

            if data:
                CacheMetrics.record_hit()
                logger.debug(
                    f"Cache HIT: active_modifiers player={player_id} time={elapsed_ms:.2f}ms"
                )
                return data
            else:
                CacheMetrics.record_miss()
                logger.debug(
                    f"Cache MISS: active_modifiers player={player_id} time={elapsed_ms:.2f}ms"
                )
                return None

        except Exception as e:
            CacheMetrics.record_error()
            CacheMetrics.record_miss()
            logger.error(
                f"Error getting cached modifiers: player={player_id} error={e}",
                exc_info=True,
            )
            return None
