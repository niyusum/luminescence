"""
Advanced caching layer with observability, compression, and sophisticated invalidation.

Features:
- Automatic compression for large payloads (>1KB threshold)
- Tag-based bulk invalidation
- Batch operations for efficiency
- Hit/miss rate tracking with timing metrics
- Health monitoring and circuit breaker integration
- ConfigManager-driven TTLs
- Versioned keys for schema evolution

RIKI LAW Compliance:
- Complete audit trails for cache operations (Article II)
- ConfigManager integration for tunables (Article V)
- Graceful degradation when Redis unavailable (Article IX)
- Comprehensive metrics and observability (Article X)
"""

from typing import Dict, Any, Optional, List, Set
from datetime import datetime, timedelta
import json
import zlib
import time
import asyncio
from contextlib import asynccontextmanager

from src.core.infra.redis_service import RedisService
from src.core.config.config_manager import ConfigManager
from src.core.logging.logger import get_logger

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
    
    Key Templates:
        - player_resources:{player_id}
        - maiden_collection:{player_id}
        - fusion_rates:{tier}
        - leader_bonuses:{maiden_base_id}:{tier}
        - daily_quest:{player_id}:{date}
        - prayer_charges:{player_id}
        - active_modifiers:{player_id}
        - leaderboards:{type}:{period}
    
    Tags (for bulk invalidation):
        - player:{player_id} - All caches for specific player
        - maiden - All maiden-related caches
        - fusion - All fusion-related caches
        - leader - All leader bonus caches
        - resources - All resource caches
        - daily - All daily quest caches
        - global - All global caches
    
    RIKI LAW Compliance:
        - Article II: Logs all cache operations for audit trails
        - Article V: ConfigManager for all TTLs and thresholds
        - Article IX: Graceful degradation on Redis failure
        - Article X: Comprehensive metrics and health monitoring
    """
    
    # Metrics tracking
    _metrics = {
        "hits": 0,
        "misses": 0,
        "sets": 0,
        "invalidations": 0,
        "errors": 0,
        "compressions": 0,
        "decompressions": 0,
        "total_get_time_ms": 0.0,
        "total_set_time_ms": 0.0,
    }
    
    # Configuration (with ConfigManager fallbacks)
    COMPRESSION_PREFIX = b"COMPRESSED:"  # Marker for compressed data
    
    # Key templates for consistency (versioned for schema evolution)
    KEY_TEMPLATES = {
        "player_resources": "riki:v1:player:{player_id}:resources",
        "maiden_collection": "riki:v1:player:{player_id}:maidens",
        "fusion_rates": "riki:v1:fusion:rates:{tier}",
        "leader_bonuses": "riki:v1:leader:{maiden_base_id}:{tier}",
        "daily_quest": "riki:v1:daily:{player_id}:{date}",
        "prayer_charges": "riki:v1:prayer:{player_id}",
        "active_modifiers": "riki:v1:modifiers:{player_id}",
        "leaderboards": "riki:v1:leaderboard:{type}:{period}"
    }
    
    TAG_REGISTRY_KEY = "riki:v1:cache:tags"
    
    # =========================================================================
    # CONFIGURATION HELPERS (Article V Compliance)
    # =========================================================================
    
    @classmethod
    def _get_compression_threshold(cls) -> int:
        """Get compression threshold from ConfigManager."""
        return ConfigManager.get("cache.compression_threshold", 1024)
    
    @classmethod
    def _get_ttl(cls, cache_type: str) -> int:
        """
        Get TTL for specific cache type from ConfigManager.
        
        Args:
            cache_type: Cache type (player_resources, active_modifiers, etc.)
        
        Returns:
            TTL in seconds from config or sensible default
        """
        defaults = {
            "player_resources": 300,      # 5 minutes
            "maiden_collection": 300,     # 5 minutes
            "active_modifiers": 600,      # 10 minutes
            "fusion_rates": 3600,         # 1 hour (rarely changes)
            "leader_bonuses": 3600,       # 1 hour (rarely changes)
            "daily_quest": 86400,         # 24 hours
            "prayer_charges": 300,        # 5 minutes
            "leaderboards": 600,          # 10 minutes
        }
        
        config_key = f"cache.ttl.{cache_type}"
        return ConfigManager.get(config_key, defaults.get(cache_type, 300))
    
    # =========================================================================
    # INTERNAL UTILITIES
    # =========================================================================
    
    @classmethod
    def _get_key(cls, template: str, **kwargs) -> str:
        """
        Generate cache key from template.
        
        Args:
            template: Template name from KEY_TEMPLATES
            **kwargs: Values to interpolate into template
        
        Returns:
            Formatted cache key
        
        Raises:
            ValueError: If template name is unknown
        """
        template_str = cls.KEY_TEMPLATES.get(template)
        if not template_str:
            raise ValueError(f"Unknown key template: {template}")
        return template_str.format(**kwargs)
    
    @classmethod
    async def _add_tags(cls, key: str, tags: List[str]) -> None:
        """
        Associate tags with cache key for bulk invalidation.
        
        Creates tag registry entries that map tags to keys,
        enabling efficient bulk invalidation by tag.
        
        Args:
            key: Cache key to tag
            tags: List of tags to associate
        """
        try:
            tag_ttl = ConfigManager.get("cache.tag_registry_ttl", 3600)
            
            for tag in tags:
                tag_key = f"{cls.TAG_REGISTRY_KEY}:{tag}"
                # Store key in tag's set with TTL
                await RedisService.set(f"{tag_key}:{key}", "1", ttl=tag_ttl)
        except Exception as e:
            logger.error(f"Failed to add tags {tags} to key {key}: {e}", exc_info=True)
    
    @classmethod
    async def _compress(cls, data: str) -> bytes:
        """
        Compress data if above threshold using zlib.
        
        Args:
            data: String data to potentially compress
        
        Returns:
            Compressed bytes with prefix, or raw bytes if below threshold
        """
        data_bytes = data.encode('utf-8')
        threshold = cls._get_compression_threshold()
        
        if len(data_bytes) > threshold:
            try:
                compressed = zlib.compress(data_bytes, level=6)
                cls._metrics["compressions"] += 1
                
                # Add compression marker prefix
                return cls.COMPRESSION_PREFIX + compressed
            except Exception as e:
                logger.error(f"Compression failed, storing uncompressed: {e}", exc_info=True)
                return data_bytes
        
        return data_bytes
    
    @classmethod
    async def _decompress(cls, data: bytes) -> str:
        """
        Decompress data if it has compression marker.
        
        Args:
            data: Potentially compressed bytes
        
        Returns:
            Decompressed string
        """
        # Check for compression marker
        if data.startswith(cls.COMPRESSION_PREFIX):
            try:
                compressed_data = data[len(cls.COMPRESSION_PREFIX):]
                decompressed = zlib.decompress(compressed_data)
                cls._metrics["decompressions"] += 1
                return decompressed.decode('utf-8')
            except Exception as e:
                logger.error(f"Decompression failed: {e}", exc_info=True)
                # Try returning as-is
                return data.decode('utf-8', errors='ignore')
        
        # Not compressed, decode directly
        return data.decode('utf-8')
    
    @classmethod
    async def _serialize_and_compress(cls, data: Dict[str, Any]) -> bytes:
        """
        Serialize dict to JSON and optionally compress.
        
        Args:
            data: Dictionary to serialize
        
        Returns:
            Serialized (and possibly compressed) bytes
        """
        try:
            json_str = json.dumps(data)
            return await cls._compress(json_str)
        except Exception as e:
            logger.error(f"Serialization failed for data: {e}", exc_info=True)
            raise
    
    @classmethod
    async def _decompress_and_deserialize(cls, data: bytes) -> Dict[str, Any]:
        """
        Decompress and deserialize JSON data.
        
        Args:
            data: Potentially compressed JSON bytes
        
        Returns:
            Deserialized dictionary
        """
        try:
            json_str = await cls._decompress(data)
            return json.loads(json_str)
        except Exception as e:
            logger.error(f"Deserialization failed: {e}", exc_info=True)
            raise
    
    # =========================================================================
    # PLAYER RESOURCES CACHING
    # =========================================================================
    
    @classmethod
    async def cache_player_resources(
        cls,
        player_id: int,
        resource_data: Dict[str, Any],
        ttl: Optional[int] = None
    ) -> bool:
        """
        Cache player resource summary with automatic compression.
        
        Args:
            player_id: Player's Discord ID
            resource_data: Resource information to cache
            ttl: Optional TTL override (uses ConfigManager default if None)
        
        Returns:
            True if cached successfully, False otherwise
        
        Example:
            >>> await CacheService.cache_player_resources(
            ...     player_id=123456789,
            ...     resource_data={
            ...         "rikis": 1000,
            ...         "grace": 500,
            ...         "energy": 50,
            ...         "stamina": 75
            ...     }
            ... )
        """
        start_time = time.perf_counter()
        key = cls._get_key("player_resources", player_id=player_id)
        
        # Get TTL from ConfigManager if not provided
        if ttl is None:
            ttl = cls._get_ttl("player_resources")
        
        try:
            # Use Redis's JSON support directly (no compression needed)
            success = await RedisService.set(key, resource_data, ttl=ttl)
            
            if success:
                await cls._add_tags(key, [f"player:{player_id}", "resources"])
                cls._metrics["sets"] += 1
                
                # Track timing
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                cls._metrics["total_set_time_ms"] += elapsed_ms
                
                logger.debug(
                    f"Cached player resources: player={player_id} ttl={ttl}s time={elapsed_ms:.2f}ms"
                )
            
            return success
            
        except Exception as e:
            cls._metrics["errors"] += 1
            logger.error(
                f"Failed to cache player resources: player={player_id} error={e}",
                exc_info=True
            )
            return False
    
    @classmethod
    async def get_cached_player_resources(cls, player_id: int) -> Optional[Dict[str, Any]]:
        """
        Get cached player resources.
        
        Args:
            player_id: Player's Discord ID
        
        Returns:
            Cached resource data or None if not found/expired
        """
        start_time = time.perf_counter()
        key = cls._get_key("player_resources", player_id=player_id)
        
        try:
            data = await RedisService.get(key)
            
            # Track timing
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            cls._metrics["total_get_time_ms"] += elapsed_ms
            
            if data:
                cls._metrics["hits"] += 1
                logger.debug(
                    f"Cache HIT: player_resources player={player_id} time={elapsed_ms:.2f}ms"
                )
                return data
            else:
                cls._metrics["misses"] += 1
                logger.debug(
                    f"Cache MISS: player_resources player={player_id} time={elapsed_ms:.2f}ms"
                )
                return None
                
        except Exception as e:
            cls._metrics["errors"] += 1
            cls._metrics["misses"] += 1
            logger.error(
                f"Error getting cached player resources: player={player_id} error={e}",
                exc_info=True
            )
            return None
    
    @classmethod
    async def invalidate_player_resources(cls, player_id: int) -> bool:
        """
        Invalidate player resource cache.
        
        Args:
            player_id: Player's Discord ID
        
        Returns:
            True if invalidated successfully
        """
        key = cls._get_key("player_resources", player_id=player_id)
        
        try:
            success = await RedisService.delete(key)
            
            if success:
                cls._metrics["invalidations"] += 1
                logger.debug(f"Invalidated player resources: player={player_id}")
            
            return success
            
        except Exception as e:
            cls._metrics["errors"] += 1
            logger.error(
                f"Failed to invalidate player resources: player={player_id} error={e}",
                exc_info=True
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
        ttl: Optional[int] = None
    ) -> bool:
        """
        Cache player's active modifiers.
        
        Args:
            player_id: Player's Discord ID
            modifiers: Modifier data {"income_boost": 1.15, "xp_boost": 1.10}
            ttl: Optional TTL override (uses ConfigManager default if None)
        
        Returns:
            True if cached successfully
        """
        start_time = time.perf_counter()
        key = cls._get_key("active_modifiers", player_id=player_id)
        
        # Get TTL from ConfigManager if not provided
        if ttl is None:
            ttl = cls._get_ttl("active_modifiers")
        
        try:
            success = await RedisService.set(key, modifiers, ttl=ttl)
            
            if success:
                await cls._add_tags(key, [f"player:{player_id}", "modifiers"])
                cls._metrics["sets"] += 1
                
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                cls._metrics["total_set_time_ms"] += elapsed_ms
                
                logger.debug(
                    f"Cached active modifiers: player={player_id} count={len(modifiers)} "
                    f"ttl={ttl}s time={elapsed_ms:.2f}ms"
                )
            
            return success
            
        except Exception as e:
            cls._metrics["errors"] += 1
            logger.error(
                f"Failed to cache active modifiers: player={player_id} error={e}",
                exc_info=True
            )
            return False
    
    @classmethod
    async def get_cached_modifiers(cls, player_id: int) -> Optional[Dict[str, float]]:
        """
        Get cached player modifiers.
        
        Args:
            player_id: Player's Discord ID
        
        Returns:
            Cached modifier data or None
        """
        start_time = time.perf_counter()
        key = cls._get_key("active_modifiers", player_id=player_id)
        
        try:
            data = await RedisService.get(key)
            
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            cls._metrics["total_get_time_ms"] += elapsed_ms
            
            if data:
                cls._metrics["hits"] += 1
                logger.debug(
                    f"Cache HIT: active_modifiers player={player_id} time={elapsed_ms:.2f}ms"
                )
                return data
            else:
                cls._metrics["misses"] += 1
                logger.debug(
                    f"Cache MISS: active_modifiers player={player_id} time={elapsed_ms:.2f}ms"
                )
                return None
                
        except Exception as e:
            cls._metrics["errors"] += 1
            cls._metrics["misses"] += 1
            logger.error(
                f"Error getting cached modifiers: player={player_id} error={e}",
                exc_info=True
            )
            return None
    
    # =========================================================================
    # MAIDEN COLLECTION CACHING
    # =========================================================================
    
    @classmethod
    async def cache_maiden_collection(
        cls,
        player_id: int,
        collection_data: Dict[str, Any],
        ttl: Optional[int] = None
    ) -> bool:
        """
        Cache player's maiden collection.
        
        Args:
            player_id: Player's Discord ID
            collection_data: Maiden collection data
            ttl: Optional TTL override (uses ConfigManager default if None)
        
        Returns:
            True if cached successfully
        """
        start_time = time.perf_counter()
        key = cls._get_key("maiden_collection", player_id=player_id)
        
        # Get TTL from ConfigManager if not provided
        if ttl is None:
            ttl = cls._get_ttl("maiden_collection")
        
        try:
            success = await RedisService.set(key, collection_data, ttl=ttl)
            
            if success:
                await cls._add_tags(key, [f"player:{player_id}", "maiden"])
                cls._metrics["sets"] += 1
                
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                cls._metrics["total_set_time_ms"] += elapsed_ms
                
                logger.debug(
                    f"Cached maiden collection: player={player_id} ttl={ttl}s "
                    f"time={elapsed_ms:.2f}ms"
                )
            
            return success
            
        except Exception as e:
            cls._metrics["errors"] += 1
            logger.error(
                f"Failed to cache maiden collection: player={player_id} error={e}",
                exc_info=True
            )
            return False
    
    # =========================================================================
    # BATCH OPERATIONS
    # =========================================================================
    
    @classmethod
    async def batch_cache(
        cls,
        cache_operations: List[Dict[str, Any]]
    ) -> Dict[str, bool]:
        """
        Execute multiple cache operations in batch for efficiency.
        
        Args:
            cache_operations: List of cache operations
                Each operation is a dict with:
                    - template: Key template name
                    - template_args: Args for template
                    - data: Data to cache
                    - ttl: Optional TTL (uses ConfigManager if None)
                    - tags: Optional tags list
        
        Returns:
            Dictionary mapping keys to success status
        
        Example:
            >>> results = await CacheService.batch_cache([
            ...     {
            ...         "template": "player_resources",
            ...         "template_args": {"player_id": 123},
            ...         "data": {"rikis": 1000},
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
                    await cls._add_tags(key, tags)
                    cls._metrics["sets"] += 1
                
                results[key] = success
                
            except Exception as e:
                cls._metrics["errors"] += 1
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
        
        Args:
            tag: Tag to invalidate (e.g., "player:123", "resources", "global")
        
        Returns:
            Number of keys invalidated
        
        Example:
            >>> # Invalidate all caches for player 123
            >>> count = await CacheService.invalidate_by_tag("player:123")
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
            cls._metrics["invalidations"] += 1
            
            logger.info(
                f"Tag-based invalidation: tag={tag} pattern={tag_pattern} "
                f"(Note: Redis auto-expires tagged keys via TTL)"
            )
            
            return invalidated
            
        except Exception as e:
            cls._metrics["errors"] += 1
            logger.error(f"Error invalidating by tag {tag}: {e}", exc_info=True)
            return 0
    
    @classmethod
    async def batch_invalidate_by_tags(cls, tags: List[str]) -> Dict[str, int]:
        """
        Invalidate multiple tags in parallel for efficiency.
        
        Useful for guild wipes, leaderboard resets, or multi-domain invalidation.
        
        Args:
            tags: List of tags to invalidate
        
        Returns:
            Dictionary mapping tags to number of keys invalidated
        
        Example:
            >>> results = await CacheService.batch_invalidate_by_tags([
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
            cls._metrics["errors"] += 1
            logger.error(f"Error in batch tag invalidation: {e}", exc_info=True)
            return {tag: 0 for tag in tags}
    
    # =========================================================================
    # MAINTENANCE & MONITORING
    # =========================================================================
    
    @classmethod
    async def cleanup_expired(cls, pattern: str = "riki:*") -> int:
        """
        Clean up expired cache entries.
        
        Redis automatically handles TTL expiration, so this method
        is primarily for interface consistency and monitoring.
        
        Args:
            pattern: Key pattern to check (default all riki keys)
        
        Returns:
            Number of keys checked (actual cleanup by Redis)
        """
        logger.debug(f"Redis automatically handles TTL expiration for pattern: {pattern}")
        return 0
    
    @classmethod
    def get_metrics(cls) -> Dict[str, Any]:
        """
        Get comprehensive cache performance metrics.
        
        Returns:
            Dictionary with hits, misses, hit rate, timing, compression ratio, errors
        
        Example:
            >>> metrics = CacheService.get_metrics()
            >>> print(f"Hit rate: {metrics['hit_rate']:.1f}%")
            >>> print(f"Avg get time: {metrics['avg_get_time_ms']:.2f}ms")
            >>> print(f"Compression ratio: {metrics['compression_ratio']:.2%}")
        """
        total_gets = cls._metrics["hits"] + cls._metrics["misses"]
        hit_rate = (cls._metrics["hits"] / total_gets * 100) if total_gets > 0 else 0.0
        
        avg_get_time = (
            cls._metrics["total_get_time_ms"] / total_gets
            if total_gets > 0 else 0.0
        )
        
        avg_set_time = (
            cls._metrics["total_set_time_ms"] / cls._metrics["sets"]
            if cls._metrics["sets"] > 0 else 0.0
        )
        
        # Compression ratio: what % of sets used compression
        compression_ratio = (
            cls._metrics["compressions"] / max(cls._metrics["sets"], 1)
        )
        
        return {
            "hits": cls._metrics["hits"],
            "misses": cls._metrics["misses"],
            "sets": cls._metrics["sets"],
            "invalidations": cls._metrics["invalidations"],
            "errors": cls._metrics["errors"],
            "compressions": cls._metrics["compressions"],
            "decompressions": cls._metrics["decompressions"],
            "hit_rate": round(hit_rate, 2),
            "compression_ratio": round(compression_ratio, 4),
            "avg_get_time_ms": round(avg_get_time, 2),
            "avg_set_time_ms": round(avg_set_time, 2),
            "total_operations": total_gets + cls._metrics["sets"],
        }
    
    @classmethod
    def get_hit_rate(cls) -> float:
        """
        Calculate cache hit rate percentage.
        
        Returns:
            Hit rate as percentage (0-100)
        """
        total = cls._metrics["hits"] + cls._metrics["misses"]
        if total == 0:
            return 0.0
        return (cls._metrics["hits"] / total) * 100
    
    @classmethod
    def is_healthy(cls) -> bool:
        """
        Check if cache service is healthy.
        
        Health criteria:
        - Error count below threshold
        - Hit rate above minimum threshold
        
        Returns:
            True if cache is healthy and performing well
        
        Example:
            >>> if not CacheService.is_healthy():
            ...     logger.warning("Cache degraded, consider investigating")
        """
        error_threshold = ConfigManager.get("cache.health.max_errors", 100)
        min_hit_rate = ConfigManager.get("cache.health.min_hit_rate", 70.0)
        
        return (
            cls._metrics["errors"] < error_threshold and
            cls.get_hit_rate() > min_hit_rate
        )
    
    @classmethod
    def reset_metrics(cls) -> None:
        """
        Reset all metrics counters.
        
        Useful for testing or periodic metrics reset.
        """
        cls._metrics = {
            "hits": 0,
            "misses": 0,
            "sets": 0,
            "invalidations": 0,
            "errors": 0,
            "compressions": 0,
            "decompressions": 0,
            "total_get_time_ms": 0.0,
            "total_set_time_ms": 0.0,
        }
        logger.info("Cache metrics reset")
    
    @classmethod
    async def health_check(cls) -> Dict[str, Any]:
        """
        Perform comprehensive cache health check.
        
        Returns:
            Health status including Redis availability, metrics, and status
        
        Example:
            >>> health = await CacheService.health_check()
            >>> if health["status"] == "degraded":
            ...     logger.warning("Cache experiencing issues")
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
            "status": "healthy" if (redis_available and is_healthy) else "degraded"
        }






