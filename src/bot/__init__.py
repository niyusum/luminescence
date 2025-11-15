"""
Bot infrastructure and Discord.py integration.

Contains the main bot class, base cog utilities, cog loader, and lifecycle management.
"""

from src.bot.lifecycle import (
    BotLifecycle,
    BotMetrics,
    ServiceHealth,
    StartupMetrics,
)
from src.bot.lumen_bot import LumenBot

__all__ = [
    # Main bot
    "LumenBot",
    # Lifecycle management
    "BotLifecycle",
    "BotMetrics",
    "ServiceHealth",
    "StartupMetrics",
]
