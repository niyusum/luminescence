"""
Bot Lifecycle Management for Lumen (2025)

Purpose
-------
Handles bot startup, service initialization, health monitoring, and graceful shutdown.
Separates lifecycle concerns from Discord integration logic.

Responsibilities
----------------
- Startup validation and configuration checks
- Service initialization with timing and error handling
- Background health monitoring for critical services
- Graceful shutdown with resource cleanup
- Startup metrics tracking and logging

Non-Responsibilities
--------------------
- Discord event handling (handled by LumenBot)
- Command execution (handled by LumenBot)
- Cog loading (handled by LumenBot)

Lumen 2025 Compliance
---------------------
- Observability: Structured logging for all lifecycle events
- Graceful degradation: Non-blocking health checks
- Error boundaries: Service failures don't crash bot
- Metrics: Comprehensive startup and health metrics

Architecture Notes
------------------
- BotLifecycle class manages all lifecycle concerns
- ServiceHealth dataclass for health status tracking
- StartupMetrics dataclass for initialization timing
- Background asyncio task for health monitoring
- ConfigManager integration for all tunables
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional, TYPE_CHECKING

from src.core.config import ConfigManager
from src.core.database.service import DatabaseService
from src.core.logging.logger import get_logger
from src.core.redis.service import RedisService

if TYPE_CHECKING:
    from discord.ext import commands

logger = get_logger(__name__)


@dataclass
class ServiceHealth:
    """Health status for a single service."""

    name: str
    healthy: bool
    degraded: bool
    error: Optional[str] = None
    latency_ms: Optional[float] = None


@dataclass
class StartupMetrics:
    """Metrics collected during bot startup."""

    total_time_ms: float
    database_time_ms: float
    redis_time_ms: float
    config_time_ms: float
    cogs_time_ms: float
    sync_time_ms: float
    cogs_loaded: int
    cogs_failed: int


@dataclass
class BotMetrics:
    """Runtime metrics for bot operations."""

    commands_executed: int = 0
    commands_failed: int = 0
    errors_handled: int = 0
    health_checks_performed: int = 0
    health_checks_failed: int = 0
    services_healthy: int = 0
    services_degraded: int = 0
    services_unhealthy: int = 0
    last_health_check: Optional[float] = None
    service_health: Dict[str, ServiceHealth] = field(default_factory=dict)


class BotLifecycle:
    """
    Manages bot lifecycle: startup, health monitoring, and shutdown.

    Handles service initialization with timing, background health monitoring,
    and graceful shutdown with resource cleanup.
    """

    def __init__(self, bot: commands.Bot) -> None:
        """
        Initialize bot lifecycle manager.

        Parameters
        ----------
        bot : commands.Bot
            The Discord bot instance.
        """
        self.bot = bot
        self.metrics = BotMetrics()
        self._health_task: Optional[asyncio.Task] = None
        self._is_shutting_down = False

        # Configuration
        self._health_check_interval = ConfigManager.get(
            "bot.health_check_interval_seconds", 60
        )
        self._startup_timeout = ConfigManager.get("bot.startup_timeout_seconds", 60)

        logger.info(
            "BotLifecycle initialized",
            extra={
                "health_check_interval": self._health_check_interval,
                "startup_timeout": self._startup_timeout,
            },
        )

    # ═════════════════════════════════════════════════════════════════════════
    # STARTUP VALIDATION
    # ═════════════════════════════════════════════════════════════════════════

    async def validate_startup(self) -> None:
        """
        Validate environment and configuration before startup.

        Raises
        ------
        ValueError
            If required configuration is missing or invalid.
        """
        logger.info("Validating bot startup configuration")

        # Check required config
        required_keys = [
            "discord.token",
            "database.url",
            "redis.host",
        ]

        missing_keys = []
        for key in required_keys:
            try:
                value = ConfigManager.get(key)
                if not value:
                    missing_keys.append(key)
            except Exception:
                missing_keys.append(key)

        if missing_keys:
            raise ValueError(
                f"Missing required configuration: {', '.join(missing_keys)}"
            )

        # Validate bot token format (basic check)
        token = ConfigManager.get("discord.token")
        if not isinstance(token, str) or len(token) < 50:
            raise ValueError("Invalid Discord token format")

        logger.info("Startup validation passed")

    # ═════════════════════════════════════════════════════════════════════════
    # SERVICE INITIALIZATION
    # ═════════════════════════════════════════════════════════════════════════

    async def initialize_service(
        self,
        name: str,
        init_coro: Coroutine[Any, Any, Any],
        required: bool = True,
    ) -> float:
        """
        Initialize a service with timing and error handling.

        Parameters
        ----------
        name : str
            Service name for logging.
        init_coro : Coroutine
            The initialization coroutine to execute.
        required : bool
            Whether this service is required for bot operation.

        Returns
        -------
        float
            Time taken in milliseconds.

        Raises
        ------
        RuntimeError
            If a required service fails to initialize.
        """
        start_time = time.perf_counter()

        logger.info(f"Initializing {name}...")

        try:
            await asyncio.wait_for(init_coro, timeout=self._startup_timeout)

            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.info(
                f"{name} initialized successfully",
                extra={"service": name, "time_ms": round(elapsed_ms, 2)},
            )

            return elapsed_ms

        except asyncio.TimeoutError:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            error_msg = f"{name} initialization timed out after {self._startup_timeout}s"

            logger.error(error_msg, extra={"service": name, "time_ms": elapsed_ms})

            if required:
                raise RuntimeError(error_msg)

            return elapsed_ms

        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            error_msg = f"{name} initialization failed: {exc}"

            logger.error(
                error_msg,
                extra={
                    "service": name,
                    "time_ms": elapsed_ms,
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )

            if required:
                raise RuntimeError(error_msg) from exc

            return elapsed_ms

    def log_startup_summary(self, startup_metrics: StartupMetrics) -> None:
        """
        Log comprehensive startup summary with metrics.

        Parameters
        ----------
        startup_metrics : StartupMetrics
            Metrics collected during startup.
        """
        logger.info(
            "Bot startup complete",
            extra={
                "total_time_ms": round(startup_metrics.total_time_ms, 2),
                "database_time_ms": round(startup_metrics.database_time_ms, 2),
                "redis_time_ms": round(startup_metrics.redis_time_ms, 2),
                "config_time_ms": round(startup_metrics.config_time_ms, 2),
                "cogs_time_ms": round(startup_metrics.cogs_time_ms, 2),
                "sync_time_ms": round(startup_metrics.sync_time_ms, 2),
                "cogs_loaded": startup_metrics.cogs_loaded,
                "cogs_failed": startup_metrics.cogs_failed,
            },
        )

        # Log warning if startup took too long
        if startup_metrics.total_time_ms > 10000:  # 10 seconds
            logger.warning(
                f"Slow startup detected: {round(startup_metrics.total_time_ms / 1000, 2)}s"
            )

    # ═════════════════════════════════════════════════════════════════════════
    # HEALTH MONITORING
    # ═════════════════════════════════════════════════════════════════════════

    def start_health_monitoring(self) -> None:
        """Start background health monitoring task."""
        if self._health_task is not None:
            logger.warning("Health monitoring already running")
            return

        self._health_task = asyncio.create_task(self._health_monitor_loop())
        logger.info(
            "Health monitoring started",
            extra={"interval_seconds": self._health_check_interval},
        )

    async def _health_monitor_loop(self) -> None:
        """Main health monitoring loop."""
        logger.debug("Health monitor loop started")

        while not self._is_shutting_down:
            try:
                await self.check_service_health()
                await asyncio.sleep(self._health_check_interval)

            except asyncio.CancelledError:
                logger.debug("Health monitor loop cancelled")
                break

            except Exception as exc:
                self.metrics.health_checks_failed += 1
                logger.error(
                    "Error in health monitor loop",
                    extra={"error": str(exc), "error_type": type(exc).__name__},
                    exc_info=True,
                )
                await asyncio.sleep(self._health_check_interval)

    async def check_service_health(self) -> None:
        """
        Check health of all critical services.

        Updates metrics and logs unhealthy services.
        """
        self.metrics.health_checks_performed += 1
        self.metrics.last_health_check = time.time()

        services_checked: List[ServiceHealth] = []

        # Check database
        db_health = await self._check_database_health()
        services_checked.append(db_health)

        # Check Redis
        redis_health = await self._check_redis_health()
        services_checked.append(redis_health)

        # Update metrics
        self.metrics.services_healthy = sum(1 for s in services_checked if s.healthy)
        self.metrics.services_degraded = sum(1 for s in services_checked if s.degraded)
        self.metrics.services_unhealthy = sum(
            1 for s in services_checked if not s.healthy and not s.degraded
        )

        # Store service health
        for service in services_checked:
            self.metrics.service_health[service.name] = service

        # Log unhealthy services
        unhealthy = [s for s in services_checked if not s.healthy]
        if unhealthy:
            for service in unhealthy:
                logger.warning(
                    f"Service unhealthy: {service.name}",
                    extra={
                        "service": service.name,
                        "degraded": service.degraded,
                        "error": service.error,
                        "latency_ms": service.latency_ms,
                    },
                )

    async def _check_database_health(self) -> ServiceHealth:
        """Check database service health."""
        start_time = time.perf_counter()

        try:
            is_healthy = await DatabaseService.health_check()
            latency_ms = (time.perf_counter() - start_time) * 1000

            return ServiceHealth(
                name="database",
                healthy=is_healthy,
                degraded=False,
                latency_ms=latency_ms,
            )

        except Exception as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000

            return ServiceHealth(
                name="database",
                healthy=False,
                degraded=False,
                error=str(exc),
                latency_ms=latency_ms,
            )

    async def _check_redis_health(self) -> ServiceHealth:
        """Check Redis service health."""
        start_time = time.perf_counter()

        try:
            is_healthy = await RedisService.health_check()
            latency_ms = (time.perf_counter() - start_time) * 1000

            # Check if degraded (high latency)
            degraded = latency_ms > 100  # 100ms threshold

            return ServiceHealth(
                name="redis",
                healthy=is_healthy,
                degraded=degraded,
                latency_ms=latency_ms,
            )

        except Exception as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000

            return ServiceHealth(
                name="redis",
                healthy=False,
                degraded=False,
                error=str(exc),
                latency_ms=latency_ms,
            )

    # ═════════════════════════════════════════════════════════════════════════
    # SHUTDOWN
    # ═════════════════════════════════════════════════════════════════════════

    async def shutdown(self) -> None:
        """
        Perform graceful shutdown with resource cleanup.

        Stops health monitoring, closes services, and cleans up resources.
        """
        if self._is_shutting_down:
            logger.warning("Shutdown already in progress")
            return

        self._is_shutting_down = True
        logger.info("Starting graceful shutdown")

        # Stop health monitoring
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass
            self._health_task = None
            logger.debug("Health monitoring stopped")

        # Close services
        shutdown_tasks = [
            ("Database", DatabaseService.close()),
            ("Redis", RedisService.close()),
        ]

        for service_name, shutdown_coro in shutdown_tasks:
            try:
                await asyncio.wait_for(shutdown_coro, timeout=5.0)
                logger.info(f"{service_name} closed successfully")
            except asyncio.TimeoutError:
                logger.warning(f"{service_name} shutdown timed out")
            except Exception as exc:
                logger.error(
                    f"Error closing {service_name}: {exc}",
                    extra={"error_type": type(exc).__name__},
                    exc_info=True,
                )

        logger.info("Graceful shutdown complete")

    # ═════════════════════════════════════════════════════════════════════════
    # METRICS
    # ═════════════════════════════════════════════════════════════════════════

    def get_metrics_snapshot(self) -> Dict[str, Any]:
        """
        Get current metrics snapshot.

        Returns
        -------
        Dict[str, Any]
            Dictionary with all metrics and service health status.
        """
        return {
            "commands_executed": self.metrics.commands_executed,
            "commands_failed": self.metrics.commands_failed,
            "errors_handled": self.metrics.errors_handled,
            "health_checks_performed": self.metrics.health_checks_performed,
            "health_checks_failed": self.metrics.health_checks_failed,
            "services_healthy": self.metrics.services_healthy,
            "services_degraded": self.metrics.services_degraded,
            "services_unhealthy": self.metrics.services_unhealthy,
            "last_health_check": self.metrics.last_health_check,
            "service_health": {
                name: {
                    "healthy": health.healthy,
                    "degraded": health.degraded,
                    "error": health.error,
                    "latency_ms": health.latency_ms,
                }
                for name, health in self.metrics.service_health.items()
            },
        }
