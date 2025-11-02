import asyncio
import sys

from src.core.config import Config
from src.core.logger import get_logger
from src.core.riki_bot import RIKIBot

logger = get_logger(__name__)


async def main():
    """RIKI RPG Entry Point."""
    try:
        Config.validate()
    except Exception as e:
        logger.critical(f"Configuration validation failed: {e}")
        sys.exit(1)

    bot = RIKIBot()

    try:
        logger.info("🚀 Starting RIKI RPG...")
        await bot.start(Config.DISCORD_TOKEN)
    except KeyboardInterrupt:
        logger.info("🛑 Manual shutdown via keyboard interrupt.")
    except Exception as e:
        logger.critical(f"Fatal startup error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        if not bot.is_closed():
            await bot.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot manually stopped.")
    except Exception as e:
        logger.critical(f"Startup failure: {e}", exc_info=True)
        sys.exit(1)
