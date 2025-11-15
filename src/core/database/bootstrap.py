"""
Database Subsystem Bootstrap - Infrastructure Orchestration (Lumen 2025)

Purpose
-------
Single entry point for initializing and shutting down the entire database
subsystem with health verification and component factory methods.

Orchestrates DatabaseService initialization, health verification, and provides
convenient factory methods for creating related infrastructure components.

Responsibilities
----------------
- Initialize DatabaseService (engine, session factory, connection pool)
- Optionally verify database readiness via health check with timeout
- Provide factory methods for DatabaseHealthMonitor and DatabaseRetryPolicy
- Emit structured logs for bootstrap lifecycle events
- Propagate initialization failures with clear error messages
- Graceful shutdown with resource cleanup

Non-Responsibilities
--------------------
- Database migrations (handled by Alembic)
- Domain state management or business logic
- Background task scheduling (caller schedules monitors)
- Connection string construction (handled by Config)
- Transaction management (handled by DatabaseService)
- Query execution (handled by services)

LUMEN 2025 Compliance
---------------------
✓ Article I: Transaction-safe initialization via DatabaseService
✓ Article II: Comprehensive audit logging of bootstrap events
✓ Article III: Config-driven with safe defaults
✓ Article IX: Graceful degradation (health check optional, clear errors)
✓ Article X: Structured observability throughout lifecycle

Architecture Notes
------------------
**Bootstrap Sequence**:
1. `initialize_database_subsystem()` called during bot startup
2. DatabaseService initializes engine and session factory
3. Optional health check verifies database connectivity with timeout
4. Returns on success or raises DatabaseInitializationError

**Health Verification**:
- Configurable timeout via DATABASE_BOOTSTRAP_HEALTH_TIMEOUT_SECONDS
- Default: 5.0 seconds
- Can be disabled via `verify_health=False` for fast dev startup
- Failure propagates as DatabaseInitializationError

**Component Factories**:
- `create_health_monitor()`: Background health monitoring
- `create_retry_policy()`: Retry logic for transient failures

**Shutdown Sequence**:
1. `shutdown_database_subsystem()` called during bot shutdown
2. DatabaseService.shutdown() disposes engine and closes connections
3. Logs completion for observability

Configuration
-------------
Bootstrap behavior controlled by Config:
- DATABASE_URL (required)
- DATABASE_BOOTSTRAP_HEALTH_TIMEOUT_SECONDS (default: 5.0)
- DATABASE_HEALTH_CHECK_INTERVAL_SECONDS (default: 30.0)
- DATABASE_RETRY_MAX_ATTEMPTS (default: 3)

Usage Example
-------------
Basic initialization:

>>> from src.core.database.bootstrap import (
>>>     initialize_database_subsystem,
>>>     shutdown_database_subsystem,
>>> )
>>>
>>> # During bot startup
>>> try:
>>>     await initialize_database_subsystem(verify_health=True)
>>>     logger.info("Database ready")
>>> except DatabaseInitializationError as e:
>>>     logger.critical(f"Database initialization failed: {e}")
>>>     raise
>>>
>>> # During bot shutdown
>>> await shutdown_database_subsystem()

With health monitoring:

>>> from src.core.database.bootstrap import (
>>>     initialize_database_subsystem,
>>>     create_health_monitor,
>>>     shutdown_database_subsystem,
>>> )
>>>
>>> # Initialize database
>>> await initialize_database_subsystem()
>>>
>>> # Create and start health monitor
>>> stop_event = asyncio.Event()
>>> monitor = create_health_monitor()
>>> monitor_task = asyncio.create_task(monitor.run_forever(stop_event=stop_event))
>>>
>>> # ... bot runs ...
>>>
>>> # Shutdown
>>> stop_event.set()
>>> await monitor_task
>>> await shutdown_database_subsystem()

Skip health check for fast dev startup:

>>> # In development, skip health check for faster restarts
>>> await initialize_database_subsystem(verify_health=False)

Error Handling
--------------
`initialize_database_subsystem()` raises DatabaseInitializationError when:
- Database connection fails
- Health check times out (if verify_health=True)
- Health check fails (if verify_health=True)
- Engine creation fails
- Configuration is invalid

All errors include:
- Clear error message
- Structured logging with context
- Original exception preserved via `from exc`
"""

from __future__ import annotations

import asyncio
from typing import Optional

from src.core.config.config import Config
from src.core.logging.logger import get_logger
from src.core.database.service import (
    DatabaseInitializationError,
    DatabaseService,
)
from src.core.database.health_monitor import (
    DatabaseHealthMonitor,
    DatabaseHealthMonitorConfig,
)
from src.core.database.retry_policy import (
    DatabaseRetryConfig,
    DatabaseRetryPolicy,
)

logger = get_logger(__name__)


# ============================================================================
# Subsystem Lifecycle
# ============================================================================


async def initialize_database_subsystem(*, verify_health: bool = True) -> None:
    """
    Initialize the database subsystem.

    Steps
    -----
    1. Initialize DatabaseService (engine + session factory)
    2. Optionally verify readiness with health check (if verify_health=True)

    Parameters
    ----------
    verify_health : bool, default=True
        If True, performs a health check after initialization to verify
        database connectivity. Health check has a configurable timeout.

    Raises
    ------
    DatabaseInitializationError
        If initialization fails or health check fails/times out.

    Notes
    -----
    - Safe to skip health check in development for faster startup
    - Health timeout controlled by DATABASE_BOOTSTRAP_HEALTH_TIMEOUT_SECONDS
    - Logs all steps for observability
    """
    logger.info("Initializing database subsystem")

    try:
        await DatabaseService.initialize()
    except DatabaseInitializationError:
        # Already logged and has clear error message
        raise
    except Exception as exc:
        logger.error(
            "Unexpected error during database initialization",
            extra={
                "error": str(exc),
                "error_type": type(exc).__name__,
            },
            exc_info=True,
        )
        raise DatabaseInitializationError(
            f"Database initialization failed: {exc}"
        ) from exc

    if not verify_health:
        logger.info("Database subsystem initialized (health check skipped)")
        return

    # Perform health check with timeout
    health_timeout = float(
        getattr(Config, "DATABASE_BOOTSTRAP_HEALTH_TIMEOUT_SECONDS", 5.0)
    )

    logger.debug(
        "Performing bootstrap health check",
        extra={"timeout_seconds": health_timeout},
    )

    try:
        healthy = await asyncio.wait_for(
            DatabaseService.health_check(),
            timeout=health_timeout,
        )
    except asyncio.TimeoutError as exc:
        logger.error(
            "Database health check timed out during bootstrap",
            extra={"timeout_seconds": health_timeout},
            exc_info=True,
        )
        raise DatabaseInitializationError(
            f"Database health check timed out after {health_timeout}s"
        ) from exc
    except Exception as exc:
        logger.error(
            "Unexpected error during bootstrap health check",
            extra={
                "error": str(exc),
                "error_type": type(exc).__name__,
            },
            exc_info=True,
        )
        raise DatabaseInitializationError(
            f"Database health check failed: {exc}"
        ) from exc

    if not healthy:
        logger.error("Database health check failed during bootstrap")
        raise DatabaseInitializationError(
            "Database is unreachable or unhealthy after initialization"
        )

    logger.info("Database subsystem initialized and healthy")


async def shutdown_database_subsystem() -> None:
    """
    Shutdown the database subsystem.

    Calls DatabaseService.shutdown() to dispose the engine and close all
    connections. Emits structured logs for observability.

    This method is safe to call multiple times and will not raise exceptions
    if the database is already shut down.
    """
    logger.info("Shutting down database subsystem")

    try:
        await DatabaseService.shutdown()
        logger.info("Database subsystem shutdown complete")
    except Exception as exc:
        logger.error(
            "Error during database subsystem shutdown",
            extra={
                "error": str(exc),
                "error_type": type(exc).__name__,
            },
            exc_info=True,
        )
        # Don't re-raise during shutdown to allow graceful degradation
        logger.warning("Database shutdown completed with errors")


# ============================================================================
# Component Factory Methods
# ============================================================================


def create_health_monitor() -> DatabaseHealthMonitor:
    """
    Create a DatabaseHealthMonitor configured from Config.

    Returns
    -------
    DatabaseHealthMonitor
        Configured health monitor instance ready to run.

    Usage
    -----
    >>> monitor = create_health_monitor()
    >>> stop_event = asyncio.Event()
    >>> task = asyncio.create_task(monitor.run_forever(stop_event=stop_event))
    >>> # ... later ...
    >>> stop_event.set()
    >>> await task

    Configuration
    -------------
    Uses Config values:
    - DATABASE_HEALTH_CHECK_INTERVAL_SECONDS
    - DATABASE_HEALTH_FAILURE_THRESHOLD
    - DATABASE_HEALTH_RECOVERY_THRESHOLD
    """
    config = DatabaseHealthMonitorConfig.from_config()
    monitor = DatabaseHealthMonitor(config)

    logger.debug(
        "Created DatabaseHealthMonitor from config",
        extra={
            "interval_seconds": config.interval_seconds,
            "failure_threshold": config.failure_threshold,
            "recovery_threshold": config.recovery_threshold,
        },
    )

    return monitor


def create_retry_policy() -> DatabaseRetryPolicy:
    """
    Create a DatabaseRetryPolicy configured from Config.

    Returns
    -------
    DatabaseRetryPolicy
        Configured retry policy instance ready to use.

    Usage
    -----
    >>> retry_policy = create_retry_policy()
    >>> async def operation():
    >>>     async with DatabaseService.get_transaction() as session:
    >>>         # ... database work ...
    >>>         pass
    >>> result = await retry_policy.execute(
    >>>     operation,
    >>>     operation_name="player.update_lumees"
    >>> )

    Configuration
    -------------
    Uses Config values:
    - DATABASE_RETRY_MAX_ATTEMPTS
    - DATABASE_RETRY_INITIAL_BACKOFF_MS
    - DATABASE_RETRY_MAX_BACKOFF_MS
    - DATABASE_RETRY_JITTER_MS
    """
    config = DatabaseRetryConfig.from_config()
    policy = DatabaseRetryPolicy(config)

    logger.debug(
        "Created DatabaseRetryPolicy from config",
        extra={
            "max_attempts": config.max_attempts,
            "initial_backoff_ms": config.initial_backoff_ms,
            "max_backoff_ms": config.max_backoff_ms,
            "jitter_ms": config.jitter_ms,
        },
    )

    return policy


# ============================================================================
# Legacy Compatibility Aliases
# ============================================================================


# Maintain compatibility with old function names
create_database_health_monitor_from_config = create_health_monitor
create_database_retry_policy_from_config = create_retry_policy