"""
Drop Cog - Discord commands for drop system
============================================

Commands:
- Execute drop command (spend charge, earn auric coin)
- Check drop charge status
- View drop history and statistics
"""

from discord.ext import commands


class DropCog(commands.Cog):
    """Drop command and charge management."""

    def __init__(self, bot):
        self.bot = bot

    # Commands will be implemented here


async def setup(bot):
    """Load the DropCog."""
    await bot.add_cog(DropCog(bot))
