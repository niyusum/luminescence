"""
Configuration metrics and health monitoring for Lumen (2025).

Purpose
-------
Provides thread-safe metrics collection and health monitoring for configuration
operations. Tracks performance indicators including cache hit rates, latencies,
stale reads, and error rates with real-time health assessment.

Responsibilities
----------------
- Thread-safe metrics tracking for all config operations
- Real-time cache hit rate and performance calculations
- Stale read detection and tracking
- Health monitoring with configurable thresholds
- Metrics snapshots for monitoring systems
- Support for metrics reset and inspection

Non-Responsibilities
--------------------
- Configuration storage or retrieval (handled by ConfigManager)
- Configuration validation (handled by validator module)
- Transaction management (handled by DatabaseService)
- Logging operations (handled by logger)

LES 2025 Compliance
-------------------
- **Observability**: Comprehensive metrics for production monitoring
- **Type Safety**: Strongly-typed metrics using dataclasses
- **Separation of Concerns**: Pure metrics logic with no config operations
- **Thread Safety**: Async-safe metric updates
- **Testability**: Metrics can be reset and inspected independently

Architecture Notes
------------------
- Metrics stored in dataclass with slots for efficiency
- Thread-safe via asyncio.Lock for concurrent operations
- Derived metrics calculated on-demand from raw counters
- Health snapshots designed for external monitoring systems
- Compatible with async/await patterns

Dependencies
------------
- Standard library: dataclasses, asyncio, typing
- No external dependencies

Performance Characteristics
---------------------------
- O(1) metric recording
- O(1) metric retrieval
- Lock contention minimized via single lock
- Memory footprint: ~500B for metrics dataclass
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from typing import Any, Dict


@dataclass(slots=True)
class ConfigMetrics:
    """
    Thread-safe typed metrics container for ConfigManager observability.
    
    Tracks all configuration operations including reads, writes, cache hits/misses,
    refresh operations, errors, and latencies. Supports derived metric calculations
    and health monitoring.
    """

    # Operation counts
    gets: int = 0
    sets: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    fallback_to_defaults: int = 0
    refresh_count: int = 0
    errors: int = 0
    stale_reads: int = 0

    # Latency tracking (milliseconds)
    total_get_time_ms: float = 0.0
    total_set_time_ms: float = 0.0

    # Thread safety lock
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert metrics to dictionary for logging/export.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation of all metrics (excludes lock).
        
        Example
        -------
        >>> metrics = ConfigMetrics()
        >>> metrics_dict = metrics.to_dict()
        >>> logger.info("Config metrics", extra=metrics_dict)
        """
        # Exclude the lock from serialization
        data = asdict(self)
        data.pop('_lock', None)
        return data

    async def record_get(self, elapsed_ms: float, hit: bool, stale: bool = False) -> None:
        """
        Record a GET operation with all relevant metrics.
        
        Parameters
        ----------
        elapsed_ms:
            Operation duration in milliseconds.
        hit:
            Whether the value was found in cache.
        stale:
            Whether the cached value was stale (older than TTL).
        
        Example
        -------
        >>> metrics = ConfigMetrics()
        >>> await metrics.record_get(elapsed_ms=5.2, hit=True, stale=False)
        """
        async with self._lock:
            self.gets += 1
            self.total_get_time_ms += elapsed_ms
            if hit:
                self.cache_hits += 1
            else:
                self.cache_misses += 1
            if stale:
                self.stale_reads += 1

    async def record_set(self, elapsed_ms: float) -> None:
        """
        Record a SET operation.
        
        Parameters
        ----------
        elapsed_ms:
            Operation duration in milliseconds.
        
        Example
        -------
        >>> metrics = ConfigMetrics()
        >>> await metrics.record_set(elapsed_ms=12.5)
        """
        async with self._lock:
            self.sets += 1
            self.total_set_time_ms += elapsed_ms

    async def record_fallback_to_default(self) -> None:
        """
        Record a fallback to default value.
        
        Called when configuration is not found in cache or database,
        and the default value is used instead.
        
        Example
        -------
        >>> metrics = ConfigMetrics()
        >>> await metrics.record_fallback_to_default()
        """
        async with self._lock:
            self.fallback_to_defaults += 1

    async def record_refresh(self) -> None:
        """
        Record a cache refresh operation.
        
        Called when the background refresh task successfully updates
        the configuration cache.
        
        Example
        -------
        >>> metrics = ConfigMetrics()
        >>> await metrics.record_refresh()
        """
        async with self._lock:
            self.refresh_count += 1

    async def record_error(self) -> None:
        """
        Record an error in configuration operations.
        
        Called when any configuration operation fails (read, write,
        validation, refresh, etc.).
        
        Example
        -------
        >>> metrics = ConfigMetrics()
        >>> await metrics.record_error()
        """
        async with self._lock:
            self.errors += 1

    async def get_cache_hit_rate(self) -> float:
        """
        Calculate cache hit rate as a percentage.
        
        Returns
        -------
        float
            Hit rate percentage (0.0 - 100.0).
        
        Example
        -------
        >>> metrics = ConfigMetrics()
        >>> hit_rate = await metrics.get_cache_hit_rate()
        >>> if hit_rate < 80.0:
        ...     logger.warning(f"Low config cache hit rate: {hit_rate:.1f}%")
        """
        async with self._lock:
            total_gets = self.gets
            if total_gets == 0:
                return 0.0
            return (self.cache_hits / total_gets) * 100.0

    async def get_avg_get_time_ms(self) -> float:
        """
        Calculate average GET operation latency in milliseconds.
        
        Returns
        -------
        float
            Average latency in milliseconds.
        
        Example
        -------
        >>> metrics = ConfigMetrics()
        >>> avg_latency = await metrics.get_avg_get_time_ms()
        >>> if avg_latency > 10.0:
        ...     logger.warning(f"High config GET latency: {avg_latency:.2f}ms")
        """
        async with self._lock:
            if self.gets == 0:
                return 0.0
            return self.total_get_time_ms / self.gets

    async def get_avg_set_time_ms(self) -> float:
        """
        Calculate average SET operation latency in milliseconds.
        
        Returns
        -------
        float
            Average latency in milliseconds.
        
        Example
        -------
        >>> metrics = ConfigMetrics()
        >>> avg_latency = await metrics.get_avg_set_time_ms()
        >>> if avg_latency > 100.0:
        ...     logger.warning(f"High config SET latency: {avg_latency:.2f}ms")
        """
        async with self._lock:
            if self.sets == 0:
                return 0.0
            return self.total_set_time_ms / self.sets

    async def get_stale_read_rate(self) -> float:
        """
        Calculate stale read rate as a percentage.
        
        Stale reads occur when cached values are older than the TTL
        but are still served (useful for monitoring cache freshness).
        
        Returns
        -------
        float
            Stale read rate percentage (0.0 - 100.0).
        
        Example
        -------
        >>> metrics = ConfigMetrics()
        >>> stale_rate = await metrics.get_stale_read_rate()
        >>> if stale_rate > 10.0:
        ...     logger.warning(f"High stale read rate: {stale_rate:.1f}%")
        """
        async with self._lock:
            if self.cache_hits == 0:
                return 0.0
            return (self.stale_reads / self.cache_hits) * 100.0

    async def reset(self) -> None:
        """
        Reset all metrics counters to zero.
        
        Useful for testing, periodic metrics rotation, or monitoring
        system resets. Thread-safe operation.
        
        Example
        -------
        >>> metrics = ConfigMetrics()
        >>> await metrics.reset()
        >>> logger.info("Config metrics reset for new monitoring cycle")
        """
        async with self._lock:
            self.gets = 0
            self.sets = 0
            self.cache_hits = 0
            self.cache_misses = 0
            self.fallback_to_defaults = 0
            self.refresh_count = 0
            self.errors = 0
            self.total_get_time_ms = 0.0
            self.total_set_time_ms = 0.0
            self.stale_reads = 0


async def get_metrics_snapshot(
    metrics: ConfigMetrics,
    initialized: bool,
    cached_configs: int,
    cache_ttl_seconds: int,
) -> Dict[str, Any]:
    """
    Generate a comprehensive metrics snapshot for monitoring.
    
    Includes both raw counters and derived metrics for complete
    observability into configuration system performance.
    
    Parameters
    ----------
    metrics:
        The ConfigMetrics instance to snapshot.
    initialized:
        Whether ConfigManager is initialized.
    cached_configs:
        Number of configurations currently cached.
    cache_ttl_seconds:
        Current cache TTL in seconds.
    
    Returns
    -------
    Dict[str, Any]
        Comprehensive metrics snapshot including:
        - All raw metrics counters
        - Derived metrics (hit rate, averages, stale rate)
        - System state (initialized, cache size, TTL)
    
    Example
    -------
    >>> snapshot = await get_metrics_snapshot(
    ...     metrics=config_metrics,
    ...     initialized=True,
    ...     cached_configs=50,
    ...     cache_ttl_seconds=300
    ... )
    >>> logger.info("Config metrics snapshot", extra=snapshot)
    """
    metrics_dict = metrics.to_dict()

    # Add derived metrics
    metrics_dict.update({
        "cache_hit_rate": round(await metrics.get_cache_hit_rate(), 2),
        "avg_get_time_ms": round(await metrics.get_avg_get_time_ms(), 2),
        "avg_set_time_ms": round(await metrics.get_avg_set_time_ms(), 2),
        "stale_read_rate": round(await metrics.get_stale_read_rate(), 2),
        "initialized": initialized,
        "cached_configs": cached_configs,
        "cache_ttl_seconds": cache_ttl_seconds,
    })

    return metrics_dict


def get_health_snapshot(
    initialized: bool,
    background_refresh_running: bool,
    cached_configs: int,
    errors: int,
    refresh_count: int,
    cache_ttl_seconds: int,
) -> Dict[str, Any]:
    """
    Generate a compact health snapshot for infrastructure dashboards.
    
    Provides key health indicators without full metrics detail,
    optimized for monitoring systems and alerting.
    
    Parameters
    ----------
    initialized:
        Whether ConfigManager is initialized.
    background_refresh_running:
        Whether background refresh task is running.
    cached_configs:
        Number of configurations currently cached.
    errors:
        Total error count since last reset.
    refresh_count:
        Total refresh count since last reset.
    cache_ttl_seconds:
        Current cache TTL in seconds.
    
    Returns
    -------
    Dict[str, Any]
        Compact health snapshot containing:
        - Initialization status
        - Background task status
        - Cache size
        - Error count
        - Refresh count
        - Current TTL
        - Overall health status
    
    Example
    -------
    >>> health = get_health_snapshot(
    ...     initialized=True,
    ...     background_refresh_running=True,
    ...     cached_configs=50,
    ...     errors=0,
    ...     refresh_count=100,
    ...     cache_ttl_seconds=300
    ... )
    >>> if not health["is_healthy"]:
    ...     send_alert("config_system_degraded", health)
    """
    # Determine overall health status
    is_healthy = (
        initialized
        and background_refresh_running
        and errors < 10  # Less than 10 errors is acceptable
        and cached_configs > 0  # Should have some configs cached
    )

    status = "healthy" if is_healthy else "degraded"
    if not initialized:
        status = "not_initialized"
    elif errors > 50:
        status = "unhealthy"

    return {
        "initialized": initialized,
        "background_refresh_running": background_refresh_running,
        "cached_configs": cached_configs,
        "errors": errors,
        "refresh_count": refresh_count,
        "cache_ttl_seconds": cache_ttl_seconds,
        "is_healthy": is_healthy,
        "status": status,
    }


# Export all public interfaces
__all__ = [
    "ConfigMetrics",
    "get_metrics_snapshot",
    "get_health_snapshot",
]