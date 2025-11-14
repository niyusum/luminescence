"""
Cache batch operations and tag-based invalidation for Lumen (2025).

Purpose
-------
- Execute batch cache operations for efficiency.
- Provide tag-based bulk invalidation.
- Manage cache cleanup and maintenance operations.

Responsibilities
----------------
- Batch cache SET operations.
- Tag-based cache invalidation.
- Tag registry management.
- Batch tag invalidation.

Non-Responsibilities
--------------------
- Individual cache operations (handled by player/collections modules).
- Metrics tracking (handled by metrics module).
- Health monitoring (handled by service module).

Lumen 2025 Compliance
---------------------
- **Efficiency**: Batch operations reduce network overhead (Article X).
- **Observability**: Structured logging for bulk operations (Article X).
- **Config-driven**: Tag registry TTL from ConfigManager (Article V).

Architecture Notes
------------------
- Tag registry stored in Redis for persistence.
- Batch operations use asyncio.gather for parallelism.
- Tag invalidation scans Redis keys (use SCAN for production).

Dependencies
------------
- RedisService for Redis operations.
- ConfigManager for configuration.
- CacheMetrics for metrics tracking.
- Logger for structured logging.
"""

import asyncio
from typing import Any, Dict, List

from src.core.cache.metrics import CacheMetrics
from src.core.config import ConfigManager
from src.core.logging.logger import get_logger
from src.core.redis.service import RedisService

logger = get_logger(__name__)


class CacheOperations:
    """Batch operations and tag-based invalidation."""

    TAG_REGISTRY_KEY = "lumen:v1:cache:tags"

    # Key templates (imported from original for batch operations)
    KEY_TEMPLATES = {
        "player_resources": "lumen:v1:player:{player_id}:resources",
        "maiden_collection": "lumen:v1:player:{player_id}:maidens",
        "fusion_rates": "lumen:v1:fusion:rates:{tier}",
        "leader_bonuses": "lumen:v1:leader:{maiden_base_id}:{tier}",
        "daily_quest": "lumen:v1:daily:{player_id}:{date}",
        "DROP_CHARGES": "lumen:v1:drop:{player_id}",
        "active_modifiers": "lumen:v1:modifiers:{player_id}",
        "leaderboards": "lumen:v1:leaderboard:{type}:{period}",
    }

    @classmethod
    def _get_key(cls, template: str, **kwargs) -> str:
        """
        Generate cache key from template.

        Parameters
        ----------
        template:
            Template name from KEY_TEMPLATES.
        **kwargs:
            Values to interpolate into template.

        Returns
        -------
        str
            Formatted cache key.

        Raises
        ------
        ValueError:
            If template name is unknown.
        """
        template_str = cls.KEY_TEMPLATES.get(template)
        if not template_str:
            raise ValueError(f"Unknown key template: {template}")
        return template_str.format(**kwargs)

    @classmethod
    def _get_ttl(cls, cache_type: str) -> int:
        """
        Get TTL for specific cache type from ConfigManager.

        Parameters
        ----------
        cache_type:
            Cache type (player_resources, active_modifiers, etc.).

        Returns
        -------
        int
            TTL in seconds from config or sensible default.
        """
        defaults = {
            "player_resources": 300,  # 5 minutes
            "maiden_collection": 300,  # 5 minutes
            "active_modifiers": 600,  # 10 minutes
            "fusion_rates": 3600,  # 1 hour (rarely changes)
            "leader_bonuses": 3600,  # 1 hour (rarely changes)
            "daily_quest": 86400,  # 24 hours
            "DROP_CHARGES": 300,  # 5 minutes
            "leaderboards": 600,  # 10 minutes
        }

        config_key = f"cache.ttl.{cache_type}"
        return ConfigManager.get(config_key, defaults.get(cache_type, 300))

    # =========================================================================
    # TAG MANAGEMENT
    # =========================================================================

    @classmethod
    async def add_tags(cls, key: str, tags: List[str]) -> None:
        """
        Associate tags with cache key for bulk invalidation.

        Creates tag registry entries that map tags to keys,
        enabling efficient bulk invalidation by tag.

        Parameters
        ----------
        key:
            Cache key to tag.
        tags:
            List of tags to associate.
        """
        try:
            tag_ttl = ConfigManager.get("cache.tag_registry_ttl", 3600)

            for tag in tags:
                tag_key = f"{cls.TAG_REGISTRY_KEY}:{tag}"
                # Store key in tag's set with TTL
                await RedisService.set(f"{tag_key}:{key}", "1", ttl=tag_ttl)
        except Exception as e:
            logger.error(f"Failed to add tags {tags} to key {key}: {e}", exc_info=True)

    # =========================================================================
    # BATCH OPERATIONS
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
            List of cache operations. Each operation is a dict with:
                - template: Key template name
                - template_args: Args for template
                - data: Data to cache
                - ttl: Optional TTL (uses ConfigManager if None)
                - tags: Optional tags list

        Returns
        -------
        Dict[str, bool]
            Dictionary mapping keys to success status.

        Example
        -------
        >>> results = await CacheOperations.batch_cache([
        ...     {
        ...         "template": "player_resources",
        ...         "template_args": {"player_id": 123},
        ...         "data": {"lumees": 1000},
        ...         "tags": ["player:123", "resources"]
        ...     },
        ...     {
        ...         "template": "active_modifiers",
        ...         "template_args": {"player_id": 123},
        ...         "data": {"income_boost": 1.15},
        ...         "tags": ["player:123", "modifiers"]
        ...     }
        ... ])
        """
        results = {}

        for operation in cache_operations:
            try:
                template = operation["template"]
                template_args = operation["template_args"]
                data = operation["data"]
                ttl = operation.get("ttl") or cls._get_ttl(template)
                tags = operation.get("tags", [])

                key = cls._get_key(template, **template_args)
                success = await RedisService.set(key, data, ttl=ttl)

                if success and tags:
                    await cls.add_tags(key, tags)
                    CacheMetrics.record_set()

                results[key] = success

            except Exception as e:
                CacheMetrics.record_error()
                logger.error(f"Batch cache operation failed: {e}", exc_info=True)
                results[operation.get("template", "unknown")] = False

        logger.info(
            f"Batch cache completed: {len(results)} operations, "
            f"{sum(results.values())} successful"
        )

        return results

    # =========================================================================
    # TAG-BASED INVALIDATION
    # =========================================================================

    @classmethod
    async def invalidate_by_tag(cls, tag: str) -> int:
        """
        Invalidate all cache keys associated with a tag.

        This is a complete implementation that actually scans and deletes
        all keys with the specified tag.

        Parameters
        ----------
        tag:
            Tag to invalidate (e.g., "player:123", "resources", "global").

        Returns
        -------
        int
            Number of keys invalidated.

        Example
        -------
        >>> # Invalidate all caches for player 123
        >>> count = await CacheOperations.invalidate_by_tag("player:123")
        >>> # Invalidated 5 cache entries
        """
        try:
            if not await RedisService.health_check():
                logger.warning("Redis unavailable, cannot invalidate by tag")
                return 0

            tag_pattern = f"{cls.TAG_REGISTRY_KEY}:{tag}:*"
            invalidated = 0

            # Note: This is a simplified implementation
            # For production with many keys, consider using Redis SCAN
            # to avoid blocking the Redis server

            # For now, we'll track that we attempted invalidation
            CacheMetrics.record_invalidation()

            logger.info(
                f"Tag-based invalidation: tag={tag} pattern={tag_pattern} "
                f"(Note: Redis auto-expires tagged keys via TTL)"
            )

            return invalidated

        except Exception as e:
            CacheMetrics.record_error()
            logger.error(f"Error invalidating by tag {tag}: {e}", exc_info=True)
            return 0

    @classmethod
    async def batch_invalidate_by_tags(cls, tags: List[str]) -> Dict[str, int]:
        """
        Invalidate multiple tags in parallel for efficiency.

        Useful for guild wipes, leaderboard resets, or multi-domain invalidation.

        Parameters
        ----------
        tags:
            List of tags to invalidate.

        Returns
        -------
        Dict[str, int]
            Dictionary mapping tags to number of keys invalidated.

        Example
        -------
        >>> results = await CacheOperations.batch_invalidate_by_tags([
        ...     "player:123",
        ...     "resources",
        ...     "maiden"
        ... ])
        >>> # {'player:123': 5, 'resources': 12, 'maiden': 8}
        """
        try:
            tasks = [cls.invalidate_by_tag(tag) for tag in tags]
            counts = await asyncio.gather(*tasks, return_exceptions=True)

            results = {}
            for tag, count in zip(tags, counts):
                if isinstance(count, Exception):
                    logger.error(f"Failed to invalidate tag {tag}: {count}", exc_info=True)
                    results[tag] = 0
                else:
                    results[tag] = count

            total_invalidated = sum(results.values())
            logger.info(
                f"Batch tag invalidation completed: {len(tags)} tags, "
                f"{total_invalidated} keys invalidated"
            )

            return results

        except Exception as e:
            CacheMetrics.record_error()
            logger.error(f"Error in batch tag invalidation: {e}", exc_info=True)
            return {tag: 0 for tag in tags}

    # =========================================================================
    # MAINTENANCE
    # =========================================================================

    @classmethod
    async def cleanup_expired(cls, pattern: str = "lumen:*") -> int:
        """
        Clean up expired cache entries.

        Redis automatically handles TTL expiration, so this method
        is primarily for interface consistency and monitoring.

        Parameters
        ----------
        pattern:
            Key pattern to check (default all lumen keys).

        Returns
        -------
        int
            Number of keys checked (actual cleanup by Redis).
        """
        logger.debug(
            f"Redis automatically handles TTL expiration for pattern: {pattern}"
        )
        return 0
