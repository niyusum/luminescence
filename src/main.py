import asyncio
import signal
import sys

from src.core.config.config import Config
from src.core.logging.logger import get_logger
from src.core.database.service import DatabaseService
from src.bot.lumen_bot import LumenBot

logger = get_logger(__name__)


# ============================================================================
# Application Bootstrap
# ============================================================================

async def _startup() -> LumenBot:
    """Initialize all infrastructure components before launching the bot."""
    logger.info("Initializing Lumen RPG infrastructure...")

    # Validate configuration early
    try:
        Config.validate()
    except Exception as exc:
        logger.critical(f"Configuration validation failed: {exc}")
        raise

    # Initialize database service
    try:
        await DatabaseService.initialize()
    except Exception as exc:
        logger.critical(f"Database initialization failed: {exc}", exc_info=True)
        raise

    bot = LumenBot()

    logger.info("Infrastructure initialized successfully.")
    return bot


async def _shutdown(bot: LumenBot | None) -> None:
    """Gracefully shut down the bot and infrastructure services."""
    logger.info("Shutting down Lumen RPG...")

    # Close bot if active
    if bot and not bot.is_closed():
        try:
            await bot.close()
        except Exception as exc:
            logger.error(f"Error while closing bot: {exc}", exc_info=True)

    # Shutdown database
    try:
        await DatabaseService.shutdown()
    except Exception as exc:
        logger.error(f"DatabaseService shutdown error: {exc}", exc_info=True)

    logger.info("Shutdown complete.")


# ============================================================================
# Application Entrypoint
# ============================================================================

async def main() -> None:
    """Lumen RPG Entry Point (LES 2025 Compliant)."""
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
    """Install a SIGTERM handler for graceful shutdown in production."""
    try:
        loop.add_signal_handler(signal.SIGTERM, loop.stop)
    except NotImplementedError:
        # Windows platforms may not support SIGTERM
        logger.debug("SIGTERM handler not supported on this platform.")


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _install_signal_handlers(loop)

    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Bot manually stopped.")
    except Exception as exc:
        logger.critical(f"Startup failure: {exc}", exc_info=True)
        sys.exit(1)
    finally:
        loop.close()


