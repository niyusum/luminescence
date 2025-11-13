"""
Database health monitor for Lumen 2025.

Purpose
-------
Provide a small, focused async loop that periodically probes the database via
`DatabaseService.health_check()` and emits metrics/logs about availability.

Responsibilities
----------------
- Periodically run health checks on the database.
- Track transitions between healthy and unhealthy states.
- Emit structured logs and database metrics on each probe and state change.

Non-Responsibilities
--------------------
- Does not manage the database engine or sessions.
- Does not perform retries for business operations.
- Does not implement circuit-breaking for callers (handled elsewhere).
- Does not know about domain models or services.

Design Notes
------------
- The monitor is **opt-in**: nothing runs automatically.
- Callers must explicitly create an instance and schedule `run_forever` in an
  asyncio task during startup, and signal shutdown via an `asyncio.Event`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

from src.core.config.config import Config
from src.core.logging.logger import get_logger
from src.core.database.service import DatabaseService
from src.core.database.metrics import DatabaseMetrics

logger = get_logger(__name__)


@dataclass
class DatabaseHealthMonitorConfig:
    """Configuration for the database health monitor."""

    interval_seconds: float
    failure_threshold: int
    recovery_threshold: int

    @classmethod
    def from_config(cls) -> "DatabaseHealthMonitorConfig":
        """Build from global Config values with safe defaults."""
        interval_seconds = float(
            getattr(Config, "DATABASE_HEALTH_INTERVAL_SECONDS", 10.0)
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


class DatabaseHealthMonitor:
    """
    Periodic database health monitor.

    Typical usage
    -------------
    >>> stop_event = asyncio.Event()
    >>> monitor = DatabaseHealthMonitor.from_config()
    >>> task = asyncio.create_task(monitor.run_forever(stop_event=stop_event))
    ...
    >>> stop_event.set()
    >>> await task
    """

    def __init__(self, config: DatabaseHealthMonitorConfig) -> None:
        self._config = config
        self._consecutive_failures: int = 0
        self._consecutive_successes: int = 0
        self._is_healthy: Optional[bool] = None

    @classmethod
    def from_config(cls) -> "DatabaseHealthMonitor":
        return cls(DatabaseHealthMonitorConfig.from_config())

    async def run_forever(self, *, stop_event: asyncio.Event) -> None:
        """
        Run health checks until `stop_event` is set.

        This method should be scheduled as a background task.
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
                try:
                    await asyncio.wait_for(
                        stop_event.wait(),
                        timeout=self._config.interval_seconds,
                    )
                except asyncio.TimeoutError:
                    # Normal case: interval elapsed.
                    continue
        finally:
            logger.info("DatabaseHealthMonitor stopped")

    async def _tick_once(self) -> None:
        healthy = await DatabaseService.health_check()

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
            },
        )

        # State transitions: healthy -> unhealthy
        if (
            healthy is False
            and (self._is_healthy is True or self._is_healthy is None)
            and self._consecutive_failures >= self._config.failure_threshold
        ):
            self._is_healthy = False
            logger.error(
                "Database marked UNHEALTHY by health monitor",
                extra={
                    "consecutive_failures": self._consecutive_failures,
                    "failure_threshold": self._config.failure_threshold,
                },
            )

        # State transitions: unhealthy -> healthy
        if (
            healthy is True
            and self._is_healthy is False
            and self._consecutive_successes >= self._config.recovery_threshold
        ):
            self._is_healthy = True
            logger.info(
                "Database marked HEALTHY by health monitor",
                extra={
                    "consecutive_successes": self._consecutive_successes,
                    "recovery_threshold": self._config.recovery_threshold,
                },
            )

        # Metrics are already recorded by DatabaseService.health_check()
        # via DatabaseMetrics, so we don't emit additional metrics here.
