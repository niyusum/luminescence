"""
Cache metrics tracking and health monitoring for Lumen (2025).

Purpose
-------
- Track cache performance metrics (hits, misses, latencies).
- Monitor cache health and compression efficiency.
- Provide observability for cache operations.

Responsibilities
----------------
- Maintain metrics counters for cache operations.
- Calculate derived metrics (hit rate, compression ratio).
- Provide health checks and status monitoring.
- Support metrics reset for testing.

Non-Responsibilities
--------------------
- Cache storage or retrieval (handled by service module).
- Tag management or invalidation (handled by operations module).
- Configuration management (handled by ConfigManager).

Lumen 2025 Compliance
---------------------
- **Observability**: Comprehensive metrics for all cache operations (Article X).
- **Type safety**: Strongly-typed metrics tracking.
- **Separation of concerns**: Pure metrics logic, no cache operations.

Architecture Notes
------------------
- Metrics stored in-memory using class-level dictionary.
- Thread-safe for async operations.
- Derived metrics calculated on-demand.

Dependencies
------------
- ConfigManager for health thresholds.
- Standard library only (typing, Dict, Any).
"""

from typing import Any, Dict

from src.core.config import ConfigManager


class CacheMetrics:
    """Cache performance metrics tracker."""

    # Metrics tracking
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

    @classmethod
    def record_hit(cls) -> None:
        """Record a cache hit."""
        cls._metrics["hits"] += 1

    @classmethod
    def record_miss(cls) -> None:
        """Record a cache miss."""
        cls._metrics["misses"] += 1

    @classmethod
    def record_set(cls) -> None:
        """Record a cache set operation."""
        cls._metrics["sets"] += 1

    @classmethod
    def record_invalidation(cls) -> None:
        """Record a cache invalidation."""
        cls._metrics["invalidations"] += 1

    @classmethod
    def record_error(cls) -> None:
        """Record a cache error."""
        cls._metrics["errors"] += 1

    @classmethod
    def record_compression(cls) -> None:
        """Record a compression operation."""
        cls._metrics["compressions"] += 1

    @classmethod
    def record_decompression(cls) -> None:
        """Record a decompression operation."""
        cls._metrics["decompressions"] += 1

    @classmethod
    def record_get_time(cls, elapsed_ms: float) -> None:
        """Record GET operation latency."""
        cls._metrics["total_get_time_ms"] += elapsed_ms

    @classmethod
    def record_set_time(cls, elapsed_ms: float) -> None:
        """Record SET operation latency."""
        cls._metrics["total_set_time_ms"] += elapsed_ms

    @classmethod
    def get_metrics(cls) -> Dict[str, Any]:
        """
        Get comprehensive cache performance metrics.

        Returns
        -------
        Dict[str, Any]
            Dictionary with hits, misses, hit rate, timing, compression ratio, errors.

        Example
        -------
        >>> metrics = CacheMetrics.get_metrics()
        >>> print(f"Hit rate: {metrics['hit_rate']:.1f}%")
        >>> print(f"Avg get time: {metrics['avg_get_time_ms']:.2f}ms")
        >>> print(f"Compression ratio: {metrics['compression_ratio']:.2%}")
        """
        total_gets = cls._metrics["hits"] + cls._metrics["misses"]
        hit_rate = (cls._metrics["hits"] / total_gets * 100) if total_gets > 0 else 0.0

        avg_get_time = (
            cls._metrics["total_get_time_ms"] / total_gets if total_gets > 0 else 0.0
        )

        avg_set_time = (
            cls._metrics["total_set_time_ms"] / cls._metrics["sets"]
            if cls._metrics["sets"] > 0
            else 0.0
        )

        # Compression ratio: what % of sets used compression
        compression_ratio = cls._metrics["compressions"] / max(cls._metrics["sets"], 1)

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

        Returns
        -------
        float
            Hit rate as percentage (0-100).
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

        Returns
        -------
        bool
            True if cache is healthy and performing well.

        Example
        -------
        >>> if not CacheMetrics.is_healthy():
        ...     logger.warning("Cache degraded, consider investigating")
        """
        error_threshold = ConfigManager.get("cache.health.max_errors", 100)
        min_hit_rate = ConfigManager.get("cache.health.min_hit_rate", 70.0)

        return (
            cls._metrics["errors"] < error_threshold
            and cls.get_hit_rate() > min_hit_rate
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
