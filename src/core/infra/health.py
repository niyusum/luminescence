"""
Unified Health Check Service for Lumen (2025)

Purpose
-------
Provide a single, unified health check endpoint that aggregates health status
from all critical infrastructure components (Database, Redis) and returns a
comprehensive system health report.

This service is designed for:
- External monitoring tools (Prometheus, Datadog, etc.)
- Load balancer health checks
- Operations dashboards
- Automated alerting systems
- Pre-deployment validation

Responsibilities
----------------
- Aggregate health status from all infrastructure components
- Determine overall system health based on component states
- Provide detailed health reports with component breakdowns
- Support both quick checks and detailed diagnostics
- Return structured health data for monitoring integration
- Provide health check with configurable timeout

Non-Responsibilities
--------------------
- Health monitoring loops (handled by individual monitors)
- State tracking (handled by individual monitors)
- Metrics collection (handled by individual metrics modules)
- Alerting (handled by external systems)
- Circuit breaking (handled by circuit breaker modules)

LUMEN LAW Compliance
--------------------
- Article I: Stateless operations, queries current state
- Article X: Structured observability with detailed health reports
- Article IX: Graceful degradation (partial health reports on errors)
- Article II: Health check audit logging

Architecture Notes
------------------
**Health Status Hierarchy**:
- **HEALTHY**: All components operational
- **DEGRADED**: All components up but some performing poorly
- **UNHEALTHY**: One or more critical components down

**Component Priority**:
- Database: CRITICAL (system cannot function without it)
- Redis: CRITICAL (caching and rate limiting essential)

**Health Check Strategy**:
- Non-blocking concurrent health checks
- Timeout protection to prevent hanging
- Individual component errors don't crash health check
- Returns partial results if some components fail to respond

**Report Structure**:
- Overall status (HEALTHY/DEGRADED/UNHEALTHY)
- Timestamp
- Individual component statuses
- Component-specific metrics
- Error messages for failed checks

Configuration
-------------
- `HEALTH_CHECK_TIMEOUT_SECONDS`: Maximum time for health check (default: 5.0)

Usage Examples
--------------
Basic health check:

>>> from src.core.infra.health import UnifiedHealthCheck
>>>
>>> # Perform health check
>>> report = await UnifiedHealthCheck.check()
>>> print(report["status"])  # "HEALTHY" | "DEGRADED" | "UNHEALTHY"
>>>
>>> # Check specific components
>>> if report["components"]["database"]["status"] != "HEALTHY":
>>>     logger.error("Database unhealthy!")

Health check with custom timeout:

>>> # Quick health check with 2-second timeout
>>> report = await UnifiedHealthCheck.check(timeout_seconds=2.0)
>>> if report["status"] == "UNHEALTHY":
>>>     await shutdown_gracefully()

Integration with monitoring system:

>>> # In monitoring endpoint handler
>>> @app.get("/health")
>>> async def health_endpoint():
>>>     report = await UnifiedHealthCheck.check()
>>>     status_code = 200 if report["status"] == "HEALTHY" else 503
>>>     return JSONResponse(content=report, status_code=status_code)

Integration with bot lifecycle:

>>> # In BotLifecycle startup
>>> report = await UnifiedHealthCheck.check()
>>> if report["status"] == "UNHEALTHY":
>>>     raise RuntimeError("System unhealthy at startup")
>>> logger.info("All systems healthy", extra={"health_report": report})

Pre-deployment validation:

>>> # In deployment script
>>> import asyncio
>>> from src.core.infra.health import UnifiedHealthCheck
>>>
>>> async def validate_deployment():
>>>     report = await UnifiedHealthCheck.check(timeout_seconds=10.0)
>>>
>>>     if report["status"] != "HEALTHY":
>>>         print(f"Deployment validation failed: {report['status']}")
>>>         print(f"Details: {report['components']}")
>>>         sys.exit(1)
>>>
>>>     print("All systems healthy - deployment validated")
>>>
>>> asyncio.run(validate_deployment())

Health Report Structure
-----------------------
{
    "status": "HEALTHY" | "DEGRADED" | "UNHEALTHY",
    "timestamp": 1234567890.123,
    "components": {
        "database": {
            "status": "HEALTHY" | "DEGRADED" | "UNHEALTHY",
            "available": true,
            "consecutive_failures": 0,
            "consecutive_successes": 5,
            "is_healthy": true,
            "error": null
        },
        "redis": {
            "status": "HEALTHY" | "DEGRADED" | "UNHEALTHY",
            "available": true,
            "state": "HEALTHY",
            "is_running": true,
            "consecutive_failures": 0,
            "consecutive_successes": 10,
            "error_rate": 0.0,
            "avg_latency_ms": 12.34,
            "last_check_time": 1234567890.0,
            "error": null
        }
    },
    "errors": []
}

Error Handling
--------------
- Individual component check failures are caught and reported in the health report
- Timeout errors result in UNHEALTHY status for that component
- Health check never raises exceptions - always returns a report
- Partial health reports returned if some components fail to respond
"""

from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from src.core.logging.logger import get_logger
from src.core.config.config import Config

# Conditional imports to avoid circular dependencies
if TYPE_CHECKING:
    from src.core.database.health_monitor import DatabaseHealthMonitor
    from src.core.redis.health_monitor import RedisHealthMonitor

logger = get_logger(__name__)


class HealthStatus(Enum):
    """Overall system health status."""

    HEALTHY = "HEALTHY"       # All components operational
    DEGRADED = "DEGRADED"     # All up but some degraded
    UNHEALTHY = "UNHEALTHY"   # One or more components down


class UnifiedHealthCheck:
    """
    Unified health check service for all infrastructure components.

    This class provides static methods for checking overall system health
    by aggregating health status from all critical components.
    """

    # Class-level references to monitors (set by initialize())
    _database_monitor: Optional[DatabaseHealthMonitor] = None
    _redis_monitor: Optional[RedisHealthMonitor] = None

    @classmethod
    def initialize(
        cls,
        database_monitor: Optional[DatabaseHealthMonitor] = None,
        redis_monitor: Optional[RedisHealthMonitor] = None,
    ) -> None:
        """
        Initialize health check with monitor references.

        This should be called during bot startup after monitors are created.

        Parameters
        ----------
        database_monitor : DatabaseHealthMonitor, optional
            Reference to database health monitor
        redis_monitor : RedisHealthMonitor, optional
            Reference to Redis health monitor
        """
        cls._database_monitor = database_monitor
        cls._redis_monitor = redis_monitor

        logger.info(
            "UnifiedHealthCheck initialized",
            extra={
                "has_database_monitor": database_monitor is not None,
                "has_redis_monitor": redis_monitor is not None,
            },
        )

    @classmethod
    async def check(cls, timeout_seconds: Optional[float] = None) -> Dict[str, Any]:
        """
        Perform unified health check across all components.

        Parameters
        ----------
        timeout_seconds : float, optional
            Maximum time to wait for health check (default from config)

        Returns
        -------
        Dict[str, Any]
            Complete health report with overall status and component details
        """
        if timeout_seconds is None:
            timeout_seconds = float(getattr(Config, "HEALTH_CHECK_TIMEOUT_SECONDS", 5.0))

        start_time = time.time()

        logger.debug("Starting unified health check", extra={"timeout_seconds": timeout_seconds})

        # Run component checks concurrently
        try:
            db_status, redis_status = await asyncio.wait_for(
                asyncio.gather(
                    cls._check_database(),
                    cls._check_redis(),
                    return_exceptions=True,
                ),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Health check timed out",
                extra={"timeout_seconds": timeout_seconds},
            )
            return cls._build_timeout_report(timeout_seconds)

        # Handle exceptions from individual checks
        if isinstance(db_status, Exception):
            logger.error(
                "Database health check failed",
                extra={"error": str(db_status), "error_type": type(db_status).__name__},
                exc_info=db_status,
            )
            db_status = cls._build_error_component("database", db_status)

        if isinstance(redis_status, Exception):
            logger.error(
                "Redis health check failed",
                extra={"error": str(redis_status), "error_type": type(redis_status).__name__},
                exc_info=redis_status,
            )
            redis_status = cls._build_error_component("redis", redis_status)

        # Determine overall status
        overall_status = cls._determine_overall_status(db_status, redis_status)

        # Build report
        duration_ms = (time.time() - start_time) * 1000

        report = {
            "status": overall_status.value,
            "timestamp": time.time(),
            "duration_ms": round(duration_ms, 2),
            "components": {
                "database": db_status,
                "redis": redis_status,
            },
            "errors": cls._collect_errors(db_status, redis_status),
        }

        logger.info(
            "Health check completed",
            extra={
                "status": overall_status.value,
                "duration_ms": round(duration_ms, 2),
                "database_status": db_status.get("status"),
                "redis_status": redis_status.get("status"),
            },
        )

        return report

    # ═══════════════════════════════════════════════════════════════════════
    # COMPONENT CHECKS
    # ═══════════════════════════════════════════════════════════════════════

    @classmethod
    async def _check_database(cls) -> Dict[str, Any]:
        """Check database health."""
        if cls._database_monitor is None:
            logger.warning("Database health monitor not initialized")
            return {
                "status": "UNKNOWN",
                "available": False,
                "error": "Health monitor not initialized",
            }

        # DatabaseHealthMonitor doesn't have a get_status() method like Redis
        # We need to call the DatabaseService health check directly
        from src.core.database.service import DatabaseService

        try:
            is_healthy = await DatabaseService.health_check()

            # Get monitor state
            monitor_healthy = cls._database_monitor._is_healthy
            consecutive_failures = cls._database_monitor._consecutive_failures
            consecutive_successes = cls._database_monitor._consecutive_successes

            if is_healthy and monitor_healthy is not False:
                status = "HEALTHY"
            elif is_healthy and monitor_healthy is False:
                status = "DEGRADED"  # Recovering
            else:
                status = "UNHEALTHY"

            return {
                "status": status,
                "available": is_healthy,
                "consecutive_failures": consecutive_failures,
                "consecutive_successes": consecutive_successes,
                "is_healthy": is_healthy,
                "monitor_state": monitor_healthy,
                "error": None,
            }

        except Exception as exc:
            logger.error(
                "Database health check failed",
                extra={"error": str(exc), "error_type": type(exc).__name__},
                exc_info=True,
            )
            return {
                "status": "UNHEALTHY",
                "available": False,
                "error": f"{type(exc).__name__}: {str(exc)}",
            }

    @classmethod
    async def _check_redis(cls) -> Dict[str, Any]:
        """Check Redis health."""
        if cls._redis_monitor is None:
            logger.warning("Redis health monitor not initialized")
            return {
                "status": "UNKNOWN",
                "available": False,
                "error": "Health monitor not initialized",
            }

        try:
            # Get status from Redis health monitor
            status_dict = cls._redis_monitor.get_status()

            # Map state to status
            state = status_dict.get("state", "UNKNOWN")

            return {
                "status": state,
                "available": status_dict.get("state") != "UNHEALTHY",
                "state": state,
                "is_running": status_dict.get("is_running", False),
                "consecutive_failures": status_dict.get("consecutive_failures", 0),
                "consecutive_successes": status_dict.get("consecutive_successes", 0),
                "error_rate": status_dict.get("error_rate", 0.0),
                "avg_latency_ms": status_dict.get("avg_latency_ms", 0.0),
                "last_check_time": status_dict.get("last_check_time"),
                "error": None,
            }

        except Exception as exc:
            logger.error(
                "Redis health check failed",
                extra={"error": str(exc), "error_type": type(exc).__name__},
                exc_info=True,
            )
            return {
                "status": "UNHEALTHY",
                "available": False,
                "error": f"{type(exc).__name__}: {str(exc)}",
            }

    # ═══════════════════════════════════════════════════════════════════════
    # STATUS AGGREGATION
    # ═══════════════════════════════════════════════════════════════════════

    @classmethod
    def _determine_overall_status(
        cls,
        db_status: Dict[str, Any],
        redis_status: Dict[str, Any],
    ) -> HealthStatus:
        """
        Determine overall system health from component statuses.

        Logic:
        - UNHEALTHY: Any critical component is UNHEALTHY or UNKNOWN
        - DEGRADED: All components up but at least one is DEGRADED
        - HEALTHY: All components are HEALTHY
        """
        db_state = db_status.get("status", "UNKNOWN")
        redis_state = redis_status.get("status", "UNKNOWN")

        # If any component is unhealthy or unknown, system is unhealthy
        if db_state in ("UNHEALTHY", "UNKNOWN") or redis_state in ("UNHEALTHY", "UNKNOWN"):
            return HealthStatus.UNHEALTHY

        # If any component is degraded, system is degraded
        if db_state == "DEGRADED" or redis_state == "DEGRADED":
            return HealthStatus.DEGRADED

        # All components healthy
        return HealthStatus.HEALTHY

    @classmethod
    def _collect_errors(cls, *component_statuses: Dict[str, Any]) -> List[str]:
        """Collect all error messages from component statuses."""
        errors = []
        for status in component_statuses:
            if status.get("error"):
                errors.append(status["error"])
        return errors

    # ═══════════════════════════════════════════════════════════════════════
    # ERROR HANDLING
    # ═══════════════════════════════════════════════════════════════════════

    @classmethod
    def _build_error_component(cls, component_name: str, error: Exception) -> Dict[str, Any]:
        """Build error status for a component."""
        return {
            "status": "UNHEALTHY",
            "available": False,
            "error": f"{type(error).__name__}: {str(error)}",
        }

    @classmethod
    def _build_timeout_report(cls, timeout_seconds: float) -> Dict[str, Any]:
        """Build health report for timeout case."""
        return {
            "status": "UNHEALTHY",
            "timestamp": time.time(),
            "duration_ms": timeout_seconds * 1000,
            "components": {
                "database": {
                    "status": "UNKNOWN",
                    "available": False,
                    "error": f"Health check timed out after {timeout_seconds}s",
                },
                "redis": {
                    "status": "UNKNOWN",
                    "available": False,
                    "error": f"Health check timed out after {timeout_seconds}s",
                },
            },
            "errors": [f"Health check timed out after {timeout_seconds}s"],
        }
