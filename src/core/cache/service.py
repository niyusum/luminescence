"""
Advanced caching layer with observability and sophisticated invalidation for Lumen (2025).

Purpose
-------
Provides unified facade for the cache subsystem with high-performance caching,
comprehensive observability, and sophisticated invalidation strategies.
Main entry point for all cache operations across the Lumen system.

Features
--------
- Automatic JSON serialization via RedisService
- Tag-based bulk invalidation for coordinated updates
- Batch operations for high-throughput scenarios
- Comprehensive metrics tracking (hits, misses, latency)
- Health monitoring with circuit breaker integration
- ConfigManager-driven TTLs for all cache types
- Versioned keys for schema evolution
- Graceful degradation on Redis failures

Responsibilities
----------------
- Unified API facade for all cache operations
- Delegation to specialized cache modules
- Health checks and metrics aggregation
- High-level cache management operations

Non-Responsibilities
--------------------
- Direct Redis operations (handled by RedisService)
- Low-level cache implementation (handled by specialized modules)
- Metrics calculation (handled by CacheMetrics)
- Batch execution logic (handled by CacheOperations)

LES 2025 Compliance
-------------------
- **Observability**: Complete audit trails and metrics (Article X)
- **Config-Driven**: ConfigManager for all TTLs and thresholds (Article V)
- **Graceful Degradation**: Handles Redis failures transparently (Article IX)
- **Separation of Concerns**: Clean delegation to specialized modules (Article I)
- **Type Safety**: Complete type hints throughout

Architecture Notes
------------------
This module serves as a unified facade, delegating to specialized modules:

- **PlayerCache**: Player-specific caching (resources, modifiers)
- **CollectionCache**: Collection caching (maidens, fusion rates, etc.)
- **CacheOperations**: Batch operations and tag management
- **CacheMetrics**: Metrics tracking and health monitoring

All operations maintain backward compatibility while providing modern,
production-grade caching capabilities.

Key Templates
-------------
Player-specific:
- `lumen:v2:player:{player_id}:resources`
- `lumen:v2:player:{player_id}:modifiers`
- `lumen:v2:player:{player_id}:maidens`

Global collections:
- `lumen:v2:fusion:rates:{tier}`
- `lumen:v2:leader:{maiden_base_id}:{tier}`
- `lumen:v2:leaderboard:{type}:{period}`

Daily/time-based:
- `lumen:v2:daily:{player_id}:{date}`
- `lumen:v2:drop:{player_id}`

Tag Examples
------------
For bulk invalidation:
- `player:{player_id}` - All caches for specific player
- `maiden` - All maiden-related caches
- `fusion` - All fusion-related caches
- `leader` - All leader bonus caches
- `resources` - All resource caches
- `global` - All global/system caches

Dependencies
------------
- PlayerCache: Player-specific operations
- CollectionCache: Collection operations
- CacheOperations: Batch and tag operations
- CacheMetrics: Metrics and health monitoring
- RedisService: Redis backend
- ConfigManager: Configuration management
- Logger: Structured logging

Performance Characteristics
---------------------------
- Average GET latency: <5ms
- Average SET latency: <10ms
- Typical cache hit rate: 85-95%
- Batch operation throughput: 1000+ ops/sec
- Tag invalidation: O(n) where n = keys with tag
"""

from typing import Any, Dict, List, Optional

from src.core.cache.collections import CollectionCache
from src.core.cache.metrics import CacheMetrics
from src.core.cache.operations import CacheOperations
from src.core.cache.player import PlayerCache
from src.core.logging.logger import get_logger
from src.core.redis.service import RedisService

logger = get_logger(__name__)


class CacheService:
    """
    Advanced caching layer with comprehensive observability and management.
    
    Main entry point for all cache operations. Provides a clean, unified API
    while delegating to specialized modules for implementation.
    
    This facade maintains backward compatibility while providing production-grade
    caching capabilities including batch operations, tag-based invalidation,
    and comprehensive metrics.
    """

    # =========================================================================
    # PLAYER RESOURCES CACHING
    # Delegates to PlayerCache module
    # =========================================================================

    @classmethod
    async def cache_player_resources(
        cls,
        player_id: int,
        resource_data: Dict[str, Any],
        ttl: Optional[int] = None,
    ) -> bool:
        """
        Cache player resource summary.
        
        Parameters
        ----------
        player_id:
            Player's Discord ID (snowflake).
        resource_data:
            Resource data dictionary (lumees, currencies, energy, stamina).
        ttl:
            Optional TTL override in seconds.
        
        Returns
        -------
        bool
            True if cached successfully, False on Redis failure.
        
        Example
        -------
        >>> await CacheService.cache_player_resources(
        ...     player_id=123456789,
        ...     resource_data={
        ...         "lumees": 1000,
        ...         "auric_coin": 500,
        ...         "energy": 50,
        ...         "stamina": 75
        ...     }
        ... )
        """
        return await PlayerCache.cache_player_resources(player_id, resource_data, ttl)

    @classmethod
    async def get_cached_player_resources(
        cls, player_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Get cached player resources.
        
        Parameters
        ----------
        player_id:
            Player's Discord ID (snowflake).
        
        Returns
        -------
        Optional[Dict[str, Any]]
            Cached resource data or None if not found/expired.
        """
        return await PlayerCache.get_cached_player_resources(player_id)

    @classmethod
    async def invalidate_player_resources(cls, player_id: int) -> bool:
        """
        Invalidate player resource cache.
        
        Parameters
        ----------
        player_id:
            Player's Discord ID (snowflake).
        
        Returns
        -------
        bool
            True if invalidated successfully.
        """
        return await PlayerCache.invalidate_player_resources(player_id)

    # =========================================================================
    # ACTIVE MODIFIERS CACHING
    # Delegates to PlayerCache module
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
        
        Parameters
        ----------
        player_id:
            Player's Discord ID (snowflake).
        modifiers:
            Modifier dictionary ({"income_boost": 1.15, "xp_boost": 1.10}).
        ttl:
            Optional TTL override in seconds.
        
        Returns
        -------
        bool
            True if cached successfully.
        """
        return await PlayerCache.cache_active_modifiers(player_id, modifiers, ttl)

    @classmethod
    async def get_cached_modifiers(cls, player_id: int) -> Optional[Dict[str, float]]:
        """
        Get cached player modifiers.
        
        Parameters
        ----------
        player_id:
            Player's Discord ID (snowflake).
        
        Returns
        -------
        Optional[Dict[str, float]]
            Cached modifier data or None if not found/expired.
        """
        return await PlayerCache.get_cached_modifiers(player_id)

    @classmethod
    async def invalidate_player_modifiers(cls, player_id: int) -> bool:
        """
        Invalidate player modifier cache.
        
        Parameters
        ----------
        player_id:
            Player's Discord ID (snowflake).
        
        Returns
        -------
        bool
            True if invalidated successfully.
        """
        return await PlayerCache.invalidate_player_modifiers(player_id)

    # =========================================================================
    # MAIDEN COLLECTION CACHING
    # Delegates to CollectionCache module
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
            Player's Discord ID (snowflake).
        collection_data:
            Maiden collection data.
        ttl:
            Optional TTL override in seconds.
        
        Returns
        -------
        bool
            True if cached successfully.
        """
        return await CollectionCache.cache_maiden_collection(
            player_id, collection_data, ttl
        )

    @classmethod
    async def get_cached_maiden_collection(
        cls, player_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Get cached maiden collection.
        
        Parameters
        ----------
        player_id:
            Player's Discord ID (snowflake).
        
        Returns
        -------
        Optional[Dict[str, Any]]
            Cached collection data or None if not found/expired.
        """
        return await CollectionCache.get_cached_maiden_collection(player_id)

    # =========================================================================
    # FUSION RATES CACHING
    # Delegates to CollectionCache module
    # =========================================================================

    @classmethod
    async def cache_fusion_rates(
        cls,
        tier: str,
        rates_data: Dict[str, Any],
        ttl: Optional[int] = None,
    ) -> bool:
        """
        Cache fusion rates for a tier.
        
        Parameters
        ----------
        tier:
            Tier identifier (e.g., "SR", "SSR", "UR").
        rates_data:
            Fusion rate configuration.
        ttl:
            Optional TTL override in seconds.
        
        Returns
        -------
        bool
            True if cached successfully.
        """
        return await CollectionCache.cache_fusion_rates(tier, rates_data, ttl)

    @classmethod
    async def get_cached_fusion_rates(cls, tier: str) -> Optional[Dict[str, Any]]:
        """
        Get cached fusion rates.
        
        Parameters
        ----------
        tier:
            Tier identifier (e.g., "SR", "SSR", "UR").
        
        Returns
        -------
        Optional[Dict[str, Any]]
            Cached rates data or None if not found/expired.
        """
        return await CollectionCache.get_cached_fusion_rates(tier)

    # =========================================================================
    # LEADER BONUSES CACHING
    # Delegates to CollectionCache module
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
            Maiden's base ID.
        tier:
            Tier identifier (e.g., "SR", "SSR", "UR").
        bonuses_data:
            Leader bonus configuration.
        ttl:
            Optional TTL override in seconds.
        
        Returns
        -------
        bool
            True if cached successfully.
        """
        return await CollectionCache.cache_leader_bonuses(
            maiden_base_id, tier, bonuses_data, ttl
        )

    @classmethod
    async def get_cached_leader_bonuses(
        cls, maiden_base_id: int, tier: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get cached leader bonuses.
        
        Parameters
        ----------
        maiden_base_id:
            Maiden's base ID.
        tier:
            Tier identifier (e.g., "SR", "SSR", "UR").
        
        Returns
        -------
        Optional[Dict[str, Any]]
            Cached bonuses data or None if not found/expired.
        """
        return await CollectionCache.get_cached_leader_bonuses(maiden_base_id, tier)

    # =========================================================================
    # DROP CHARGES CACHING
    # Delegates to CollectionCache module
    # =========================================================================

    @classmethod
    async def cache_drop_charges(
        cls,
        player_id: int,
        charges_data: Dict[str, Any],
        ttl: Optional[int] = None,
    ) -> bool:
        """
        Cache player's drop charges (gacha currency).
        
        Parameters
        ----------
        player_id:
            Player's Discord ID (snowflake).
        charges_data:
            Drop charge data.
        ttl:
            Optional TTL override in seconds.
        
        Returns
        -------
        bool
            True if cached successfully.
        """
        return await CollectionCache.cache_drop_charges(player_id, charges_data, ttl)

    @classmethod
    async def get_cached_drop_charges(
        cls, player_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Get cached drop charges.
        
        Parameters
        ----------
        player_id:
            Player's Discord ID (snowflake).
        
        Returns
        -------
        Optional[Dict[str, Any]]
            Cached charges data or None if not found/expired.
        """
        return await CollectionCache.get_cached_drop_charges(player_id)

    # =========================================================================
    # DAILY QUEST CACHING
    # Delegates to CollectionCache module
    # =========================================================================

    @classmethod
    async def cache_daily_quest(
        cls,
        player_id: int,
        date: str,
        quest_data: Dict[str, Any],
        ttl: Optional[int] = None,
    ) -> bool:
        """
        Cache daily quest data.
        
        Parameters
        ----------
        player_id:
            Player's Discord ID (snowflake).
        date:
            Date string in YYYY-MM-DD format.
        quest_data:
            Quest progress data.
        ttl:
            Optional TTL override in seconds.
        
        Returns
        -------
        bool
            True if cached successfully.
        """
        return await CollectionCache.cache_daily_quest(
            player_id, date, quest_data, ttl
        )

    @classmethod
    async def get_cached_daily_quest(
        cls, player_id: int, date: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get cached daily quest data.
        
        Parameters
        ----------
        player_id:
            Player's Discord ID (snowflake).
        date:
            Date string in YYYY-MM-DD format.
        
        Returns
        -------
        Optional[Dict[str, Any]]
            Cached quest data or None if not found/expired.
        """
        return await CollectionCache.get_cached_daily_quest(player_id, date)

    # =========================================================================
    # LEADERBOARD CACHING
    # Delegates to CollectionCache module
    # =========================================================================

    @classmethod
    async def cache_leaderboard(
        cls,
        leaderboard_type: str,
        period: str,
        leaderboard_data: Dict[str, Any],
        ttl: Optional[int] = None,
    ) -> bool:
        """
        Cache leaderboard data.
        
        Parameters
        ----------
        leaderboard_type:
            Type of leaderboard (e.g., "lumees", "collection", "power").
        period:
            Period identifier (e.g., "daily", "weekly", "monthly").
        leaderboard_data:
            Leaderboard rankings.
        ttl:
            Optional TTL override in seconds.
        
        Returns
        -------
        bool
            True if cached successfully.
        """
        return await CollectionCache.cache_leaderboard(
            leaderboard_type, period, leaderboard_data, ttl
        )

    @classmethod
    async def get_cached_leaderboard(
        cls, leaderboard_type: str, period: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get cached leaderboard data.
        
        Parameters
        ----------
        leaderboard_type:
            Type of leaderboard (e.g., "lumees", "collection", "power").
        period:
            Period identifier (e.g., "daily", "weekly", "monthly").
        
        Returns
        -------
        Optional[Dict[str, Any]]
            Cached leaderboard data or None if not found/expired.
        """
        return await CollectionCache.get_cached_leaderboard(leaderboard_type, period)

    # =========================================================================
    # BATCH OPERATIONS
    # Delegates to CacheOperations module
    # =========================================================================

    @classmethod
    async def batch_cache(
        cls, cache_operations: List[Dict[str, Any]]
    ) -> Dict[str, bool]:
        """
        Execute multiple cache operations in parallel for efficiency.
        
        Parameters
        ----------
        cache_operations:
            List of cache operation dictionaries.
        
        Returns
        -------
        Dict[str, bool]
            Dictionary mapping cache keys to success status.
        
        Example
        -------
        >>> results = await CacheService.batch_cache([
        ...     {
        ...         "template": "player_resources",
        ...         "template_args": {"player_id": 123},
        ...         "data": {"lumees": 1000},
        ...         "tags": ["player:123", "resources"]
        ...     },
        ...     {
        ...         "template": "active_modifiers",
        ...         "template_args": {"player_id": 456},
        ...         "data": {"income_boost": 1.15},
        ...         "tags": ["player:456", "modifiers"]
        ...     }
        ... ])
        """
        return await CacheOperations.batch_cache(cache_operations)

    # =========================================================================
    # TAG-BASED INVALIDATION
    # Delegates to CacheOperations module
    # =========================================================================

    @classmethod
    async def invalidate_by_tag(cls, tag: str) -> int:
        """
        Invalidate all cache keys associated with a tag.
        
        Parameters
        ----------
        tag:
            Tag to invalidate (e.g., "player:123", "resources", "global").
        
        Returns
        -------
        int
            Number of keys successfully invalidated.
        
        Example
        -------
        >>> # Invalidate all caches for player 123456789
        >>> count = await CacheService.invalidate_by_tag("player:123456789")
        >>> logger.info(f"Invalidated {count} cache entries")
        """
        return await CacheOperations.invalidate_by_tag(tag)

    @classmethod
    async def batch_invalidate_by_tags(cls, tags: List[str]) -> Dict[str, int]:
        """
        Invalidate multiple tags in parallel for efficiency.
        
        Parameters
        ----------
        tags:
            List of tags to invalidate concurrently.
        
        Returns
        -------
        Dict[str, int]
            Dictionary mapping tags to number of keys invalidated.
        
        Example
        -------
        >>> results = await CacheService.batch_invalidate_by_tags([
        ...     "player:123",
        ...     "resources",
        ...     "maiden"
        ... ])
        >>> total = sum(results.values())
        """
        return await CacheOperations.batch_invalidate_by_tags(tags)

    @classmethod
    async def invalidate_by_pattern(cls, pattern: str, max_keys: int = 1000) -> int:
        """
        Invalidate cache entries matching a Redis key pattern.
        
        Warning: Use with caution. Pattern matching can be expensive.
        Consider using tag-based invalidation instead.
        
        Parameters
        ----------
        pattern:
            Redis key pattern (e.g., "lumen:v2:player:*:resources").
        max_keys:
            Maximum number of keys to invalidate (safety limit).
        
        Returns
        -------
        int
            Number of keys invalidated.
        """
        return await CacheOperations.invalidate_by_pattern(pattern, max_keys)

    # =========================================================================
    # BULK PLAYER OPERATIONS
    # Convenience methods for common scenarios
    # =========================================================================

    @classmethod
    async def invalidate_all_player_caches(cls, player_id: int) -> Dict[str, bool]:
        """
        Invalidate all cache entries for a specific player.
        
        Convenience method that invalidates all player-related caches.
        
        Parameters
        ----------
        player_id:
            Player's Discord ID (snowflake).
        
        Returns
        -------
        Dict[str, bool]
            Dictionary mapping cache types to invalidation success.
        
        Example
        -------
        >>> results = await CacheService.invalidate_all_player_caches(123456789)
        >>> if all(results.values()):
        ...     logger.info("All player caches invalidated successfully")
        """
        return await PlayerCache.invalidate_all_player_caches(player_id)

    # =========================================================================
    # METRICS & MONITORING
    # Delegates to CacheMetrics module
    # =========================================================================

    @classmethod
    async def get_metrics(cls) -> Dict[str, Any]:
        """
        Get comprehensive cache performance metrics.
        
        Returns
        -------
        Dict[str, Any]
            Metrics including hits, misses, hit rate, latencies, errors.
        
        Example
        -------
        >>> metrics = await CacheService.get_metrics()
        >>> print(f"Hit rate: {metrics['hit_rate']:.1f}%")
        >>> print(f"Avg latency: {metrics['avg_get_time_ms']:.2f}ms")
        """
        return await CacheMetrics.get_metrics()

    @classmethod
    async def get_hit_rate(cls) -> float:
        """
        Calculate current cache hit rate percentage.
        
        Returns
        -------
        float
            Hit rate as percentage (0-100).
        """
        return await CacheMetrics.get_hit_rate()

    @classmethod
    async def is_healthy(cls) -> bool:
        """
        Check if cache service is healthy.
        
        Returns
        -------
        bool
            True if cache is healthy and performing well.
        """
        return await CacheMetrics.is_healthy()

    @classmethod
    async def reset_metrics(cls) -> None:
        """
        Reset all metrics counters to zero.
        
        Useful for testing or periodic metrics rotation.
        """
        await CacheMetrics.reset_metrics()
        logger.info("Cache metrics reset")

    @classmethod
    async def health_check(cls) -> Dict[str, Any]:
        """
        Perform comprehensive cache health check.
        
        Returns
        -------
        Dict[str, Any]
            Health status including Redis availability, metrics, and status.
        
        Example
        -------
        >>> health = await CacheService.health_check()
        >>> if health['status'] == 'degraded':
        ...     logger.warning("Cache performance degraded")
        ...     send_alert("cache_degraded", health)
        """
        redis_available = await RedisService.health_check()
        metrics = await cls.get_metrics()
        is_healthy = await cls.is_healthy()

        return {
            "redis_available": redis_available,
            "hit_rate": metrics["hit_rate"],
            "compression_ratio": metrics.get("compression_ratio", 0.0),
            "total_operations": metrics["total_operations"],
            "errors": metrics["errors"],
            "avg_get_time_ms": metrics["avg_get_time_ms"],
            "avg_set_time_ms": metrics["avg_set_time_ms"],
            "is_healthy": is_healthy,
            "status": "healthy" if (redis_available and is_healthy) else "degraded",
        }