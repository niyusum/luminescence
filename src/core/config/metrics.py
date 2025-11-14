"""
Configuration metrics and health monitoring for Lumen (2025).

Purpose
-------
- Track performance metrics for configuration reads and writes.
- Monitor cache hit rates, stale reads, and error counts.
- Provide health snapshots for infra dashboards and observability.

Responsibilities
----------------
- Define `ConfigMetrics` dataclass for metrics tracking.
- Calculate derived metrics (cache hit rate, average latencies).
- Generate health snapshots for monitoring systems.
- Support metrics reset for testing and maintenance.

Non-Responsibilities
--------------------
- Configuration storage or retrieval (handled by ConfigManager).
- Configuration validation (handled by validator module).
- Transaction management (handled by DatabaseService).

Lumen 2025 Compliance
---------------------
- **Observability**: Comprehensive metrics tracking for all config operations.
- **Type safety**: Strongly-typed metrics using dataclasses.
- **Separation of concerns**: Pure metrics logic; no config management.
- **Testability**: Metrics can be reset and inspected independently.

Architecture Notes
------------------
- Metrics are tracked in-memory; not persisted to database.
- Derived metrics (hit rate, averages) calculated on-demand.
- Health snapshots designed for external monitoring systems.

Dependencies
------------
- Standard library only (dataclasses).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict


# ============================================================================
# Metrics Dataclass
# ============================================================================


@dataclass(slots=True)
class ConfigMetrics:
    """Typed metrics container for ConfigManager observability."""

    gets: int = 0
    sets: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    fallback_to_defaults: int = 0
    refresh_count: int = 0
    errors: int = 0
    total_get_time_ms: float = 0.0
    total_set_time_ms: float = 0.0
    stale_reads: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary for logging/export."""
        return asdict(self)

    def get_cache_hit_rate(self) -> float:
        """
        Calculate cache hit rate as a percentage.

        Returns
        -------
        float
            Hit rate percentage (0.0 - 100.0).
        """
        total_gets = self.gets
        if total_gets == 0:
            return 0.0
        return (self.cache_hits / total_gets) * 100.0

    def get_avg_get_time_ms(self) -> float:
        """
        Calculate average GET operation latency.

        Returns
        -------
        float
            Average latency in milliseconds.
        """
        if self.gets == 0:
            return 0.0
        return self.total_get_time_ms / self.gets

    def get_avg_set_time_ms(self) -> float:
        """
        Calculate average SET operation latency.

        Returns
        -------
        float
            Average latency in milliseconds.
        """
        if self.sets == 0:
            return 0.0
        return self.total_set_time_ms / self.sets

    def reset(self) -> None:
        """Reset all metrics counters to zero."""
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


# ============================================================================
# Metrics Helper Functions
# ============================================================================


def get_metrics_snapshot(
    metrics: ConfigMetrics,
    initialized: bool,
    cached_configs: int,
    cache_ttl_seconds: int,
) -> Dict[str, Any]:
    """
    Generate a comprehensive metrics snapshot.

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
        Comprehensive metrics snapshot including derived metrics.
    """
    metrics_dict = metrics.to_dict()

    metrics_dict.update(
        {
            "cache_hit_rate": round(metrics.get_cache_hit_rate(), 2),
            "avg_get_time_ms": round(metrics.get_avg_get_time_ms(), 2),
            "avg_set_time_ms": round(metrics.get_avg_set_time_ms(), 2),
            "initialized": initialized,
            "cached_configs": cached_configs,
            "cache_ttl_seconds": cache_ttl_seconds,
        }
    )
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
    Generate a compact health snapshot for infra dashboards.

    Parameters
    ----------
    initialized:
        Whether ConfigManager is initialized.
    background_refresh_running:
        Whether background refresh task is running.
    cached_configs:
        Number of configurations currently cached.
    errors:
        Total error count.
    refresh_count:
        Total refresh count.
    cache_ttl_seconds:
        Current cache TTL in seconds.

    Returns
    -------
    Dict[str, Any]
        Compact health snapshot suitable for monitoring systems.
    """
    return {
        "initialized": initialized,
        "background_refresh_running": background_refresh_running,
        "cached_configs": cached_configs,
        "errors": errors,
        "refresh_count": refresh_count,
        "cache_ttl_seconds": cache_ttl_seconds,
    }
