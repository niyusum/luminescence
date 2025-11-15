"""
Player-specific caching operations for Lumen (2025).

Purpose
-------
Provides high-performance caching for player-specific data including resources,
modifiers, and session state. Designed for low-latency access to frequently
accessed player information with automatic TTL management.

Responsibilities
----------------
- Player resource caching (lumees, energy, stamina, currencies)
- Active modifier caching (boosts, multipliers, temporary effects)
- Player cache invalidation for data consistency
- Automatic TTL management via ConfigManager
- Performance metrics tracking
- Graceful degradation on Redis failures

Non-Responsibilities
--------------------
- Batch operations (handled by operations module)
- Metrics aggregation (handled by metrics module)
- Generic caching utilities (handled by service module)
- Collection caching (handled by collections module)

LES 2025 Compliance
-------------------
- **Config-Driven**: TTLs managed via ConfigManager
- **Observability**: Structured logging with operation context
- **Graceful Degradation**: Handles Redis failures without exceptions
- **Type Safety**: Complete type hints throughout
- **Performance**: Sub-millisecond operation latency tracking

Architecture Notes
------------------
- Uses RedisService for storage backend with automatic JSON serialization
- ConfigManager-driven TTL defaults with per-operation overrides
- Comprehensive error handling with fallback to empty cache
- Performance timing tracked for all operations
- Consistent key naming with version prefixes

Key Format
----------
All keys follow the pattern: `lumen:v2:player:{player_id}:{resource_type}`

Dependencies
------------
- RedisService: Redis operations and JSON serialization
- ConfigManager: TTL configuration and thresholds
- CacheMetrics: Performance metrics tracking
- Logger: Structured logging with context

Performance Characteristics
---------------------------
- Average GET latency: <5ms
- Average SET latency: <10ms
- TTL: 300s (resources), 600s (modifiers) - configurable
- Memory per player: ~1KB (resources), ~500B (modifiers)
"""

import time
from typing import Any, Dict, Optional

from src.core.cache.metrics import CacheMetrics
from src.core.config import ConfigManager
from src.core.logging.logger import get_logger
from src.core.redis.service import RedisService

logger = get_logger(__name__)


class PlayerCache:
    """
    Player-specific caching operations.
    
    Provides high-performance caching for player resources and modifiers
    with automatic TTL management and comprehensive observability.
    """

    # Key templates with version prefix for cache invalidation
    PLAYER_RESOURCES_KEY = "lumen:v2:player:{player_id}:resources"
    ACTIVE_MODIFIERS_KEY = "lumen:v2:player:{player_id}:modifiers"

    # TTL configuration defaults (overridable via ConfigManager)
    _TTL_DEFAULTS = {
        "player_resources": 300,      # 5 minutes - frequently updated
        "active_modifiers": 600,      # 10 minutes - less frequent changes
    }

    @classmethod
    def _get_ttl(cls, cache_type: str) -> int:
        """
        Get TTL for specific cache type from ConfigManager with fallback.
        
        Parameters
        ----------
        cache_type:
            Cache type identifier (player_resources, active_modifiers).
        
        Returns
        -------
        int
            TTL in seconds from ConfigManager or sensible default.
        
        Example
        -------
        >>> ttl = PlayerCache._get_ttl("player_resources")
        >>> # Returns 300 (5 minutes) by default
        """
        default = cls._TTL_DEFAULTS.get(cache_type, 300)
        config_key = f"cache.ttl.{cache_type}"
        return ConfigManager.get(config_key, default)

    # =========================================================================
    # PLAYER RESOURCES CACHING
    # =========================================================================

    @classmethod
    async def cache_player_resources(
        cls,
        player_id: int,
        resource_data: Dict[str, Any],
        ttl: Optional[int] = None,
    ) -> bool:
        """
        Cache player resource summary with automatic JSON serialization.
        
        Caches frequently accessed player resources including currencies,
        energy, stamina, and other consumables for fast access.
        
        Parameters
        ----------
        player_id:
            Player's Discord ID (snowflake).
        resource_data:
            Resource information dictionary. Expected keys:
            - lumees: Primary currency
            - auric_coin: Premium currency
            - energy: Current energy points
            - stamina: Current stamina points
            - last_updated: Timestamp of data snapshot
        ttl:
            Optional TTL override in seconds. Uses ConfigManager default if None.
        
        Returns
        -------
        bool
            True if cached successfully, False on Redis failure.
        
        Example
        -------
        >>> success = await PlayerCache.cache_player_resources(
        ...     player_id=123456789,
        ...     resource_data={
        ...         "lumees": 1000,
        ...         "auric_coin": 500,
        ...         "energy": 50,
        ...         "stamina": 75,
        ...         "last_updated": 1640000000
        ...     }
        ... )
        >>> if success:
        ...     logger.info("Player resources cached")
        """
        start_time = time.perf_counter()
        key = cls.PLAYER_RESOURCES_KEY.format(player_id=player_id)

        # Get TTL from ConfigManager if not provided
        if ttl is None:
            ttl = cls._get_ttl("player_resources")

        try:
            # Use RedisService with automatic JSON serialization
            success = await RedisService.set_json(key, resource_data, ttl_seconds=ttl)

            if success:
                await CacheMetrics.record_set()

                # Track operation latency
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                await CacheMetrics.record_set_time(elapsed_ms)

                logger.debug(
                    "Cached player resources",
                    extra={
                        "player_id": player_id,
                        "ttl_seconds": ttl,
                        "latency_ms": round(elapsed_ms, 2),
                        "operation": "cache_player_resources",
                    },
                )
            else:
                logger.warning(
                    "Failed to cache player resources (Redis returned False)",
                    extra={"player_id": player_id, "operation": "cache_player_resources"},
                )

            return success

        except Exception as e:
            await CacheMetrics.record_error()
            logger.error(
                "Exception caching player resources",
                extra={
                    "player_id": player_id,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "operation": "cache_player_resources",
                },
                exc_info=True,
            )
            return False

    @classmethod
    async def get_cached_player_resources(
        cls, player_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Get cached player resources with performance tracking.
        
        Parameters
        ----------
        player_id:
            Player's Discord ID (snowflake).
        
        Returns
        -------
        Optional[Dict[str, Any]]
            Cached resource data dictionary or None if not found/expired.
        
        Example
        -------
        >>> resources = await PlayerCache.get_cached_player_resources(123456789)
        >>> if resources:
        ...     lumees = resources.get("lumees", 0)
        ...     energy = resources.get("energy", 0)
        ... else:
        ...     # Cache miss - fetch from database
        ...     resources = await fetch_player_resources_from_db(123456789)
        """
        start_time = time.perf_counter()
        key = cls.PLAYER_RESOURCES_KEY.format(player_id=player_id)

        try:
            data = await RedisService.get_json(key)

            # Track operation latency
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            await CacheMetrics.record_get_time(elapsed_ms)

            if data:
                await CacheMetrics.record_hit()
                logger.debug(
                    "Cache HIT: player_resources",
                    extra={
                        "player_id": player_id,
                        "latency_ms": round(elapsed_ms, 2),
                        "operation": "get_cached_player_resources",
                    },
                )
                return data
            else:
                await CacheMetrics.record_miss()
                logger.debug(
                    "Cache MISS: player_resources",
                    extra={
                        "player_id": player_id,
                        "latency_ms": round(elapsed_ms, 2),
                        "operation": "get_cached_player_resources",
                    },
                )
                return None

        except Exception as e:
            await CacheMetrics.record_error()
            await CacheMetrics.record_miss()
            logger.error(
                "Exception getting cached player resources",
                extra={
                    "player_id": player_id,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "operation": "get_cached_player_resources",
                },
                exc_info=True,
            )
            return None

    @classmethod
    async def invalidate_player_resources(cls, player_id: int) -> bool:
        """
        Invalidate player resource cache entry.
        
        Use this when player resources change (transactions, rewards, etc.)
        to ensure cache consistency.
        
        Parameters
        ----------
        player_id:
            Player's Discord ID (snowflake).
        
        Returns
        -------
        bool
            True if invalidated successfully, False on Redis failure.
        
        Example
        -------
        >>> # After updating player resources in database
        >>> await update_player_lumees(player_id, new_amount)
        >>> await PlayerCache.invalidate_player_resources(player_id)
        """
        key = cls.PLAYER_RESOURCES_KEY.format(player_id=player_id)

        try:
            deleted_count = await RedisService.delete(key)
            success = bool(deleted_count)

            if success:
                await CacheMetrics.record_invalidation()
                logger.debug(
                    "Invalidated player resources cache",
                    extra={
                        "player_id": player_id,
                        "operation": "invalidate_player_resources",
                    },
                )
            else:
                logger.debug(
                    "Cache invalidation returned False (key may not exist)",
                    extra={
                        "player_id": player_id,
                        "operation": "invalidate_player_resources",
                    },
                )

            return success

        except Exception as e:
            await CacheMetrics.record_error()
            logger.error(
                "Exception invalidating player resources",
                extra={
                    "player_id": player_id,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "operation": "invalidate_player_resources",
                },
                exc_info=True,
            )
            return False

    # =========================================================================
    # ACTIVE MODIFIERS CACHING
    # =========================================================================

    @classmethod
    async def cache_active_modifiers(
        cls,
        player_id: int,
        modifiers: Dict[str, float],
        ttl: Optional[int] = None,
    ) -> bool:
        """
        Cache player's active modifiers (boosts, multipliers).
        
        Modifiers include temporary effects like:
        - Income boosts
        - XP multipliers
        - Drop rate increases
        - Energy regeneration bonuses
        
        Parameters
        ----------
        player_id:
            Player's Discord ID (snowflake).
        modifiers:
            Modifier dictionary mapping modifier names to multiplier values.
            Example: {"income_boost": 1.15, "xp_boost": 1.10}
        ttl:
            Optional TTL override in seconds. Uses ConfigManager default if None.
        
        Returns
        -------
        bool
            True if cached successfully, False on Redis failure.
        
        Example
        -------
        >>> await PlayerCache.cache_active_modifiers(
        ...     player_id=123456789,
        ...     modifiers={
        ...         "income_boost": 1.15,  # +15% income
        ...         "xp_boost": 1.10,      # +10% XP
        ...         "drop_rate": 1.25      # +25% drop rate
        ...     }
        ... )
        """
        start_time = time.perf_counter()
        key = cls.ACTIVE_MODIFIERS_KEY.format(player_id=player_id)

        # Get TTL from ConfigManager if not provided
        if ttl is None:
            ttl = cls._get_ttl("active_modifiers")

        try:
            success = await RedisService.set_json(key, modifiers, ttl_seconds=ttl)

            if success:
                await CacheMetrics.record_set()

                elapsed_ms = (time.perf_counter() - start_time) * 1000
                await CacheMetrics.record_set_time(elapsed_ms)

                logger.debug(
                    "Cached active modifiers",
                    extra={
                        "player_id": player_id,
                        "modifier_count": len(modifiers),
                        "ttl_seconds": ttl,
                        "latency_ms": round(elapsed_ms, 2),
                        "operation": "cache_active_modifiers",
                    },
                )
            else:
                logger.warning(
                    "Failed to cache active modifiers (Redis returned False)",
                    extra={"player_id": player_id, "operation": "cache_active_modifiers"},
                )

            return success

        except Exception as e:
            await CacheMetrics.record_error()
            logger.error(
                "Exception caching active modifiers",
                extra={
                    "player_id": player_id,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "operation": "cache_active_modifiers",
                },
                exc_info=True,
            )
            return False

    @classmethod
    async def get_cached_modifiers(cls, player_id: int) -> Optional[Dict[str, float]]:
        """
        Get cached player modifiers with performance tracking.
        
        Parameters
        ----------
        player_id:
            Player's Discord ID (snowflake).
        
        Returns
        -------
        Optional[Dict[str, float]]
            Cached modifier dictionary or None if not found/expired.
        
        Example
        -------
        >>> modifiers = await PlayerCache.get_cached_modifiers(123456789)
        >>> if modifiers:
        ...     income_multiplier = modifiers.get("income_boost", 1.0)
        ...     total_income = base_income * income_multiplier
        ... else:
        ...     # Cache miss - fetch from database
        ...     modifiers = await fetch_active_modifiers_from_db(123456789)
        """
        start_time = time.perf_counter()
        key = cls.ACTIVE_MODIFIERS_KEY.format(player_id=player_id)

        try:
            data = await RedisService.get_json(key)

            elapsed_ms = (time.perf_counter() - start_time) * 1000
            await CacheMetrics.record_get_time(elapsed_ms)

            if data:
                await CacheMetrics.record_hit()
                logger.debug(
                    "Cache HIT: active_modifiers",
                    extra={
                        "player_id": player_id,
                        "latency_ms": round(elapsed_ms, 2),
                        "operation": "get_cached_modifiers",
                    },
                )
                return data
            else:
                await CacheMetrics.record_miss()
                logger.debug(
                    "Cache MISS: active_modifiers",
                    extra={
                        "player_id": player_id,
                        "latency_ms": round(elapsed_ms, 2),
                        "operation": "get_cached_modifiers",
                    },
                )
                return None

        except Exception as e:
            await CacheMetrics.record_error()
            await CacheMetrics.record_miss()
            logger.error(
                "Exception getting cached modifiers",
                extra={
                    "player_id": player_id,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "operation": "get_cached_modifiers",
                },
                exc_info=True,
            )
            return None

    @classmethod
    async def invalidate_player_modifiers(cls, player_id: int) -> bool:
        """
        Invalidate player modifier cache entry.
        
        Use this when modifiers change (buff expires, new buff applied, etc.)
        to ensure cache consistency.
        
        Parameters
        ----------
        player_id:
            Player's Discord ID (snowflake).
        
        Returns
        -------
        bool
            True if invalidated successfully, False on Redis failure.
        
        Example
        -------
        >>> # After applying new modifier or expiring old one
        >>> await apply_xp_boost(player_id, 1.5, duration=3600)
        >>> await PlayerCache.invalidate_player_modifiers(player_id)
        """
        key = cls.ACTIVE_MODIFIERS_KEY.format(player_id=player_id)

        try:
            deleted_count = await RedisService.delete(key)
            success = bool(deleted_count)

            if success:
                await CacheMetrics.record_invalidation()
                logger.debug(
                    "Invalidated player modifiers cache",
                    extra={
                        "player_id": player_id,
                        "operation": "invalidate_player_modifiers",
                    },
                )

            return success

        except Exception as e:
            await CacheMetrics.record_error()
            logger.error(
                "Exception invalidating player modifiers",
                extra={
                    "player_id": player_id,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "operation": "invalidate_player_modifiers",
                },
                exc_info=True,
            )
            return False

    @classmethod
    async def invalidate_all_player_caches(cls, player_id: int) -> Dict[str, bool]:
        """
        Invalidate all cache entries for a specific player.
        
        Convenience method for invalidating all player-related caches at once.
        Useful for logout, data migration, or full cache refresh scenarios.
        
        Parameters
        ----------
        player_id:
            Player's Discord ID (snowflake).
        
        Returns
        -------
        Dict[str, bool]
            Dictionary mapping cache types to invalidation success status.
        
        Example
        -------
        >>> # After major player data update
        >>> results = await PlayerCache.invalidate_all_player_caches(123456789)
        >>> if all(results.values()):
        ...     logger.info("All player caches invalidated successfully")
        """
        results = {
            "resources": await cls.invalidate_player_resources(player_id),
            "modifiers": await cls.invalidate_player_modifiers(player_id),
        }

        logger.info(
            "Bulk player cache invalidation completed",
            extra={
                "player_id": player_id,
                "results": results,
                "operation": "invalidate_all_player_caches",
            },
        )

        return results