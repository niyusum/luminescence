"""
Database Health Monitor - Infrastructure Observability (Lumen 2025)

Purpose
-------
Periodic background monitoring of database availability with state tracking,
metrics emission, and structured logging.

Provides an async loop that continuously probes the database via
DatabaseService.health_check() and tracks healthy/unhealthy state transitions
with configurable thresholds.

Responsibilities
----------------
- Periodically execute health checks on the database
- Track consecutive failures and successes
- Detect transitions between healthy and unhealthy states
- Emit structured logs and metrics on state changes
- Provide graceful start/stop with asyncio.Event signaling

Non-Responsibilities
--------------------
- Managing the database engine or sessions (DatabaseService handles this)
- Performing retries for business operations (handled by DatabaseRetryPolicy)
- Implementing circuit-breaking for callers (handled elsewhere)
- Domain logic or Discord integration

LUMEN 2025 Compliance
---------------------
✓ Article I: No state mutations, read-only monitoring
✓ Article II: Comprehensive structured logging
✓ Article III: Config-driven with safe defaults
✓ Article IX: Graceful degradation with clear shutdown
✓ Article X: Maximum observability via logs and metrics

Architecture Notes
------------------
**Opt-In Design**:
- Nothing runs automatically; caller must explicitly create and start
- Uses asyncio.Event for clean shutdown signaling
- Designed for background task scheduling in bot lifecycle

**State Tracking**:
- Tracks consecutive failures and successes separately
- Uses thresholds to prevent flapping between states
- Initial state is None (unknown) until threshold reached

**Thresholds**:
- failure_threshold: Consecutive failures before marking unhealthy
- recovery_threshold: Consecutive successes before marking healthy

Configuration
-------------
All values sourced from Config:
- DATABASE_HEALTH_CHECK_INTERVAL_SECONDS (default: 30.0)
- DATABASE_HEALTH_FAILURE_THRESHOLD (default: 3)
- DATABASE_HEALTH_RECOVERY_THRESHOLD (default: 3)

Usage Example
-------------
Basic usage with bot lifecycle:

>>> from src.core.database.bootstrap import create_health_monitor
>>>
>>> # During bot startup
>>> stop_event = asyncio.Event()
>>> monitor = create_health_monitor()
>>> monitor_task = asyncio.create_task(monitor.run_forever(stop_event=stop_event))
>>>
>>> # ... bot runs ...
>>>
>>> # During bot shutdown
>>> stop_event.set()
>>> await monitor_task

Manual configuration:

>>> from src.core.database.health_monitor import (
>>>     DatabaseHealthMonitor,
>>>     DatabaseHealthMonitorConfig,
>>> )
>>>
>>> config = DatabaseHealthMonitorConfig(
>>>     interval_seconds=10.0,
>>>     failure_threshold=5,
>>>     recovery_threshold=2,
>>> )
>>> monitor = DatabaseHealthMonitor(config)
>>> stop_event = asyncio.Event()
>>> await monitor.run_forever(stop_event=stop_event)

State Transitions
-----------------
**Healthy → Unhealthy**:
- Requires `failure_threshold` consecutive failures
- Emits ERROR-level log with context
- Metrics already recorded by DatabaseService.health_check()

**Unhealthy → Healthy**:
- Requires `recovery_threshold` consecutive successes
- Emits INFO-level log with context
- Metrics already recorded by DatabaseService.health_check()
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

from src.core.config.config import Config
from src.core.logging.logger import get_logger
from src.core.database.service import DatabaseService

logger = get_logger(__name__)


# ============================================================================
# Configuration
# ============================================================================


@dataclass
class DatabaseHealthMonitorConfig:
    """
    Configuration for periodic database health monitoring.

    Attributes
    ----------
    interval_seconds : float
        Time between health checks in seconds.
    failure_threshold : int
        Number of consecutive failures before marking unhealthy.
    recovery_threshold : int
        Number of consecutive successes before marking healthy.
    """

    interval_seconds: float
    failure_threshold: int
    recovery_threshold: int

    @classmethod
    def from_config(cls) -> DatabaseHealthMonitorConfig:
        """
        Build configuration from Config with safe defaults.

        Returns
        -------
        DatabaseHealthMonitorConfig
            Configuration instance sourced from Config.

        Configuration Keys
        ------------------
        - DATABASE_HEALTH_CHECK_INTERVAL_SECONDS (default: 30.0)
        - DATABASE_HEALTH_FAILURE_THRESHOLD (default: 3)
        - DATABASE_HEALTH_RECOVERY_THRESHOLD (default: 3)
        """
        interval_seconds = float(
            getattr(Config, "DATABASE_HEALTH_CHECK_INTERVAL_SECONDS", 30.0)
        )
        failure_threshold = int(
            getattr(Config, "DATABASE_HEALTH_FAILURE_THRESHOLD", 3)
        )
        recovery_threshold = int(
            getattr(Config, "DATABASE_HEALTH_RECOVERY_THRESHOLD", 3)
        )

        return cls(
            interval_seconds=interval_seconds,
            failure_threshold=failure_threshold,
            recovery_threshold=recovery_threshold,
        )


# ============================================================================
# Health Monitor
# ============================================================================


class DatabaseHealthMonitor:
    """
    Periodic database health monitor.

    Continuously probes the database at configured intervals and tracks
    state transitions between healthy and unhealthy based on consecutive
    failures/successes.

    Public API
    ----------
    - __init__(config) -> Create monitor with configuration
    - from_config() -> Create monitor from Config
    - run_forever(stop_event) -> Run monitoring loop until stopped

    Usage
    -----
    >>> stop_event = asyncio.Event()
    >>> monitor = DatabaseHealthMonitor.from_config()
    >>> task = asyncio.create_task(monitor.run_forever(stop_event=stop_event))
    >>> # ... later ...
    >>> stop_event.set()
    >>> await task
    """

    def __init__(self, config: DatabaseHealthMonitorConfig) -> None:
        """
        Initialize health monitor with configuration.

        Parameters
        ----------
        config : DatabaseHealthMonitorConfig
            Configuration specifying intervals and thresholds.
        """
        self._config = config
        self._consecutive_failures: int = 0
        self._consecutive_successes: int = 0
        self._is_healthy: Optional[bool] = None

    @classmethod
    def from_config(cls) -> DatabaseHealthMonitor:
        """
        Create a health monitor configured from Config.

        Returns
        -------
        DatabaseHealthMonitor
            Monitor instance ready to run.

        See Also
        --------
        DatabaseHealthMonitorConfig.from_config : Configuration factory
        """
        return cls(DatabaseHealthMonitorConfig.from_config())

    async def run_forever(self, *, stop_event: asyncio.Event) -> None:
        """
        Run health checks until stop_event is set.

        This method should be scheduled as a background task during bot
        startup and stopped gracefully during shutdown by setting stop_event.

        Parameters
        ----------
        stop_event : asyncio.Event
            Event to signal shutdown. Monitor stops when this is set.

        Notes
        -----
        - Logs startup with configuration details
        - Executes health checks at configured intervals
        - Handles graceful shutdown on stop signal
        - Always logs completion even if interrupted
        """
        logger.info(
            "DatabaseHealthMonitor started",
            extra={
                "interval_seconds": self._config.interval_seconds,
                "failure_threshold": self._config.failure_threshold,
                "recovery_threshold": self._config.recovery_threshold,
            },
        )

        try:
            while not stop_event.is_set():
                await self._tick_once()

                # Wait for interval or stop signal
                try:
                    await asyncio.wait_for(
                        stop_event.wait(),
                        timeout=self._config.interval_seconds,
                    )
                except asyncio.TimeoutError:
                    # Normal case: interval elapsed, continue monitoring
                    continue

        except Exception as exc:
            logger.error(
                "Unexpected error in DatabaseHealthMonitor",
                extra={
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise

        finally:
            logger.info("DatabaseHealthMonitor stopped")

    async def _tick_once(self) -> None:
        """
        Execute a single health check and update state tracking.

        Updates consecutive failure/success counters and detects state
        transitions based on configured thresholds.
        """
        healthy = await DatabaseService.health_check()

        # Update counters
        if healthy:
            self._consecutive_successes += 1
            self._consecutive_failures = 0
        else:
            self._consecutive_failures += 1
            self._consecutive_successes = 0

        logger.debug(
            "Database health monitor tick",
            extra={
                "healthy": healthy,
                "consecutive_failures": self._consecutive_failures,
                "consecutive_successes": self._consecutive_successes,
                "current_state": self._is_healthy,
            },
        )

        # Detect state transitions
        self._check_unhealthy_transition(healthy)
        self._check_healthy_transition(healthy)

    def _check_unhealthy_transition(self, healthy: bool) -> None:
        """
        Check for healthy → unhealthy state transition.

        Parameters
        ----------
        healthy : bool
            Result of current health check.
        """
        should_transition = (
            not healthy
            and (self._is_healthy is True or self._is_healthy is None)
            and self._consecutive_failures >= self._config.failure_threshold
        )

        if should_transition:
            self._is_healthy = False
            logger.error(
                "Database marked UNHEALTHY by health monitor",
                extra={
                    "consecutive_failures": self._consecutive_failures,
                    "failure_threshold": self._config.failure_threshold,
                },
            )

    def _check_healthy_transition(self, healthy: bool) -> None:
        """
        Check for unhealthy → healthy state transition.

        Parameters
        ----------
        healthy : bool
            Result of current health check.
        """
        should_transition = (
            healthy
            and self._is_healthy is False
            and self._consecutive_successes >= self._config.recovery_threshold
        )

        if should_transition:
            self._is_healthy = True
            logger.info(
                "Database marked HEALTHY by health monitor",
                extra={
                    "consecutive_successes": self._consecutive_successes,
                    "recovery_threshold": self._config.recovery_threshold,
                },
            )