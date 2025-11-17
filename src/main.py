"""
Lumen RPG - Application Entry Point (LES 2025)
===============================================

Purpose
-------
Minimal bootstrap entrypoint that:
- Validates configuration
- Initializes database infrastructure
- Creates and runs ApplicationContext (Kernel)
- Handles graceful shutdown

Responsibilities
----------------
- Early config validation
- Database initialization
- Event loop setup
- Signal handler installation
- ApplicationContext orchestration
- Graceful and emergency shutdown

Non-Responsibilities
--------------------
- Service initialization (delegated to ApplicationContext)
- Bot lifecycle (delegated to LumenBot via ApplicationContext)
- Dependency injection (delegated to ApplicationContext)
- Business logic (delegated to domain services)

Lumen 2025 Compliance
---------------------
- Clean separation: infra bootstrap only
- ApplicationContext handles all DI and lifecycle
- Structured logging throughout
- Fail-fast on critical errors
- Cross-platform signal handling
"""

import asyncio
import signal
import sys

from src.core.config.config import Config
from src.core.database.service import DatabaseService
from src.core.infra.application_context import ApplicationContext
from src.core.logging.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# Application Bootstrap
# ============================================================================

async def main() -> None:
    """
    Lumen RPG application entry point.

    Lifecycle:
        1. Validate configuration
        2. Initialize database infrastructure
        3. Create and initialize ApplicationContext
        4. Run bot (blocks until shutdown)
        5. Graceful shutdown via ApplicationContext
    """
    context: ApplicationContext | None = None

    try:
        logger.info("========== LUMEN RPG STARTUP ==========")

        # Step 1: Validate configuration
        try:
            Config.validate()
            logger.info("✓ Configuration validated")
        except Exception as exc:
            logger.critical(
                "Configuration validation failed",
                extra={"error": str(exc)},
                exc_info=True,
            )
            raise

        # Step 2: Initialize database infrastructure
        try:
            await DatabaseService.initialize()
            logger.info("✓ Database infrastructure initialized")
        except Exception as exc:
            logger.critical(
                "Database initialization failed",
                extra={"error": str(exc)},
                exc_info=True,
            )
            raise

        # Step 3: Create and initialize ApplicationContext (Kernel)
        try:
            context = ApplicationContext()
            await context.initialize()
            logger.info("✓ Application context initialized")
        except Exception as exc:
            logger.critical(
                "Application context initialization failed",
                extra={"error": str(exc)},
                exc_info=True,
            )
            raise

        # Step 4: Run bot (blocks until bot stops)
        logger.info("========== BOT STARTING ==========")
        await context.run_bot()

    except asyncio.CancelledError:
        logger.warning("Asyncio task cancelled, shutting down gracefully")
        raise

    except KeyboardInterrupt:
        logger.info("Manual shutdown via keyboard interrupt")

    except Exception as exc:
        logger.critical(
            "Fatal application error",
            extra={"error": str(exc), "error_type": type(exc).__name__},
            exc_info=True,
        )
        sys.exit(1)

    finally:
        # Step 5: Graceful shutdown
        if context:
            try:
                await context.shutdown()
            except Exception as exc:
                logger.error(
                    "Error during shutdown",
                    extra={"error": str(exc)},
                    exc_info=True,
                )

        logger.info("========== LUMEN RPG SHUTDOWN COMPLETE ==========")


# ============================================================================
# Signal Handling
# ============================================================================

def _install_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    """
    Install signal handlers for graceful shutdown.

    Handles:
        - SIGTERM (production deployments)
        - SIGINT (handled by KeyboardInterrupt)
    """
    try:
        loop.add_signal_handler(signal.SIGTERM, loop.stop)
        logger.debug("✓ SIGTERM handler installed")
    except NotImplementedError:
        # Windows doesn't support add_signal_handler
        logger.debug("Signal handlers not supported on this platform (Windows)")


# ============================================================================
# Process Entry Point
# ============================================================================

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _install_signal_handlers(loop)

    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Shutdown via keyboard interrupt")
    except Exception as exc:
        logger.critical(
            "Application startup failure",
            extra={"error": str(exc)},
            exc_info=True,
        )
        sys.exit(1)
    finally:
        loop.close()
        logger.info("Event loop closed")