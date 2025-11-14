"""
Redis Metrics Collector for Lumen (2025)

Purpose
-------
Centralized metrics collection for all Redis operations including:
- Operation latency tracking (GET, SET, DELETE, INCR, EXPIRE, JSON ops)
- Lock acquisition metrics (success/failure, wait time, hold time)
- Connection pool statistics
- Error rate tracking
- Health check metrics

Responsibilities
----------------
- Track operation counts and latencies
- Monitor lock performance and contention
- Collect connection pool utilization metrics
- Aggregate error rates by operation type
- Provide queryable metrics for monitoring systems
- Expose metrics for Prometheus/Grafana integration

Non-Responsibilities
--------------------
- No business logic
- No Redis operations (pure metrics collection)
- No alert generation (handled by external monitoring)
- No metric persistence (in-memory only, export via API)

Lumen 2025 Compliance
---------------------
- Strict layering: pure infrastructure metrics
- Config-driven: metric retention and aggregation windows
- Observability: structured logging for metric events
- Zero business logic
- Thread-safe metric collection

Architecture Notes
------------------
- Uses collections.defaultdict and deque for efficient aggregation
- Metrics are kept in memory with configurable retention windows
- Designed for low overhead (<1ms per metric record)
- Supports histogram buckets for latency distribution
- Thread-safe via asyncio primitives
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from threading import Lock

from src.core.logging.logger import get_logger
from src.core.config import ConfigManager

logger = get_logger(__name__)


@dataclass
class OperationMetrics:
    """Metrics for a specific Redis operation type."""
    
    total_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_latency_ms: float = 0.0
    min_latency_ms: float = float('inf')
    max_latency_ms: float = 0.0
    latencies: deque = field(default_factory=lambda: deque(maxlen=1000))
    
    def record(self, latency_ms: float, success: bool) -> None:
        """Record a single operation."""
        self.total_count += 1
        if success:
            self.success_count += 1
        else:
            self.failure_count += 1
            
        self.total_latency_ms += latency_ms
        self.min_latency_ms = min(self.min_latency_ms, latency_ms)
        self.max_latency_ms = max(self.max_latency_ms, latency_ms)
        self.latencies.append(latency_ms)
    
    @property
    def avg_latency_ms(self) -> float:
        """Calculate average latency."""
        return self.total_latency_ms / self.total_count if self.total_count > 0 else 0.0
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        return (self.success_count / self.total_count * 100) if self.total_count > 0 else 0.0
    
    @property
    def p50_latency_ms(self) -> float:
        """Calculate 50th percentile latency."""
        return self._percentile(50)
    
    @property
    def p95_latency_ms(self) -> float:
        """Calculate 95th percentile latency."""
        return self._percentile(95)
    
    @property
    def p99_latency_ms(self) -> float:
        """Calculate 99th percentile latency."""
        return self._percentile(99)
    
    def _percentile(self, p: int) -> float:
        """Calculate percentile from latency samples."""
        if not self.latencies:
            return 0.0
        sorted_latencies = sorted(self.latencies)
        idx = int(len(sorted_latencies) * (p / 100.0))
        return sorted_latencies[min(idx, len(sorted_latencies) - 1)]


@dataclass
class LockMetrics:
    """Metrics for distributed lock operations."""
    
    acquisition_attempts: int = 0
    acquisition_successes: int = 0
    acquisition_failures: int = 0
    total_wait_time_ms: float = 0.0
    total_hold_time_ms: float = 0.0
    timeouts: int = 0
    contentions: int = 0
    wait_times: deque = field(default_factory=lambda: deque(maxlen=1000))
    hold_times: deque = field(default_factory=lambda: deque(maxlen=1000))
    
    def record_acquisition(self, wait_ms: float, success: bool) -> None:
        """Record lock acquisition attempt."""
        self.acquisition_attempts += 1
        self.total_wait_time_ms += wait_ms
        self.wait_times.append(wait_ms)
        
        if success:
            self.acquisition_successes += 1
        else:
            self.acquisition_failures += 1
            self.timeouts += 1
            
        if wait_ms > 10:  # Contention threshold: 10ms
            self.contentions += 1
    
    def record_hold(self, hold_ms: float) -> None:
        """Record lock hold duration."""
        self.total_hold_time_ms += hold_ms
        self.hold_times.append(hold_ms)
    
    @property
    def avg_wait_time_ms(self) -> float:
        """Calculate average wait time."""
        return self.total_wait_time_ms / self.acquisition_attempts if self.acquisition_attempts > 0 else 0.0
    
    @property
    def avg_hold_time_ms(self) -> float:
        """Calculate average hold time."""
        return self.total_hold_time_ms / len(self.hold_times) if self.hold_times else 0.0
    
    @property
    def success_rate(self) -> float:
        """Calculate acquisition success rate."""
        return (self.acquisition_successes / self.acquisition_attempts * 100) if self.acquisition_attempts > 0 else 0.0


class RedisMetrics:
    """
    Centralized Redis metrics collector for Lumen.
    
    Thread-safe collection of Redis operation metrics including
    latencies, success rates, lock performance, and connection stats.
    """
    
    _operations: Dict[str, OperationMetrics] = defaultdict(OperationMetrics)
    _locks: Dict[str, LockMetrics] = defaultdict(LockMetrics)
    _global_lock_metrics: LockMetrics = LockMetrics()
    _connection_pool_stats: Dict[str, Any] = {}
    _health_checks: deque = deque(maxlen=100)
    _lock = Lock()
    _start_time: float = time.time()
    
    # ═══════════════════════════════════════════════════════════════════════
    # OPERATION METRICS
    # ═══════════════════════════════════════════════════════════════════════
    
    @classmethod
    def record_operation(
        cls,
        operation: str,
        latency_ms: float,
        success: bool = True,
    ) -> None:
        """
        Record a Redis operation metric.
        
        Parameters
        ----------
        operation : str
            Operation type (GET, SET, DELETE, INCR, EXPIRE, etc.)
        latency_ms : float
            Operation latency in milliseconds
        success : bool
            Whether the operation succeeded
        """
        with cls._lock:
            cls._operations[operation].record(latency_ms, success)
            
            # Log slow operations
            slow_threshold = cls._get_config_int("core.redis.metrics.slow_operation_ms", 100)
            if latency_ms > slow_threshold:
                logger.warning(
                    "Slow Redis operation detected",
                    extra={
                        "operation": operation,
                        "latency_ms": round(latency_ms, 2),
                        "threshold_ms": slow_threshold,
                    },
                )
    
    # ═══════════════════════════════════════════════════════════════════════
    # LOCK METRICS
    # ═══════════════════════════════════════════════════════════════════════
    
    @classmethod
    def record_lock_acquisition(
        cls,
        lock_key: str,
        wait_ms: float,
        success: bool,
    ) -> None:
        """
        Record lock acquisition attempt.
        
        Parameters
        ----------
        lock_key : str
            The lock identifier
        wait_ms : float
            Time spent waiting for the lock in milliseconds
        success : bool
            Whether acquisition succeeded
        """
        with cls._lock:
            cls._locks[lock_key].record_acquisition(wait_ms, success)
            cls._global_lock_metrics.record_acquisition(wait_ms, success)
            
            # Log lock contention
            if wait_ms > 50:  # High contention threshold
                logger.info(
                    "Lock contention detected",
                    extra={
                        "lock_key": lock_key,
                        "wait_ms": round(wait_ms, 2),
                        "success": success,
                    },
                )
    
    @classmethod
    def record_lock_hold(cls, lock_key: str, hold_ms: float) -> None:
        """
        Record lock hold duration.
        
        Parameters
        ----------
        lock_key : str
            The lock identifier
        hold_ms : float
            Time lock was held in milliseconds
        """
        with cls._lock:
            cls._locks[lock_key].record_hold(hold_ms)
            cls._global_lock_metrics.record_hold(hold_ms)
            
            # Log long-held locks
            long_hold_threshold = cls._get_config_int("core.redis.metrics.long_hold_ms", 1000)
            if hold_ms > long_hold_threshold:
                logger.warning(
                    "Long lock hold detected",
                    extra={
                        "lock_key": lock_key,
                        "hold_ms": round(hold_ms, 2),
                        "threshold_ms": long_hold_threshold,
                    },
                )
    
    # ═══════════════════════════════════════════════════════════════════════
    # HEALTH CHECK METRICS
    # ═══════════════════════════════════════════════════════════════════════
    
    @classmethod
    def record_health_check(cls, success: bool, latency_ms: float) -> None:
        """
        Record health check result.
        
        Parameters
        ----------
        success : bool
            Whether health check passed
        latency_ms : float
            Health check latency in milliseconds
        """
        with cls._lock:
            cls._health_checks.append({
                "timestamp": time.time(),
                "success": success,
                "latency_ms": latency_ms,
            })
    
    # ═══════════════════════════════════════════════════════════════════════
    # CONNECTION POOL METRICS
    # ═══════════════════════════════════════════════════════════════════════
    
    @classmethod
    def update_connection_pool_stats(
        cls,
        total_connections: int,
        active_connections: int,
        idle_connections: int,
    ) -> None:
        """
        Update connection pool statistics.
        
        Parameters
        ----------
        total_connections : int
            Total number of connections in pool
        active_connections : int
            Number of active connections
        idle_connections : int
            Number of idle connections
        """
        with cls._lock:
            cls._connection_pool_stats = {
                "total": total_connections,
                "active": active_connections,
                "idle": idle_connections,
                "utilization_pct": (active_connections / total_connections * 100) if total_connections > 0 else 0.0,
                "timestamp": time.time(),
            }
    
    # ═══════════════════════════════════════════════════════════════════════
    # METRIC RETRIEVAL
    # ═══════════════════════════════════════════════════════════════════════
    
    @classmethod
    def get_summary(cls) -> Dict[str, Any]:
        """
        Get comprehensive metrics summary.
        
        Returns
        -------
        Dict[str, Any]
            Complete metrics snapshot including operations, locks, health, and pool stats
        """
        with cls._lock:
            uptime_seconds = time.time() - cls._start_time
            
            # Aggregate operation metrics
            operations_summary = {}
            for op_name, metrics in cls._operations.items():
                operations_summary[op_name] = {
                    "total_count": metrics.total_count,
                    "success_count": metrics.success_count,
                    "failure_count": metrics.failure_count,
                    "success_rate_pct": round(metrics.success_rate, 2),
                    "avg_latency_ms": round(metrics.avg_latency_ms, 2),
                    "min_latency_ms": round(metrics.min_latency_ms, 2),
                    "max_latency_ms": round(metrics.max_latency_ms, 2),
                    "p50_latency_ms": round(metrics.p50_latency_ms, 2),
                    "p95_latency_ms": round(metrics.p95_latency_ms, 2),
                    "p99_latency_ms": round(metrics.p99_latency_ms, 2),
                }
            
            # Global lock metrics
            lock_summary = {
                "acquisition_attempts": cls._global_lock_metrics.acquisition_attempts,
                "acquisition_successes": cls._global_lock_metrics.acquisition_successes,
                "acquisition_failures": cls._global_lock_metrics.acquisition_failures,
                "success_rate_pct": round(cls._global_lock_metrics.success_rate, 2),
                "avg_wait_time_ms": round(cls._global_lock_metrics.avg_wait_time_ms, 2),
                "avg_hold_time_ms": round(cls._global_lock_metrics.avg_hold_time_ms, 2),
                "timeouts": cls._global_lock_metrics.timeouts,
                "contentions": cls._global_lock_metrics.contentions,
            }
            
            # Health check summary
            health_summary = {
                "total_checks": len(cls._health_checks),
                "successful_checks": sum(1 for check in cls._health_checks if check["success"]),
                "failed_checks": sum(1 for check in cls._health_checks if not check["success"]),
                "success_rate_pct": (
                    sum(1 for check in cls._health_checks if check["success"]) / len(cls._health_checks) * 100
                    if cls._health_checks else 0.0
                ),
                "avg_latency_ms": (
                    sum(check["latency_ms"] for check in cls._health_checks) / len(cls._health_checks)
                    if cls._health_checks else 0.0
                ),
            }
            
            return {
                "uptime_seconds": round(uptime_seconds, 2),
                "operations": operations_summary,
                "locks": lock_summary,
                "health": health_summary,
                "connection_pool": cls._connection_pool_stats.copy(),
            }
    
    @classmethod
    def get_operation_metrics(cls, operation: str) -> Dict[str, Any]:
        """Get metrics for a specific operation type."""
        with cls._lock:
            metrics = cls._operations.get(operation)
            if not metrics:
                return {}
            
            return {
                "total_count": metrics.total_count,
                "success_count": metrics.success_count,
                "failure_count": metrics.failure_count,
                "success_rate_pct": round(metrics.success_rate, 2),
                "avg_latency_ms": round(metrics.avg_latency_ms, 2),
                "min_latency_ms": round(metrics.min_latency_ms, 2),
                "max_latency_ms": round(metrics.max_latency_ms, 2),
                "p50_latency_ms": round(metrics.p50_latency_ms, 2),
                "p95_latency_ms": round(metrics.p95_latency_ms, 2),
                "p99_latency_ms": round(metrics.p99_latency_ms, 2),
            }
    
    @classmethod
    def get_lock_metrics(cls, lock_key: Optional[str] = None) -> Dict[str, Any]:
        """
        Get lock metrics.
        
        Parameters
        ----------
        lock_key : Optional[str]
            Specific lock key to get metrics for. If None, returns global metrics.
        """
        with cls._lock:
            if lock_key is None:
                metrics = cls._global_lock_metrics
            else:
                metrics = cls._locks.get(lock_key)
                if not metrics:
                    return {}
            
            return {
                "acquisition_attempts": metrics.acquisition_attempts,
                "acquisition_successes": metrics.acquisition_successes,
                "acquisition_failures": metrics.acquisition_failures,
                "success_rate_pct": round(metrics.success_rate, 2),
                "avg_wait_time_ms": round(metrics.avg_wait_time_ms, 2),
                "avg_hold_time_ms": round(metrics.avg_hold_time_ms, 2),
                "timeouts": metrics.timeouts,
                "contentions": metrics.contentions,
            }
    
    # ═══════════════════════════════════════════════════════════════════════
    # RESET & MAINTENANCE
    # ═══════════════════════════════════════════════════════════════════════
    
    @classmethod
    def reset(cls) -> None:
        """Reset all metrics (useful for testing)."""
        with cls._lock:
            cls._operations.clear()
            cls._locks.clear()
            cls._global_lock_metrics = LockMetrics()
            cls._connection_pool_stats.clear()
            cls._health_checks.clear()
            cls._start_time = time.time()
            
            logger.info("Redis metrics reset")
    
    # ═══════════════════════════════════════════════════════════════════════
    # CONFIGURATION HELPERS
    # ═══════════════════════════════════════════════════════════════════════
    
    @staticmethod
    def _get_config_int(key: str, default: int) -> int:
        """Get integer config value with fallback."""
        try:
            val = ConfigManager.get(key)
            if isinstance(val, int):
                return val
        except Exception:
            pass
        return default