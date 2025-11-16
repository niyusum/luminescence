"""
Economy Cog - Discord commands for economy management
======================================================

Commands:
- View transaction history
- Economy statistics
- Admin economy tools
"""

from discord.ext import commands


class EconomyCog(commands.Cog):
    """Economy management commands."""

    def __init__(self, bot):
        self.bot = bot

    # Commands will be implemented here


async def setup(bot):
    """Load the EconomyCog."""
    await bot.add_cog(EconomyCog(bot))
