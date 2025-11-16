"""
Exploration Cog - Discord commands for exploration
===================================================

Commands:
- Sector exploration
- Progress tracking
- Mastery rank progression
- Miniboss battles
"""

from discord.ext import commands


class ExplorationCog(commands.Cog):
    """Exploration and mastery commands."""

    def __init__(self, bot):
        self.bot = bot

    # Commands will be implemented here


async def setup(bot):
    """Load the ExplorationCog."""
    await bot.add_cog(ExplorationCog(bot))
