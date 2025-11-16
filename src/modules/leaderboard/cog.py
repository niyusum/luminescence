"""
Leaderboard Cog - Discord commands for leaderboards
====================================================

Commands:
- View leaderboards by category
- Check personal rank
- View rank changes
"""

from discord.ext import commands


class LeaderboardCog(commands.Cog):
    """Leaderboard commands."""

    def __init__(self, bot):
        self.bot = bot

    # Commands will be implemented here


async def setup(bot):
    """Load the LeaderboardCog."""
    await bot.add_cog(LeaderboardCog(bot))
