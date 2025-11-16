"""
Shrine Cog - Discord commands for player shrines
=================================================

Commands:
- View shrine status
- Collect shrine yields
- Upgrade shrines
- Activate/deactivate shrines
"""

from discord.ext import commands


class ShrineCog(commands.Cog):
    """Player shrine commands."""

    def __init__(self, bot):
        self.bot = bot

    # Commands will be implemented here


async def setup(bot):
    """Load the ShrineCog."""
    await bot.add_cog(ShrineCog(bot))
