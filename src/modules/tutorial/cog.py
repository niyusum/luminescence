"""
Tutorial Cog - Discord commands and listeners for tutorial
===========================================================

Commands:
- View tutorial progress
- Skip tutorial
- Get hints

Event Listeners:
- Auto-advance tutorial based on player actions
"""

from discord.ext import commands


class TutorialCog(commands.Cog):
    """Tutorial progression commands and listeners."""

    def __init__(self, bot):
        self.bot = bot

    # Commands and listeners will be implemented here


async def setup(bot):
    """Load the TutorialCog."""
    await bot.add_cog(TutorialCog(bot))
