"""
Database subsystem bootstrap for Lumen 2025.

Purpose
-------
Provide a single entry point for initializing and shutting down the database
subsystem, including:

- Engine + session factory initialization.
- Optional readiness verification via health checks.
- Construction helpers for health monitors and retry policies.

Responsibilities
----------------
- Centralize database subsystem startup and shutdown.
- Provide helpers for creating related infra components (health monitor,
  retry policy).
- Emit structured logs around bootstrap lifecycle.

Non-Responsibilities
--------------------
- Does not perform migrations.
- Does not manage domain state or business logic.
- Does not create background tasks by itself; the caller is responsible for
  scheduling monitors or other loops.

Design Notes
------------
- Intended to be called from the main application bootstrap sequence.
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
