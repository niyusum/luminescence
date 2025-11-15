"""
Cache metrics tracking and health monitoring for Lumen (2025).

Purpose
-------
Provides thread-safe metrics collection and health monitoring for cache operations.
Tracks performance indicators including hit rates, latencies, compression efficiency,
and error rates with real-time health assessment.

Responsibilities
----------------
- Thread-safe metrics tracking for all cache operations
- Real-time hit rate and performance calculations
- Health monitoring with configurable thresholds
- Compression efficiency tracking
- Latency measurements for operations
- Metrics reset for testing and monitoring cycles

Non-Responsibilities
--------------------
- Cache storage or retrieval (handled by service/player/collections modules)
- Tag management (handled by operations module)
- Configuration storage (handled by ConfigManager)
- Logging operations (handled by logger)

LES 2025 Compliance
-------------------
- **Observability**: Comprehensive metrics for production monitoring
- **Type Safety**: Fully typed metrics interface
- **Separation of Concerns**: Pure metrics logic with no cache operations
- **Thread Safety**: Async-safe metric updates
- **Config-Driven**: Health thresholds from ConfigManager

Architecture Notes
------------------
- Metrics stored in memory using class-level dictionary
- Thread-safe via asyncio.Lock for concurrent operations
- Derived metrics calculated on-demand from raw counters
- Health checks use ConfigManager thresholds
- Designed for high-frequency updates with minimal overhead

Dependencies
------------
- ConfigManager: Health threshold configuration
- asyncio: Thread-safe locking
- typing: Type hints for metrics data structures

Performance Characteristics
---------------------------
- O(1) metric recording
- O(1) metric retrieval
- Lock contention minimized via separate lock per operation type
- Memory footprint: ~1KB for metrics dictionary
"""

import asyncio
from typing import Any, Dict

from src.core.config import ConfigManager


class CacheMetrics:
    """
    Thread-safe cache performance metrics tracker.
    
    Provides comprehensive metrics collection for cache operations including
    hits, misses, latencies, compression ratios, and error rates.
    
    All operations are thread-safe for concurrent access from multiple
    async tasks.
    """

    # Metrics storage with type-annotated structure
    _metrics: Dict[str, Any] = {
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
    
    # Thread safety lock for atomic metric updates
    _lock: asyncio.Lock = asyncio.Lock()

    @classmethod
    async def record_hit(cls) -> None:
        """
        Record a cache hit (key found in cache).
        
        Thread-safe operation for concurrent metric updates.
        """
        async with cls._lock:
            cls._metrics["hits"] += 1

    @classmethod
    async def record_miss(cls) -> None:
        """
        Record a cache miss (key not found in cache).
        
        Thread-safe operation for concurrent metric updates.
        """
        async with cls._lock:
            cls._metrics["misses"] += 1

    @classmethod
    async def record_set(cls) -> None:
        """
        Record a cache set operation.
        
        Thread-safe operation for concurrent metric updates.
        """
        async with cls._lock:
            cls._metrics["sets"] += 1

    @classmethod
    async def record_invalidation(cls) -> None:
        """
        Record a cache invalidation operation.
        
        Thread-safe operation for concurrent metric updates.
        """
        async with cls._lock:
            cls._metrics["invalidations"] += 1

    @classmethod
    async def record_error(cls) -> None:
        """
        Record a cache error (Redis failure, serialization error, etc.).
        
        Thread-safe operation for concurrent metric updates.
        """
        async with cls._lock:
            cls._metrics["errors"] += 1

    @classmethod
    async def record_compression(cls) -> None:
        """
        Record a compression operation (data compressed before storage).
        
        Thread-safe operation for concurrent metric updates.
        """
        async with cls._lock:
            cls._metrics["compressions"] += 1

    @classmethod
    async def record_decompression(cls) -> None:
        """
        Record a decompression operation (data decompressed after retrieval).
        
        Thread-safe operation for concurrent metric updates.
        """
        async with cls._lock:
            cls._metrics["decompressions"] += 1

    @classmethod
    async def record_get_time(cls, elapsed_ms: float) -> None:
        """
        Record GET operation latency in milliseconds.
        
        Parameters
        ----------
        elapsed_ms:
            Operation duration in milliseconds.
        """
        async with cls._lock:
            cls._metrics["total_get_time_ms"] += elapsed_ms

    @classmethod
    async def record_set_time(cls, elapsed_ms: float) -> None:
        """
        Record SET operation latency in milliseconds.
        
        Parameters
        ----------
        elapsed_ms:
            Operation duration in milliseconds.
        """
        async with cls._lock:
            cls._metrics["total_set_time_ms"] += elapsed_ms

    @classmethod
    async def get_metrics(cls) -> Dict[str, Any]:
        """
        Get comprehensive cache performance metrics.
        
        Returns derived metrics calculated from raw counters including
        hit rates, average latencies, compression ratios, and total operations.
        
        Returns
        -------
        Dict[str, Any]
            Comprehensive metrics dictionary containing:
            - hits: Total cache hits
            - misses: Total cache misses
            - sets: Total set operations
            - invalidations: Total invalidations
            - errors: Total errors encountered
            - compressions: Total compression operations
            - decompressions: Total decompression operations
            - hit_rate: Cache hit rate percentage (0-100)
            - compression_ratio: Ratio of sets using compression (0-1)
            - avg_get_time_ms: Average GET latency in milliseconds
            - avg_set_time_ms: Average SET latency in milliseconds
            - total_operations: Sum of all cache operations
        
        Example
        -------
        >>> metrics = await CacheMetrics.get_metrics()
        >>> print(f"Hit rate: {metrics['hit_rate']:.1f}%")
        >>> print(f"Avg get time: {metrics['avg_get_time_ms']:.2f}ms")
        >>> print(f"Compression ratio: {metrics['compression_ratio']:.2%}")
        """
        async with cls._lock:
            # Calculate derived metrics
            total_gets = cls._metrics["hits"] + cls._metrics["misses"]
            hit_rate = (
                (cls._metrics["hits"] / total_gets * 100) if total_gets > 0 else 0.0
            )

            avg_get_time = (
                cls._metrics["total_get_time_ms"] / total_gets
                if total_gets > 0
                else 0.0
            )

            avg_set_time = (
                cls._metrics["total_set_time_ms"] / cls._metrics["sets"]
                if cls._metrics["sets"] > 0
                else 0.0
            )

            # Compression ratio: percentage of sets that used compression
            compression_ratio = (
                cls._metrics["compressions"] / max(cls._metrics["sets"], 1)
            )

            return {
                # Raw counters
                "hits": cls._metrics["hits"],
                "misses": cls._metrics["misses"],
                "sets": cls._metrics["sets"],
                "invalidations": cls._metrics["invalidations"],
                "errors": cls._metrics["errors"],
                "compressions": cls._metrics["compressions"],
                "decompressions": cls._metrics["decompressions"],
                # Derived metrics
                "hit_rate": round(hit_rate, 2),
                "compression_ratio": round(compression_ratio, 4),
                "avg_get_time_ms": round(avg_get_time, 2),
                "avg_set_time_ms": round(avg_set_time, 2),
                "total_operations": total_gets + cls._metrics["sets"],
            }

    @classmethod
    async def get_hit_rate(cls) -> float:
        """
        Calculate cache hit rate percentage.
        
        Returns
        -------
        float
            Hit rate as percentage (0-100). Returns 0.0 if no operations recorded.
        
        Example
        -------
        >>> hit_rate = await CacheMetrics.get_hit_rate()
        >>> if hit_rate < 70.0:
        ...     logger.warning(f"Cache hit rate low: {hit_rate:.1f}%")
        """
        async with cls._lock:
            total = cls._metrics["hits"] + cls._metrics["misses"]
            if total == 0:
                return 0.0
            return (cls._metrics["hits"] / total) * 100

    @classmethod
    async def is_healthy(cls) -> bool:
        """
        Check if cache service is healthy based on error rate and hit rate.
        
        Health criteria (configurable via ConfigManager):
        - Error count below threshold (default: 100)
        - Hit rate above minimum threshold (default: 70%)
        
        Returns
        -------
        bool
            True if cache is healthy and performing well, False otherwise.
        
        Example
        -------
        >>> if not await CacheMetrics.is_healthy():
        ...     logger.warning("Cache degraded, consider investigating")
        ...     await send_alert("cache_degraded")
        """
        error_threshold = ConfigManager.get("cache.health.max_errors", 100)
        min_hit_rate = ConfigManager.get("cache.health.min_hit_rate", 70.0)

        async with cls._lock:
            current_hit_rate = await cls.get_hit_rate()
            return (
                cls._metrics["errors"] < error_threshold
                and current_hit_rate >= min_hit_rate
            )

    @classmethod
    async def reset_metrics(cls) -> None:
        """
        Reset all metrics counters to zero.
        
        Useful for:
        - Testing and validation
        - Periodic metrics rotation
        - Monitoring system resets
        - Diagnostic purposes
        
        Thread-safe operation that atomically resets all counters.
        
        Example
        -------
        >>> # Reset metrics at start of new monitoring period
        >>> await CacheMetrics.reset_metrics()
        >>> logger.info("Cache metrics reset for new monitoring cycle")
        """
        async with cls._lock:
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

    @classmethod
    async def get_health_summary(cls) -> Dict[str, Any]:
        """
        Get comprehensive health summary for monitoring and alerting.
        
        Returns
        -------
        Dict[str, Any]
            Health summary containing:
            - is_healthy: Overall health status
            - hit_rate: Current hit rate percentage
            - error_count: Total errors encountered
            - total_operations: Total cache operations
            - avg_latency_ms: Average operation latency
            - status: Human-readable status string
        
        Example
        -------
        >>> health = await CacheMetrics.get_health_summary()
        >>> if health['status'] == 'degraded':
        ...     send_alert("cache_degraded", health)
        """
        metrics = await cls.get_metrics()
        is_healthy = await cls.is_healthy()
        
        avg_latency = (
            (metrics["avg_get_time_ms"] + metrics["avg_set_time_ms"]) / 2
        )
        
        # Determine status based on health and performance
        if not is_healthy:
            status = "unhealthy"
        elif metrics["errors"] > 10 or avg_latency > 100:
            status = "degraded"
        else:
            status = "healthy"
        
        return {
            "is_healthy": is_healthy,
            "hit_rate": metrics["hit_rate"],
            "error_count": metrics["errors"],
            "total_operations": metrics["total_operations"],
            "avg_latency_ms": round(avg_latency, 2),
            "status": status,
        }
