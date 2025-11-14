"""
Advanced caching layer with observability, compression, and sophisticated invalidation.

Features
--------
- Automatic compression for large payloads (>1KB threshold)
- Tag-based bulk invalidation
- Batch operations for efficiency
- Hit/miss rate tracking with timing metrics
- Health monitoring and circuit breaker integration
- ConfigManager-driven TTLs
- Versioned keys for schema evolution

LUMEN LAW Compliance
--------------------
- Complete audit trails for cache operations (Article II)
- ConfigManager integration for tunables (Article V)
- Graceful degradation when Redis unavailable (Article IX)
- Comprehensive metrics and observability (Article X)

Architecture
------------
This module serves as a unified facade for the cache subsystem,
delegating to specialized modules:
- player: Player-specific caching (resources, modifiers)
- collections: Collection caching (maidens, fusion, etc.)
- operations: Batch operations and tag invalidation
- metrics: Metrics tracking and health monitoring

All operations are delegated to specialized modules for better
separation of concerns while maintaining backward compatibility.
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
    Advanced caching layer with compression, tagging, and sophisticated invalidation.

    Built on top of RedisService with additional features:
    - Data compression for large objects (>1KB threshold)
    - Tag-based invalidation (invalidate all "player" caches at once)
    - Key templates for consistent naming
    - Metrics tracking (hits/misses/timing)
    - Batch operations for efficiency
    - Graceful degradation when Redis unavailable
    - ConfigManager integration for all tunables

    Key Templates
    -------------
    - player_resources:{player_id}
    - maiden_collection:{player_id}
    - fusion_rates:{tier}
    - leader_bonuses:{maiden_base_id}:{tier}
    - daily_quest:{player_id}:{date}
    - DROP_CHARGES:{player_id}
    - active_modifiers:{player_id}
    - leaderboards:{type}:{period}

    Tags (for bulk invalidation)
    ----------------------------
    - player:{player_id} - All caches for specific player
    - maiden - All maiden-related caches
    - fusion - All fusion-related caches
    - leader - All leader bonus caches
    - resources - All resource caches
    - daily - All daily quest caches
    - global - All global caches

    LUMEN LAW Compliance
    --------------------
    - Article II: Logs all cache operations for audit trails
    - Article V: ConfigManager for all TTLs and thresholds
    - Article IX: Graceful degradation on Redis failure
    - Article X: Comprehensive metrics and health monitoring
    """

    # =========================================================================
    # PLAYER RESOURCES CACHING (Delegates to PlayerCache)
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
        """
        return await PlayerCache.cache_player_resources(player_id, resource_data, ttl)

    @classmethod
    async def get_cached_player_resources(
        cls, player_id: int
    ) -> Optional[Dict[str, Any]]:
        """Get cached player resources."""
        return await PlayerCache.get_cached_player_resources(player_id)

    @classmethod
    async def invalidate_player_resources(cls, player_id: int) -> bool:
        """Invalidate player resource cache."""
        return await PlayerCache.invalidate_player_resources(player_id)

    # =========================================================================
    # ACTIVE MODIFIERS CACHING (Delegates to PlayerCache)
    # =========================================================================

    @classmethod
    async def cache_active_modifiers(
        cls, player_id: int, modifiers: Dict[str, float], ttl: Optional[int] = None
    ) -> bool:
        """Cache player's active modifiers."""
        return await PlayerCache.cache_active_modifiers(player_id, modifiers, ttl)

    @classmethod
    async def get_cached_modifiers(cls, player_id: int) -> Optional[Dict[str, float]]:
        """Get cached player modifiers."""
        return await PlayerCache.get_cached_modifiers(player_id)

    # =========================================================================
    # MAIDEN COLLECTION CACHING (Delegates to CollectionCache)
    # =========================================================================

    @classmethod
    async def cache_maiden_collection(
        cls,
        player_id: int,
        collection_data: Dict[str, Any],
        ttl: Optional[int] = None,
    ) -> bool:
        """Cache player's maiden collection."""
        return await CollectionCache.cache_maiden_collection(
            player_id, collection_data, ttl
        )

    @classmethod
    async def get_cached_maiden_collection(
        cls, player_id: int
    ) -> Optional[Dict[str, Any]]:
        """Get cached maiden collection."""
        return await CollectionCache.get_cached_maiden_collection(player_id)

    # =========================================================================
    # FUSION RATES CACHING (Delegates to CollectionCache)
    # =========================================================================

    @classmethod
    async def cache_fusion_rates(
        cls, tier: str, rates_data: Dict[str, Any], ttl: Optional[int] = None
    ) -> bool:
        """Cache fusion rates for a tier."""
        return await CollectionCache.cache_fusion_rates(tier, rates_data, ttl)

    @classmethod
    async def get_cached_fusion_rates(cls, tier: str) -> Optional[Dict[str, Any]]:
        """Get cached fusion rates."""
        return await CollectionCache.get_cached_fusion_rates(tier)

    # =========================================================================
    # LEADER BONUSES CACHING (Delegates to CollectionCache)
    # =========================================================================

    @classmethod
    async def cache_leader_bonuses(
        cls,
        maiden_base_id: int,
        tier: str,
        bonuses_data: Dict[str, Any],
        ttl: Optional[int] = None,
    ) -> bool:
        """Cache leader bonuses for a maiden."""
        return await CollectionCache.cache_leader_bonuses(
            maiden_base_id, tier, bonuses_data, ttl
        )

    @classmethod
    async def get_cached_leader_bonuses(
        cls, maiden_base_id: int, tier: str
    ) -> Optional[Dict[str, Any]]:
        """Get cached leader bonuses."""
        return await CollectionCache.get_cached_leader_bonuses(maiden_base_id, tier)

    # =========================================================================
    # DROP CHARGES CACHING (Delegates to CollectionCache)
    # =========================================================================

    @classmethod
    async def cache_drop_charges(
        cls, player_id: int, charges_data: Dict[str, Any], ttl: Optional[int] = None
    ) -> bool:
        """Cache player's drop charges."""
        return await CollectionCache.cache_drop_charges(player_id, charges_data, ttl)

    @classmethod
    async def get_cached_drop_charges(
        cls, player_id: int
    ) -> Optional[Dict[str, Any]]:
        """Get cached drop charges."""
        return await CollectionCache.get_cached_drop_charges(player_id)

    # =========================================================================
    # BATCH OPERATIONS (Delegates to CacheOperations)
    # =========================================================================

    @classmethod
    async def batch_cache(
        cls, cache_operations: List[Dict[str, Any]]
    ) -> Dict[str, bool]:
        """
        Execute multiple cache operations in batch for efficiency.

        Parameters
        ----------
        cache_operations:
            List of cache operations.

        Returns
        -------
        Dict[str, bool]
            Dictionary mapping keys to success status.
        """
        return await CacheOperations.batch_cache(cache_operations)

    # =========================================================================
    # TAG-BASED INVALIDATION (Delegates to CacheOperations)
    # =========================================================================

    @classmethod
    async def invalidate_by_tag(cls, tag: str) -> int:
        """Invalidate all cache keys associated with a tag."""
        return await CacheOperations.invalidate_by_tag(tag)

    @classmethod
    async def batch_invalidate_by_tags(cls, tags: List[str]) -> Dict[str, int]:
        """Invalidate multiple tags in parallel for efficiency."""
        return await CacheOperations.batch_invalidate_by_tags(tags)

    # =========================================================================
    # MAINTENANCE & MONITORING (Delegates to CacheOperations and CacheMetrics)
    # =========================================================================

    @classmethod
    async def cleanup_expired(cls, pattern: str = "lumen:*") -> int:
        """Clean up expired cache entries."""
        return await CacheOperations.cleanup_expired(pattern)

    @classmethod
    def get_metrics(cls) -> Dict[str, Any]:
        """
        Get comprehensive cache performance metrics.

        Returns
        -------
        Dict[str, Any]
            Dictionary with hits, misses, hit rate, timing, compression ratio, errors.
        """
        return CacheMetrics.get_metrics()

    @classmethod
    def get_hit_rate(cls) -> float:
        """
        Calculate cache hit rate percentage.

        Returns
        -------
        float
            Hit rate as percentage (0-100).
        """
        return CacheMetrics.get_hit_rate()

    @classmethod
    def is_healthy(cls) -> bool:
        """
        Check if cache service is healthy.

        Returns
        -------
        bool
            True if cache is healthy and performing well.
        """
        return CacheMetrics.is_healthy()

    @classmethod
    def reset_metrics(cls) -> None:
        """Reset all metrics counters."""
        CacheMetrics.reset_metrics()
        logger.info("Cache metrics reset")

    @classmethod
    async def health_check(cls) -> Dict[str, Any]:
        """
        Perform comprehensive cache health check.

        Returns
        -------
        Dict[str, Any]
            Health status including Redis availability, metrics, and status.
        """
        redis_available = await RedisService.health_check()
        metrics = cls.get_metrics()
        is_healthy = cls.is_healthy()

        return {
            "redis_available": redis_available,
            "hit_rate": metrics["hit_rate"],
            "compression_ratio": metrics["compression_ratio"],
            "total_operations": metrics["total_operations"],
            "errors": metrics["errors"],
            "avg_get_time_ms": metrics["avg_get_time_ms"],
            "is_healthy": is_healthy,
            "status": "healthy" if (redis_available and is_healthy) else "degraded",
        }
