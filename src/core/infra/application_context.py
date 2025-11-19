"""
Application Context (Kernel) - Lumen RPG Infrastructure Orchestration
======================================================================

Purpose
-------
Central dependency injection kernel that orchestrates the initialization and
shutdown of all core infrastructure services in the correct dependency order.

Responsibilities
----------------
- Initialize ConfigManager
- Initialize ServiceContainer with dependency injection
- Create and configure LumenBot with dependency injection
- **Explicitly register and load all feature cogs (P1.4)**
- Coordinate graceful shutdown in reverse order
- Provide structured lifecycle logging with timing

Non-Responsibilities
--------------------
- Business logic (delegated to domain services)
- Bot event handling (delegated to LumenBot)
- Domain service implementation (delegated to ServiceContainer)

Lumen 2025 Compliance (P1.4)
-----------------------------
- Strict separation of concerns (infrastructure orchestration only)
- Config-driven initialization
- **Explicit cog registration (no magic discovery)**
- **Constructor injection for all cogs**
- Structured logging with timing metrics
- Graceful degradation on non-critical failures
- Dependency injection for testability
- Zero business logic

Architecture Notes
------------------
The ApplicationContext is the single point of control for:
1. Dependency order enforcement
2. Service lifecycle management
3. Dependency injection coordination
4. **Explicit cog registration and loading (P1.4)**

Initialization Order (Critical):
    1. ConfigManager
    2. ServiceContainer
    3. LumenBot (with injected dependencies)
    4. **Feature Cogs (with dependency injection)**

Shutdown Order (Reverse):
    1. LumenBot.close()
    2. ServiceContainer.shutdown()
    3. DatabaseService.shutdown()
"""

from __future__ import annotations

import time
from typing import Optional

from src.bot.lumen_bot import LumenBot
from src.core.config import Config
from src.core.config.manager import ConfigManager
from src.core.database.service import DatabaseService
from src.core.event import event_bus
from src.core.logging.logger import get_logger
from src.core.services.container import ServiceContainer

logger = get_logger(__name__)

# ============================================================================
# EXPLICIT COG REGISTRATION (P1.4 - No Magic Discovery)
# ============================================================================

FEATURE_COGS = [
    "src.modules.player.cog",
    "src.modules.maiden.cog",
    "src.modules.exploration.cog",
    "src.modules.ascension.cog",
    "src.modules.daily.cog",
    "src.modules.tutorial.cog",
    "src.modules.leaderboard.cog",
    "src.modules.shrine.cog",
    "src.modules.guild.cog",
    "src.modules.summon.cog",
    "src.modules.economy.cog",
    "src.modules.drop.cog",
]


class ApplicationContext:
    """
    Kernel for infrastructure orchestration and dependency injection.

    Manages the complete application lifecycle from initialization through
    shutdown, ensuring services are created in dependency order and torn
    down in reverse order.

    Usage:
        context = ApplicationContext()
        await context.initialize()
        await context.run_bot()  # Blocks until shutdown
    """

    def __init__(self) -> None:
        """
        Initialize application context.

        Note: Does not perform actual initialization - call initialize() for that.
        """
        self._config_manager: Optional[ConfigManager] = None
        self._service_container: Optional[ServiceContainer] = None
        self._bot: Optional[LumenBot] = None
        self._initialized: bool = False

        logger.debug("ApplicationContext created")

    # ========================================================================
    # INITIALIZATION (Dependency Order: ConfigManager → Services → Bot)
    # ========================================================================

    async def initialize(self) -> None:
        """
        Initialize all infrastructure components in dependency order.

        Order:
            1. ConfigManager
            2. ServiceContainer (requires ConfigManager, EventBus)
            3. LumenBot (requires ConfigManager, ServiceContainer, EventBus)

        Raises:
            RuntimeError: If already initialized or initialization fails
        """
        if self._initialized:
            raise RuntimeError("ApplicationContext already initialized")

        logger.info("=" * 70)
        logger.info("APPLICATION CONTEXT INITIALIZATION")
        logger.info("=" * 70)

        start_time = time.perf_counter()

        try:
            # Step 1: Initialize ConfigManager
            config_start = time.perf_counter()
            self._config_manager = ConfigManager()
            await self._config_manager.initialize()
            config_time = (time.perf_counter() - config_start) * 1000
            logger.info("✓ ConfigManager initialized (%.2fms)", config_time)

            # Step 2: Initialize ServiceContainer
            service_start = time.perf_counter()
            self._service_container = ServiceContainer(
                config_manager=self._config_manager,
                event_bus=event_bus,
                logger=get_logger("src.core.services.container"),
            )
            await self._service_container.initialize()
            service_time = (time.perf_counter() - service_start) * 1000
            logger.info("✓ ServiceContainer initialized (%.2fms)", service_time)

            # Step 3: Create LumenBot with dependency injection
            bot_start = time.perf_counter()
            self._bot = LumenBot(
                config_manager=self._config_manager,
                service_container=self._service_container,
                event_bus=event_bus,
            )
            bot_time = (time.perf_counter() - bot_start) * 1000
            logger.info("✓ LumenBot created with DI (%.2fms)", bot_time)

            # Step 4: Load feature cogs with dependency injection (P1.4)
            cogs_start = time.perf_counter()
            await self._load_cogs()
            cogs_time = (time.perf_counter() - cogs_start) * 1000
            logger.info("✓ Feature cogs loaded (%.2fms)", cogs_time)

            self._initialized = True
            total_time = (time.perf_counter() - start_time) * 1000

            logger.info("=" * 70)
            logger.info("✓ Application context initialized successfully")
            logger.info("  Total time: %.2fms", total_time)
            logger.info("=" * 70)

        except Exception as exc:
            logger.critical(
                "Application context initialization failed",
                extra={
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            # Attempt cleanup on initialization failure
            await self._emergency_shutdown()
            raise RuntimeError("Failed to initialize application context") from exc

    async def _load_cogs(self) -> None:
        """
        Load all feature cogs with explicit dependency injection (P1.4).

        Replaces magic discovery with explicit registration for:
        - Clear dependency graph
        - Predictable initialization order
        - Constructor injection for all cogs
        - Per-cog error handling and timing

        Raises:
            RuntimeError: If cog loading fails
        """
        if not self._bot or not self._service_container:
            raise RuntimeError("Cannot load cogs: bot or service_container not initialized")

        logger.info("Loading feature cogs with dependency injection...")

        loaded_count = 0
        failed_cogs = []

        for cog_module_path in FEATURE_COGS:
            cog_name = cog_module_path.split(".")[-2].title()  # e.g., "maiden" -> "Maiden"
            cog_start = time.perf_counter()

            try:
                # Load cog with dependency injection
                # Most cogs use discord.py's setup() pattern which calls bot.add_cog()
                await self._bot.load_extension(cog_module_path)

                cog_time = (time.perf_counter() - cog_start) * 1000
                logger.debug(
                    "  ✓ %s loaded (%.2fms)",
                    cog_name,
                    cog_time,
                )
                loaded_count += 1

            except Exception as exc:
                cog_time = (time.perf_counter() - cog_start) * 1000
                logger.error(
                    "  ✗ %s failed to load (%.2fms)",
                    cog_name,
                    cog_time,
                    extra={
                        "cog_module": cog_module_path,
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    },
                    exc_info=True,
                )
                failed_cogs.append((cog_name, str(exc)))

        # Log summary
        logger.info(
            "Cog loading complete: %d/%d successful",
            loaded_count,
            len(FEATURE_COGS),
        )

        if failed_cogs:
            logger.warning(
                "Failed to load %d cogs: %s",
                len(failed_cogs),
                ", ".join(f"{name} ({error})" for name, error in failed_cogs),
            )

            # For now, we continue even if some cogs fail (graceful degradation)
            # In production, you might want to fail fast for critical cogs
            # raise RuntimeError(f"Failed to load {len(failed_cogs)} cogs")

    # ========================================================================
    # BOT EXECUTION
    # ========================================================================

    async def run_bot(self) -> None:
        """
        Run the Discord bot (blocks until bot stops).

        Requires initialize() to be called first.

        Raises:
            RuntimeError: If not initialized
        """
        if not self._initialized or self._bot is None:
            raise RuntimeError("Cannot run bot: ApplicationContext not initialized")

        logger.info("Starting Discord bot...")
        try:
            await self._bot.start(Config.DISCORD_TOKEN)
        except Exception as exc:
            logger.critical(
                "Bot execution failed",
                extra={
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise

    # ========================================================================
    # GRACEFUL SHUTDOWN (Reverse Order: Bot → Services → Database)
    # ========================================================================

    async def shutdown(self) -> None:
        """
        Gracefully shut down all services in reverse dependency order.

        Order:
            1. LumenBot.close()
            2. ServiceContainer.shutdown()
            3. DatabaseService.shutdown()
        """
        if not self._initialized:
            logger.warning("ApplicationContext not initialized, nothing to shut down")
            return

        logger.info("=" * 70)
        logger.info("APPLICATION CONTEXT SHUTDOWN")
        logger.info("=" * 70)

        # Step 1: Close bot
        if self._bot and not self._bot.is_closed():
            try:
                await self._bot.close()
                logger.info("✓ LumenBot closed")
            except Exception as exc:
                logger.error(
                    "Error closing bot",
                    extra={
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    },
                    exc_info=True,
                )

        # Step 2: Shutdown service container
        if self._service_container:
            try:
                await self._service_container.shutdown()
                logger.info("✓ ServiceContainer shut down")
            except Exception as exc:
                logger.error(
                    "Error shutting down service container",
                    extra={
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    },
                    exc_info=True,
                )

        # Step 3: Shutdown database service
        try:
            await DatabaseService.shutdown()
            logger.info("✓ DatabaseService shut down")
        except Exception as exc:
            logger.error(
                "Error shutting down database",
                extra={
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )

        self._initialized = False
        logger.info("=" * 70)
        logger.info("✓ Application context shutdown complete")
        logger.info("=" * 70)

    async def _emergency_shutdown(self) -> None:
        """
        Emergency shutdown - best-effort cleanup without raising exceptions.

        Used when initialization fails partway through.
        """
        logger.warning("Performing emergency shutdown")

        if self._bot and not self._bot.is_closed():
            try:
                await self._bot.close()
            except Exception:
                pass

        if self._service_container:
            try:
                await self._service_container.shutdown()
            except Exception:
                pass

        try:
            await DatabaseService.shutdown()
        except Exception:
            pass

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def bot(self) -> LumenBot:
        """Get the bot instance (only after initialization)."""
        if not self._initialized or self._bot is None:
            raise RuntimeError("Bot not available: ApplicationContext not initialized")
        return self._bot

    @property
    def config_manager(self) -> ConfigManager:
        """Get the config manager instance (only after initialization)."""
        if not self._initialized or self._config_manager is None:
            raise RuntimeError(
                "ConfigManager not available: ApplicationContext not initialized"
            )
        return self._config_manager

    @property
    def service_container(self) -> ServiceContainer:
        """Get the service container instance (only after initialization)."""
        if not self._initialized or self._service_container is None:
            raise RuntimeError(
                "ServiceContainer not available: ApplicationContext not initialized"
            )
        return self._service_container

    @property
    def is_initialized(self) -> bool:
        """Check if context is fully initialized."""
        return self._initialized