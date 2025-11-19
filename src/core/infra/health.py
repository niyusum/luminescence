"""
Unified Health Check Service for Lumen RPG (2025).

Purpose
-------
Provides a single, unified health check endpoint that aggregates health status
from all critical infrastructure components (Database, Redis, Cache, etc.) and
returns a comprehensive system health report.

This service is designed for:
- External monitoring tools (Prometheus, Datadog, etc.)
- Load balancer health checks
- Operations dashboards
- Automated alerting systems
- Pre-deployment validation
- Bot lifecycle management

Responsibilities
----------------
- Aggregate health status from all infrastructure components
- Determine overall system health based on component states
- Provide detailed health reports with component breakdowns
- Support both quick checks and detailed diagnostics
- Return structured health data for monitoring integration
- Provide health checks with configurable timeouts
- Handle partial failures gracefully

Non-Responsibilities
--------------------
- Health monitoring loops (handled by individual component monitors)
- State tracking (handled by individual monitors)
- Metrics collection (handled by individual metrics modules)
- Alerting (handled by external systems)
- Circuit breaking (handled by circuit breaker modules)

Architecture Compliance
-----------------------
Lumen 2025 Engineering Standard compliance:
- **Separation of Responsibilities**: Pure infrastructure aggregation
- **Observability First**: Detailed health reports with structured logging
- **Error Isolation**: Individual component failures don't crash health checks
- **Graceful Degradation**: Returns partial results on timeout or error
- **Config-Driven**: Timeout and component selection from ConfigManager
- **Stateless**: Queries current state, maintains no state

Health Status Hierarchy
-----------------------
- **HEALTHY**: All components operational and responsive
- **DEGRADED**: All components up but some performing poorly
- **UNHEALTHY**: One or more critical components down or unresponsive

Component Priority
------------------
All monitored components are considered CRITICAL:
- Database: Essential for all game state
- Redis: Required for caching and rate limiting

Health Check Strategy
---------------------
- Non-blocking concurrent health checks
- Timeout protection to prevent hanging
- Individual component errors don't crash health check
- Returns partial results if some components fail to respond
- Structured error reporting for failed components

Report Structure
----------------
{
    "status": "HEALTHY" | "DEGRADED" | "UNHEALTHY",
    "timestamp": float,                    # Unix timestamp
    "duration_ms": float,                  # Check duration
    "components": {
        "database": {
            "status": "HEALTHY" | "DEGRADED" | "UNHEALTHY",
            "available": bool,
            "consecutive_failures": int,
            "consecutive_successes": int,
            "is_healthy": bool,
            "monitor_state": bool | None,
            "error": str | None
        },
        "redis": {
            "status": "HEALTHY" | "DEGRADED" | "UNHEALTHY",
            "available": bool,
            "state": str,
            "is_running": bool,
            "consecutive_failures": int,
            "consecutive_successes": int,
            "error_rate": float,
            "avg_latency_ms": float,
            "last_check_time": float | None,
            "error": str | None
        }
    },
    "errors": List[str]                    # All component errors
}

Configuration
-------------
- `health_check_timeout_seconds`: Maximum time for health check
  (default: 5.0, fallback to ConfigManager)

Dependencies
------------
- src.core.database.service.DatabaseService
- src.core.database.health_monitor.DatabaseHealthMonitor
- src.core.redis.health_monitor.RedisHealthMonitor
- src.core.config.config.ConfigManager
- src.core.logging.logger.get_logger

Design Decisions
----------------
**Timeout Protection**:
    All health checks are wrapped in asyncio.wait_for with configurable timeout
    to prevent hanging on slow components.

**Error Isolation**:
    Individual component check failures are caught and reported in the health
    report structure rather than propagating as exceptions.

**Graceful Degradation**:
    If one component fails to respond, the health check continues and reports
    on available components with explicit error messages.

**Monitor Injection**:
    Monitors are injected via initialize() rather than imported directly to
    avoid circular dependencies and enable testing.

**Status Aggregation**:
    Overall status is determined by the worst component status, with UNKNOWN
    treated as UNHEALTHY for safety.

Usage Examples
--------------
Basic health check:
    from src.core.infra.health import UnifiedHealthCheck
    
    report = await UnifiedHealthCheck.check()
    print(report["status"])  # "HEALTHY" | "DEGRADED" | "UNHEALTHY"
    
    if report["components"]["database"]["status"] != "HEALTHY":
        logger.error("Database unhealthy!")

Health check with custom timeout:
    # Quick health check with 2-second timeout
    report = await UnifiedHealthCheck.check(timeout_seconds=2.0)
    if report["status"] == "UNHEALTHY":
        await shutdown_gracefully()

Integration with monitoring system:
    # In monitoring endpoint handler
    @app.get("/health")
    async def health_endpoint():
        report = await UnifiedHealthCheck.check()
        status_code = 200 if report["status"] == "HEALTHY" else 503
        return JSONResponse(content=report, status_code=status_code)

Integration with bot lifecycle:
    # In BotLifecycle startup
    report = await UnifiedHealthCheck.check()
    if report["status"] == "UNHEALTHY":
        raise RuntimeError(f"System unhealthy at startup: {report['errors']}")
    logger.info("All systems healthy", extra={"health_report": report})

Pre-deployment validation:
    # In deployment script
    import asyncio
    from src.core.infra.health import UnifiedHealthCheck
    
    async def validate_deployment():
        report = await UnifiedHealthCheck.check(timeout_seconds=10.0)
        
        if report["status"] != "HEALTHY":
            print(f"Deployment validation failed: {report['status']}")
            print(f"Details: {report['components']}")
            sys.exit(1)
        
        print("All systems healthy - deployment validated")
    
    asyncio.run(validate_deployment())

Error Handling
--------------
- Individual component check failures are caught and reported
- Timeout errors result in UNHEALTHY status for that component
- Health check never raises exceptions - always returns a report
- Partial health reports returned if some components fail to respond
- All errors are logged with full context for debugging
"""

from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING, cast

from src.core.config.manager import ConfigManager
from src.core.logging.logger import get_logger

# Conditional imports to avoid circular dependencies
if TYPE_CHECKING:
    from src.core.database.health_monitor import DatabaseHealthMonitor
    from src.core.redis.health_monitor import RedisHealthMonitor

logger = get_logger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
# HEALTH STATUS
# ═════════════════════════════════════════════════════════════════════════════


class HealthStatus(Enum):
    """
    Overall system health status.
    
    Attributes
    ----------
    HEALTHY : str
        All components operational and responsive
    DEGRADED : str
        All components up but some performing poorly
    UNHEALTHY : str
        One or more critical components down or unresponsive
    """

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"


# ═════════════════════════════════════════════════════════════════════════════
# UNIFIED HEALTH CHECK
# ═════════════════════════════════════════════════════════════════════════════


class UnifiedHealthCheck:
    """
    Unified health check service for all infrastructure components.

    This class provides static methods for checking overall system health
    by aggregating health status from all critical components.

    The health check is designed to be non-blocking, timeout-protected, and
    resilient to individual component failures.
    """

    # Default timeout if not specified and ConfigManager unavailable
    DEFAULT_TIMEOUT_SECONDS: float = 5.0

    # Class-level references to monitors (set by initialize())
    _database_monitor: Optional[DatabaseHealthMonitor] = None
    _redis_monitor: Optional[RedisHealthMonitor] = None
    _config_manager: Optional[ConfigManager] = None
    _initialized: bool = False

    @classmethod
    def initialize(
        cls,
        database_monitor: Optional[DatabaseHealthMonitor] = None,
        redis_monitor: Optional[RedisHealthMonitor] = None,
        config_manager: Optional[ConfigManager] = None,
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
        config_manager : ConfigManager, optional
            Reference to ConfigManager for timeout configuration

        Notes
        -----
        - This method can be called multiple times to update monitors
        - At least one monitor should be provided for meaningful health checks
        """
        cls._database_monitor = database_monitor
        cls._redis_monitor = redis_monitor
        cls._config_manager = config_manager
        cls._initialized = True

        logger.info(
            "UnifiedHealthCheck initialized",
            extra={
                "has_database_monitor": database_monitor is not None,
                "has_redis_monitor": redis_monitor is not None,
                "has_config_manager": config_manager is not None,
            },
        )

    @classmethod
    async def check(cls, timeout_seconds: Optional[float] = None) -> Dict[str, Any]:
        """
        Perform comprehensive health check of all infrastructure components.

        Parameters
        ----------
        timeout_seconds : float, optional
            Maximum time to wait for health check completion.
            Falls back to ConfigManager, then DEFAULT_TIMEOUT_SECONDS.

        Returns
        -------
        Dict[str, Any]
            Comprehensive health report with overall status and component details

        Notes
        -----
        - This method never raises exceptions
        - Returns partial results on timeout or error
        - All component errors are included in the report
        - Structured for easy integration with monitoring systems
        """
        start_time = time.time()

        # Determine timeout with fallback chain
        if timeout_seconds is None:
            if cls._config_manager is not None:
                try:
                    timeout_value = cls._config_manager.get(
                        "health_check_timeout_seconds",
                        default=cls.DEFAULT_TIMEOUT_SECONDS,
                    )
                    # Ensure we got a float/int value
                    if isinstance(timeout_value, (int, float)):
                        timeout_seconds = float(timeout_value)
                    else:
                        timeout_seconds = cls.DEFAULT_TIMEOUT_SECONDS
                except Exception:
                    timeout_seconds = cls.DEFAULT_TIMEOUT_SECONDS
                    logger.warning(
                        "Failed to load timeout from ConfigManager, using default",
                        extra={"default_timeout": cls.DEFAULT_TIMEOUT_SECONDS},
                    )
            else:
                timeout_seconds = cls.DEFAULT_TIMEOUT_SECONDS

        # Warn if not initialized
        if not cls._initialized:
            logger.warning(
                "UnifiedHealthCheck not initialized - health checks may be incomplete"
            )

        # Run component checks concurrently with timeout protection
        try:
            db_result, redis_result = await asyncio.wait_for(
                asyncio.gather(
                    cls._safe_check_database(),
                    cls._safe_check_redis(),
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

        # Handle exceptions from individual checks (shouldn't happen with _safe_ wrappers)
        # Type-narrow to Dict[str, Any]
        db_status: Dict[str, Any]
        redis_status: Dict[str, Any]

        if isinstance(db_result, Exception):
            logger.error(
                "Unexpected error in database health check",
                extra={
                    "error": str(db_result),
                    "error_type": type(db_result).__name__,
                },
                exc_info=db_result,
            )
            db_status = cls._build_error_component("database", db_result)
        else:
            db_status = cast(Dict[str, Any], db_result)

        if isinstance(redis_result, Exception):
            logger.error(
                "Unexpected error in Redis health check",
                extra={
                    "error": str(redis_result),
                    "error_type": type(redis_result).__name__,
                },
                exc_info=redis_result,
            )
            redis_status = cls._build_error_component("redis", redis_result)
        else:
            redis_status = cast(Dict[str, Any], redis_result)

        # Determine overall status
        overall_status = cls._determine_overall_status(db_status, redis_status)

        # Build comprehensive report
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
                "error_count": len(report["errors"]),
            },
        )

        return report

    # ═════════════════════════════════════════════════════════════════════════
    # COMPONENT CHECKS
    # ═════════════════════════════════════════════════════════════════════════

    @classmethod
    async def _safe_check_database(cls) -> Dict[str, Any]:
        """
        Safely check database health with error isolation.
        
        Returns
        -------
        Dict[str, Any]
            Database health status dictionary
        """
        try:
            return await cls._check_database()
        except Exception as exc:
            logger.error(
                "Database health check failed",
                extra={
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            return cls._build_error_component("database", exc)

    @classmethod
    async def _safe_check_redis(cls) -> Dict[str, Any]:
        """
        Safely check Redis health with error isolation.
        
        Returns
        -------
        Dict[str, Any]
            Redis health status dictionary
        """
        try:
            return await cls._check_redis()
        except Exception as exc:
            logger.error(
                "Redis health check failed",
                extra={
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            return cls._build_error_component("redis", exc)

    @classmethod
    async def _check_database(cls) -> Dict[str, Any]:
        """
        Check database health via DatabaseService and monitor.
        
        Returns
        -------
        Dict[str, Any]
            Database health status with detailed metrics
        """
        if cls._database_monitor is None:
            logger.warning("Database health monitor not initialized")
            return {
                "status": "UNKNOWN",
                "available": False,
                "error": "Health monitor not initialized",
            }

        # Import here to avoid circular dependency
        from src.core.database.service import DatabaseService

        # Perform actual health check
        is_healthy = await DatabaseService.health_check()

        # Get monitor state
        monitor_healthy = cls._database_monitor._is_healthy
        consecutive_failures = cls._database_monitor._consecutive_failures
        consecutive_successes = cls._database_monitor._consecutive_successes

        # Determine status
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

    @classmethod
    async def _check_redis(cls) -> Dict[str, Any]:
        """
        Check Redis health via RedisHealthMonitor.
        
        Returns
        -------
        Dict[str, Any]
            Redis health status with detailed metrics
        """
        if cls._redis_monitor is None:
            logger.warning("Redis health monitor not initialized")
            return {
                "status": "UNKNOWN",
                "available": False,
                "error": "Health monitor not initialized",
            }

        # Get status from Redis health monitor
        status_dict = cls._redis_monitor.get_status()

        # Map state to status
        state = status_dict.get("state", "UNKNOWN")
        is_available = state != "UNHEALTHY"

        return {
            "status": state,
            "available": is_available,
            "state": state,
            "is_running": status_dict.get("is_running", False),
            "consecutive_failures": status_dict.get("consecutive_failures", 0),
            "consecutive_successes": status_dict.get("consecutive_successes", 0),
            "error_rate": status_dict.get("error_rate", 0.0),
            "avg_latency_ms": status_dict.get("avg_latency_ms", 0.0),
            "last_check_time": status_dict.get("last_check_time"),
            "error": None,
        }

    # ═════════════════════════════════════════════════════════════════════════
    # STATUS AGGREGATION
    # ═════════════════════════════════════════════════════════════════════════

    @classmethod
    def _determine_overall_status(
        cls,
        db_status: Dict[str, Any],
        redis_status: Dict[str, Any],
    ) -> HealthStatus:
        """
        Determine overall system health from component statuses.

        Status Hierarchy Logic:
        - UNHEALTHY: Any critical component is UNHEALTHY or UNKNOWN
        - DEGRADED: All components up but at least one is DEGRADED
        - HEALTHY: All components are HEALTHY

        Parameters
        ----------
        db_status : Dict[str, Any]
            Database component status
        redis_status : Dict[str, Any]
            Redis component status

        Returns
        -------
        HealthStatus
            Aggregated overall system health status
        """
        db_state = db_status.get("status", "UNKNOWN")
        redis_state = redis_status.get("status", "UNKNOWN")

        # UNKNOWN is treated as UNHEALTHY for safety
        unhealthy_states = ("UNHEALTHY", "UNKNOWN")

        # If any component is unhealthy or unknown, system is unhealthy
        if db_state in unhealthy_states or redis_state in unhealthy_states:
            return HealthStatus.UNHEALTHY

        # If any component is degraded, system is degraded
        if db_state == "DEGRADED" or redis_state == "DEGRADED":
            return HealthStatus.DEGRADED

        # All components healthy
        return HealthStatus.HEALTHY

    @classmethod
    def _collect_errors(cls, *component_statuses: Dict[str, Any]) -> List[str]:
        """
        Collect all error messages from component statuses.
        
        Parameters
        ----------
        *component_statuses : Dict[str, Any]
            Variable number of component status dictionaries

        Returns
        -------
        List[str]
            List of all error messages from components
        """
        errors = []
        for status in component_statuses:
            error = status.get("error")
            if error:
                errors.append(error)
        return errors

    # ═════════════════════════════════════════════════════════════════════════
    # ERROR HANDLING
    # ═════════════════════════════════════════════════════════════════════════

    @classmethod
    def _build_error_component(cls, component_name: str, error: Exception) -> Dict[str, Any]:
        """
        Build error status dictionary for a failed component.
        
        Parameters
        ----------
        component_name : str
            Name of the component that failed
        error : Exception
            The exception that occurred

        Returns
        -------
        Dict[str, Any]
            Component status dictionary indicating failure
        """
        return {
            "status": "UNHEALTHY",
            "available": False,
            "error": f"{type(error).__name__}: {str(error)}",
        }

    @classmethod
    def _build_timeout_report(cls, timeout_seconds: float) -> Dict[str, Any]:
        """
        Build health report for timeout case.
        
        Parameters
        ----------
        timeout_seconds : float
            The timeout duration that was exceeded

        Returns
        -------
        Dict[str, Any]
            Complete health report indicating timeout
        """
        error_msg = f"Health check timed out after {timeout_seconds}s"

        return {
            "status": HealthStatus.UNHEALTHY.value,
            "timestamp": time.time(),
            "duration_ms": timeout_seconds * 1000,
            "components": {
                "database": {
                    "status": "UNKNOWN",
                    "available": False,
                    "error": error_msg,
                },
                "redis": {
                    "status": "UNKNOWN",
                    "available": False,
                    "error": error_msg,
                },
            },
            "errors": [error_msg],
        }