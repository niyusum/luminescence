import asyncio
import pkgutil
from pathlib import Path
from src.core.logger import get_logger

logger = get_logger(__name__)


async def load_all_features(bot):
    """
    Dynamically discover and load all feature cogs from src/features.
    
    Scans recursively for *_cog.py files.
    This makes the bot fully modular — new features are loaded automatically
    on startup with no manual registration.
    
    RIKI LAW:
        • Dynamic discovery (Article I.8)
        • Service modularity (Article I.2)
        • No hard-coded paths
    """
    base_path = Path(__file__).parent.parent / "features"
    base_pkg = "features"
    tasks = []

    for _, name, ispkg in pkgutil.walk_packages([str(base_path)], prefix=f"{base_pkg}."):
        if name.endswith("_cog"):
            tasks.append(_safe_load(bot, name))

    if not tasks:
        logger.warning("No *_cog.py files found in src/features/")
        return

    results = await asyncio.gather(*tasks, return_exceptions=True)
    loaded = sum(1 for r in results if not isinstance(r, Exception))
    failed = len(results) - loaded
    logger.info(f"✓ Loaded {loaded} feature cogs ({failed} failed)")


async def _safe_load(bot, extension_name: str):
    try:
        await bot.load_extension(extension_name)
        logger.info(f"✓ Loaded {extension_name}")
    except Exception as e:
        logger.error(f"✗ Failed to load {extension_name}: {e}", exc_info=True)
        return e
