"""
Lumen RPG - Application Entry Point
====================================

LES 2025 Compliant Bootstrap
-----------------------------
- Config validation
- Database initialization
- Event Bus (global singleton)
- ConfigManager initialization
- Service container initialization
- Bot lifecycle management
- Graceful shutdown
"""

import asyncio
import signal
import sys

from src.core.config.config import Config
from src.core.config.manager import ConfigManager
from src.core.logging.logger import get_logger
from src.core.database.service import DatabaseService
from src.core.event import event_bus                           
from src.core.services.container import (
    initialize_service_container,
    shutdown_service_container,
)
from src.bot.lumen_bot import LumenBot

logger = get_logger(__name__)


# ============================================================================
# Application Bootstrap
# ============================================================================

async def _startup() -> LumenBot:
    """Initialize all infrastructure components before launching the bot."""
    logger.info("========== LUMEN RPG INITIALIZATION START ==========")

    # Step 1: Validate configuration early
    try:
        Config.validate()
        logger.info("✓ Configuration validated")
    except Exception as exc:
        logger.critical(f"Configuration validation failed: {exc}")
        raise

    # Step 2: Initialize database service
    try:
        await DatabaseService.initialize()
        logger.info("✓ Database service initialized")
    except Exception as exc:
        logger.critical(f"Database initialization failed: {exc}", exc_info=True)
        raise

    # Step 3: Event bus 
    try:
        logger.info("✓ Event bus available")
    except Exception as exc:
        logger.critical(f"Event bus access failed: {exc}", exc_info=True)
        raise

    # Step 4: Initialize config manager
    try:
        config_manager = ConfigManager()
        await config_manager.initialize()
        logger.info("✓ Config manager initialized")
    except Exception as exc:
        logger.critical(f"Config manager initialization failed: {exc}", exc_info=True)
        raise

    # Step 5: Initialize service container
    try:
        container = initialize_service_container(
            config_manager=config_manager,
            event_bus=event_bus,        # <-- USE GLOBAL BUS
            logger=get_logger("src.core.services.container"),
        )
        await container.initialize()
        logger.info("✓ Service container initialized")
    except Exception as exc:
        logger.critical(f"Service container initialization failed: {exc}", exc_info=True)
        raise

    # Step 6: Initialize bot
    try:
        bot = LumenBot()
        logger.info("✓ Bot initialized")
    except Exception as exc:
        logger.critical(f"Bot initialization failed: {exc}", exc_info=True)
        raise

    logger.info("========== INFRASTRUCTURE INITIALIZED SUCCESSFULLY ==========")
    return bot


# ============================================================================
# Application Shutdown
# ============================================================================

async def _shutdown(bot: LumenBot | None) -> None:
    """Gracefully shut down the bot and infrastructure services."""
    logger.info("========== LUMEN RPG SHUTDOWN START ==========")

    # Step 1: Close bot if active
    if bot and not bot.is_closed():
        try:
            await bot.close()
            logger.info("✓ Bot closed")
        except Exception as exc:
            logger.error(f"Error while closing bot: {exc}", exc_info=True)

    # Step 2: Shutdown service container
    try:
        await shutdown_service_container()
        logger.info("✓ Service container shut down")
    except Exception as exc:
        logger.error(f"Service container shutdown error: {exc}", exc_info=True)

    # Step 3: Shutdown database
    try:
        await DatabaseService.shutdown()
        logger.info("✓ Database service shut down")
    except Exception as exc:
        logger.error(f"Database service shutdown error: {exc}", exc_info=True)

    logger.info("========== SHUTDOWN COMPLETE ==========")


# ============================================================================
# Application Entrypoint
# ============================================================================

async def main() -> None:
    """
    Lumen RPG Entry Point (LES 2025 Compliant).

    Lifecycle:
        1. Validate configuration
        2. Initialize infrastructure (DB, EventBus, ConfigManager, Services)
        3. Start bot
        4. Handle shutdown gracefully
    """
    bot: LumenBot | None = None

    try:
        bot = await _startup()

        logger.info("Starting Lumen RPG Discord bot...")
        await bot.start(Config.DISCORD_TOKEN)

    except asyncio.CancelledError:
        logger.warning("Asyncio task cancellation received; shutting down gracefully.")
        raise

    except KeyboardInterrupt:
        logger.info("Manual shutdown via keyboard interrupt.")

    except Exception as exc:
        logger.critical(f"Fatal startup error: {exc}", exc_info=True)
        sys.exit(1)

    finally:
        await _shutdown(bot)


# ============================================================================
# Process Startup
# ============================================================================

def _install_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    """
    Install signal handlers for graceful shutdown in production.
    """
    try:
        loop.add_signal_handler(signal.SIGTERM, loop.stop)
        logger.debug("SIGTERM handler installed")
    except NotImplementedError:
        logger.debug("SIGTERM not supported on this platform (likely Windows)")


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _install_signal_handlers(loop)

    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Bot manually stopped via keyboard interrupt.")
    except Exception as exc:
        logger.critical(f"Startup failure: {exc}", exc_info=True)
        sys.exit(1)
    finally:
        loop.close()
        logger.info("Event loop closed.")
