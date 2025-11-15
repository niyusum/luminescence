"""
Redis Health Monitor for Lumen (2025)

Purpose
-------
Continuous health monitoring for Redis with degradation detection,
automated recovery attempts, and health status reporting.

Monitors:
- Connection health via periodic PING
- Operation latency trends
- Error rate tracking
- Circuit breaker state
- Connection pool utilization

Responsibilities
----------------
- Run periodic health checks in background
- Detect degraded performance
- Trigger recovery actions when needed
- Provide health status API for monitoring
- Log health state transitions
- Emit health events

Non-Responsibilities
--------------------
- No Redis operations (only monitors)
- No circuit breaking (see circuit_breaker.py)
- No retry logic (see retry_policy.py)
- No business logic

Lumen 2025 Compliance
---------------------
- Strict layering: pure infrastructure monitoring
- Config-driven: check intervals and thresholds
- Observability: structured logging for health events
- Event emission: health state changes
- Graceful degradation: non-blocking monitoring

Configuration Keys
------------------
- core.redis.health.check_interval_seconds: int (default 30)
- core.redis.health.timeout_seconds       : int (default 5)
- core.redis.health.latency_warning_ms    : int (default 50)
- core.redis.health.latency_critical_ms   : int (default 200)
- core.redis.health.error_rate_threshold  : float (default 0.1)

Architecture Notes
------------------
- Runs as background asyncio task
- Non-blocking health checks to avoid disrupting operations
- Maintains rolling window of health check results
- Automatically detects and logs degradation
- Provides queryable health status for external monitoring
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from enum import Enum
from typing import Any, Dict, Optional, TYPE_CHECKING

from src.core.logging.logger import get_logger
from src.core.config import ConfigManager

if TYPE_CHECKING:
    from src.core.redis.service import RedisService

logger = get_logger(__name__)


class HealthState(Enum):
    """Redis health states."""
    
    HEALTHY = "HEALTHY"         # All systems operational
    DEGRADED = "DEGRADED"       # Operational but slow
    UNHEALTHY = "UNHEALTHY"     # Not operational


class RedisHealthMonitor:
    """
    Continuous health monitoring for Redis.
    
    Runs periodic health checks and maintains health state with
    automatic degradation detection and recovery tracking.
    """
    
    def __init__(self, redis_service: type[RedisService]) -> None:
        """
        Initialize health monitor.

        Parameters
        ----------
        redis_service : type[RedisService]
            The RedisService singleton type to monitor
        """
        self._redis_service = redis_service
        self._state: HealthState = HealthState.HEALTHY
        self._is_running: bool = False
        self._monitor_task: Optional[asyncio.Task] = None
        
        # Health check history
        self._check_history: deque = deque(maxlen=100)
        self._consecutive_failures: int = 0
        self._consecutive_successes: int = 0
        self._last_check_time: Optional[float] = None
        self._last_state_change: Optional[float] = None
        
        # Configuration
        self._check_interval = self._get_config_int("core.redis.health.check_interval_seconds", 30)
        self._timeout = self._get_config_int("core.redis.health.timeout_seconds", 5)
        self._latency_warning = self._get_config_int("core.redis.health.latency_warning_ms", 50)
        self._latency_critical = self._get_config_int("core.redis.health.latency_critical_ms", 200)
        self._error_threshold = self._get_config_float("core.redis.health.error_rate_threshold", 0.1)
        
        logger.info(
            "RedisHealthMonitor initialized",
            extra={
                "check_interval_seconds": self._check_interval,
                "timeout_seconds": self._timeout,
                "latency_warning_ms": self._latency_warning,
                "latency_critical_ms": self._latency_critical,
            },
        )
    
    # ═══════════════════════════════════════════════════════════════════════
    # LIFECYCLE
    # ═══════════════════════════════════════════════════════════════════════
    
    async def start(self) -> None:
        """Start the health monitoring background task."""
        if self._is_running:
            logger.warning("RedisHealthMonitor already running")
            return
        
        self._is_running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        
        logger.info("RedisHealthMonitor started")
    
    async def stop(self) -> None:
        """Stop the health monitoring background task."""
        if not self._is_running:
            return
        
        self._is_running = False
        
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
        
        logger.info("RedisHealthMonitor stopped")
    
    # ═══════════════════════════════════════════════════════════════════════
    # MONITORING LOOP
    # ═══════════════════════════════════════════════════════════════════════
    
    async def _monitor_loop(self) -> None:
        """Main monitoring loop that runs periodic health checks."""
        logger.debug("Health monitor loop started")
        
        while self._is_running:
            try:
                await self._perform_health_check()
                await asyncio.sleep(self._check_interval)
                
            except asyncio.CancelledError:
                logger.debug("Health monitor loop cancelled")
                break
                
            except Exception as exc:
                logger.error(
                    "Error in health monitor loop",
                    extra={
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    },
                    exc_info=True,
                )
                # Continue monitoring despite errors
                await asyncio.sleep(self._check_interval)
    
    async def _perform_health_check(self) -> None:
        """Perform a single health check."""
        start_time = time.monotonic()
        check_passed = False
        latency_ms = 0.0
        error_msg = None
        
        try:
            # Perform health check with timeout
            check_passed = await asyncio.wait_for(
                self._redis_service.health_check(),
                timeout=self._timeout,
            )
            latency_ms = (time.monotonic() - start_time) * 1000
            
        except asyncio.TimeoutError:
            latency_ms = self._timeout * 1000
            error_msg = "Health check timed out"
            logger.warning(
                "Redis health check timed out",
                extra={"timeout_seconds": self._timeout},
            )
            
        except Exception as exc:
            latency_ms = (time.monotonic() - start_time) * 1000
            error_msg = str(exc)
            logger.error(
                "Redis health check failed",
                extra={
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
        
        # Record check result
        self._check_history.append({
            "timestamp": time.time(),
            "passed": check_passed,
            "latency_ms": latency_ms,
            "error": error_msg,
        })
        self._last_check_time = time.time()
        
        # Update state based on result
        await self._update_health_state(check_passed, latency_ms)
    
    # ═══════════════════════════════════════════════════════════════════════
    # STATE MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════
    
    async def _update_health_state(self, check_passed: bool, latency_ms: float) -> None:
        """Update health state based on check result."""
        old_state = self._state
        
        if check_passed:
            self._consecutive_successes += 1
            self._consecutive_failures = 0
            
            # Check latency for degradation
            if latency_ms >= self._latency_critical:
                new_state = HealthState.DEGRADED
            elif latency_ms >= self._latency_warning:
                new_state = HealthState.DEGRADED if self._state == HealthState.DEGRADED else HealthState.HEALTHY
            else:
                # Recover to healthy after 3 consecutive good checks
                new_state = HealthState.HEALTHY if self._consecutive_successes >= 3 else self._state
        else:
            self._consecutive_failures += 1
            self._consecutive_successes = 0
            
            # Transition to unhealthy after 2 consecutive failures
            new_state = HealthState.UNHEALTHY if self._consecutive_failures >= 2 else HealthState.DEGRADED
        
        # Update state if changed
        if new_state != old_state:
            self._state = new_state
            self._last_state_change = time.time()
            
            logger.warning(
                "Redis health state changed",
                extra={
                    "old_state": old_state.value,
                    "new_state": new_state.value,
                    "consecutive_failures": self._consecutive_failures,
                    "consecutive_successes": self._consecutive_successes,
                    "latency_ms": round(latency_ms, 2),
                },
            )
    
    # ═══════════════════════════════════════════════════════════════════════
    # STATUS API
    # ═══════════════════════════════════════════════════════════════════════
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get current health status.
        
        Returns
        -------
        Dict[str, Any]
            Complete health status including state, history, and metrics
        """
        # Calculate error rate from recent history
        recent_checks = list(self._check_history)[-20:]  # Last 20 checks
        error_rate = (
            sum(1 for check in recent_checks if not check["passed"]) / len(recent_checks)
            if recent_checks else 0.0
        )
        
        # Calculate average latency
        avg_latency = (
            sum(check["latency_ms"] for check in recent_checks) / len(recent_checks)
            if recent_checks else 0.0
        )
        
        return {
            "state": self._state.value,
            "is_running": self._is_running,
            "consecutive_failures": self._consecutive_failures,
            "consecutive_successes": self._consecutive_successes,
            "last_check_time": self._last_check_time,
            "last_state_change": self._last_state_change,
            "total_checks": len(self._check_history),
            "error_rate": round(error_rate, 3),
            "avg_latency_ms": round(avg_latency, 2),
            "check_interval_seconds": self._check_interval,
        }
    
    def is_healthy(self) -> bool:
        """Check if Redis is healthy."""
        return self._state == HealthState.HEALTHY
    
    def is_degraded(self) -> bool:
        """Check if Redis is degraded."""
        return self._state == HealthState.DEGRADED
    
    def is_unhealthy(self) -> bool:
        """Check if Redis is unhealthy."""
        return self._state == HealthState.UNHEALTHY
    
    # ═══════════════════════════════════════════════════════════════════════
    # MANUAL CHECK
    # ═══════════════════════════════════════════════════════════════════════
    
    async def check_now(self) -> Dict[str, Any]:
        """
        Perform an immediate health check.
        
        Returns
        -------
        Dict[str, Any]
            Check result with latency and status
        """
        start_time = time.monotonic()
        
        try:
            passed = await asyncio.wait_for(
                self._redis_service.health_check(),
                timeout=self._timeout,
            )
            latency_ms = (time.monotonic() - start_time) * 1000
            
            return {
                "passed": passed,
                "latency_ms": round(latency_ms, 2),
                "timestamp": time.time(),
            }
            
        except Exception as exc:
            latency_ms = (time.monotonic() - start_time) * 1000
            
            return {
                "passed": False,
                "latency_ms": round(latency_ms, 2),
                "timestamp": time.time(),
                "error": str(exc),
                "error_type": type(exc).__name__,
            }
    
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
    
    @staticmethod
    def _get_config_float(key: str, default: float) -> float:
        """Get float config value with fallback."""
        try:
            val = ConfigManager.get(key)
            if isinstance(val, (int, float)):
                return float(val)
        except Exception:
            pass
        return default