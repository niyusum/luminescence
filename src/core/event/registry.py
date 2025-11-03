"""
Centralized event listener registration for RIKI RPG Bot.

RIKI LAW Compliance:
- Wiring layer lives in core/ but can import from features/ (Article I)
- main.py is the only place that imports from both core and features (Article I)
- This module serves as the unified registration point for all event listeners

Architecture:
- Single source of truth for all EventBus listener registrations
- Called during bot startup from main.py
- Imports feature-specific registration functions
- Preserves separation between core infrastructure and feature logic

Usage:
    # In main.py during startup:
    from src.core.event.registry import register_all_event_listeners
    register_all_event_listeners(bot)
"""

from src.core.logging.logger import get_logger
from src.features.tutorial.listener import register_tutorial_listeners

logger = get_logger(__name__)


async def register_all_event_listeners(bot):
    """
    Register all feature event listeners with the EventBus.

    This is the centralized wiring function that connects all feature-specific
    event listeners to the EventBus. Each feature provides its own registration
    function that handles subscribing to relevant events.

    Args:
        bot: The RIKIBot instance, passed to listener registration functions
              that need access to Discord bot functionality

    Note:
        This function is called during bot startup from main.py.
        Add new feature listener registrations here as they are built.
    """
    logger.info("Registering event listeners...")

    # Tutorial event listeners
    await register_tutorial_listeners(bot)
    logger.debug("Tutorial listeners registered")

    # Add more feature listeners as they're built:
    # await register_achievement_listeners(bot)
    # await register_combat_listeners(bot)
    # await register_economy_listeners(bot)

    logger.info("Event listener registration complete")
