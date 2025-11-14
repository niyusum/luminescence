"""
Database Subsystem Bootstrap for Lumen (2025)

Purpose
-------
Provide a single entry point for initializing and shutting down the entire
database subsystem with health verification and optional component construction.

This module serves as the orchestration layer for database infrastructure,
coordinating DatabaseService initialization, health verification, and providing
factory methods for related infrastructure components (health monitors, retry
policies).

Key Features:
- Engine + session factory initialization via DatabaseService
- Optional readiness verification via health checks with timeout
- Convenience helpers for creating health monitors and retry policies
- Structured logging throughout bootstrap lifecycle
- Graceful shutdown with resource cleanup

Responsibilities
----------------
- Centralize database subsystem startup and shutdown lifecycle
- Initialize DatabaseService (engine, session factory, connection pool)
- Optionally verify database readiness via health check with timeout
- Provide factory methods for related components:
  - `create_database_health_monitor_from_config()`
  - `create_database_retry_policy_from_config()`
- Emit structured logs for bootstrap events and errors
- Propagate initialization failures with clear error messages

Non-Responsibilities
--------------------
- Database migrations (handled by Alembic/migration scripts)
- Domain state management or business logic
- Background task scheduling (caller schedules health monitors)
- Connection string construction (handled by Config)
- Transaction management (handled by DatabaseService)
- Query execution (handled by services/repositories)

LUMEN LAW Compliance
--------------------
- Article I: Transaction-safe initialization (DatabaseService handles pooling)
- Article II: Comprehensive audit logging of bootstrap events
- Article IX: Graceful degradation (health check optional, clear errors)
- Article X: Structured observability throughout lifecycle

Architecture Notes
------------------
**Bootstrap Sequence**:
1. `initialize_database_subsystem()` called during bot startup
2. DatabaseService initializes engine and session factory
3. Optional health check verifies database connectivity
4. Returns on success or raises DatabaseInitializationError on failure

**Health Verification**:
- Configurable timeout via `DATABASE_BOOTSTRAP_HEALTH_TIMEOUT_SECONDS`
- Default: 5 seconds
- Can be disabled by passing `verify_health=False`
- Useful for fast startup in dev environments

**Component Factories**:
- `create_database_health_monitor_from_config()`: Background health monitoring
- `create_database_retry_policy_from_config()`: Retry logic for transient failures

**Shutdown Sequence**:
1. `shutdown_database_subsystem()` called during bot shutdown
2. DatabaseService.shutdown() disposes engine and closes connections
3. Logs completion for observability

Configuration
-------------
Bootstrap behavior controlled by Config attributes:
- `DATABASE_URL`: Connection string (required)
- `DATABASE_BOOTSTRAP_HEALTH_TIMEOUT_SECONDS`: Health check timeout (default: 5.0)
- `DATABASE_HEALTH_CHECK_INTERVAL_SECONDS`: For health monitor (default: 30)
- `DATABASE_RETRY_MAX_ATTEMPTS`: For retry policy (default: 3)

Usage Example
-------------
Basic initialization in bot startup:

>>> from src.core.database.bootstrap import (
>>>     initialize_database_subsystem,
>>>     shutdown_database_subsystem
>>> )
>>>
>>> # During bot startup (in setup_hook or main)
>>> try:
>>>     await initialize_database_subsystem(verify_health=True)
>>>     logger.info("Database ready")
>>> except DatabaseInitializationError as e:
>>>     logger.critical(f"Database initialization failed: {e}")
>>>     raise
>>>
>>> # During bot shutdown (in close method)
>>> await shutdown_database_subsystem()

With health monitoring:

>>> from src.core.database.bootstrap import (
>>>     initialize_database_subsystem,
>>>     create_database_health_monitor_from_config,
>>>     shutdown_database_subsystem
>>> )
>>>
>>> # Initialize database
>>> await initialize_database_subsystem()
>>>
>>> # Create and start health monitor
>>> monitor = create_database_health_monitor_from_config()
>>> asyncio.create_task(monitor.start())
>>>
>>> # ... bot runs ...
>>>
>>> # Shutdown
>>> await monitor.stop()
>>> await shutdown_database_subsystem()

Skip health check for fast dev startup:

>>> # In development, skip health check for faster restarts
>>> await initialize_database_subsystem(verify_health=False)

Error Handling
--------------
`initialize_database_subsystem()` can raise:

**DatabaseInitializationError** - When:
- Database connection fails
- Health check times out (if `verify_health=True`)
- Health check fails (if `verify_health=True`)
- Engine creation fails
- Configuration is invalid

All errors include:
- Clear error message
- Structured logging with context
- Original exception preserved via `from exc`

Integration with BotLifecycle
------------------------------
This module is typically called from BotLifecycle during bot startup:

>>> # In BotLifecycle.initialize_service():
>>> db_time = await self.initialize_service(
>>>     "Database",
>>>     initialize_database_subsystem(verify_health=True)
>>> )
>>>
>>> # In BotLifecycle.shutdown():
>>> await shutdown_database_subsystem()
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


async def initialize_database_subsystem(*, verify_health: bool = True) -> None:
    """
    Initialize the database subsystem.

    Steps
    -----
    1. Initialize `DatabaseService` (engine + session factory).
    2. Optionally verify readiness with a health check.

    Raises
    ------
    DatabaseInitializationError
        If initialization fails or health check fails when `verify_health=True`.
    """
    logger.info("Initializing database subsystem")

    await DatabaseService.initialize()

    if not verify_health:
        logger.info("Database subsystem initialized (health check skipped)")
        return

    health_timeout = float(
        getattr(Config, "DATABASE_BOOTSTRAP_HEALTH_TIMEOUT_SECONDS", 5.0)
    )

    try:
        healthy = await asyncio.wait_for(
            DatabaseService.health_check(),
            timeout=health_timeout,
        )
    except asyncio.TimeoutError as exc:
        logger.error(
            "Database health check during bootstrap timed out",
            extra={"timeout_seconds": health_timeout},
            exc_info=True,
        )
        raise DatabaseInitializationError(
            "Database health check during bootstrap timed out"
        ) from exc

    if not healthy:
        logger.error("Database health check during bootstrap failed")
        raise DatabaseInitializationError(
            "Database health check during bootstrap failed"
        )

    logger.info("Database subsystem initialized and healthy")


async def shutdown_database_subsystem() -> None:
    """
    Shutdown the database subsystem.

    Calls `DatabaseService.shutdown()` and emits logs.
    """
    logger.info("Shutting down database subsystem")
    await DatabaseService.shutdown()
    logger.info("Database subsystem shutdown complete")


def create_database_health_monitor_from_config() -> DatabaseHealthMonitor:
    """
    Convenience helper to create a `DatabaseHealthMonitor` using Config.
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


def create_database_retry_policy_from_config() -> DatabaseRetryPolicy:
    """
    Convenience helper to create a `DatabaseRetryPolicy` using Config.
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
