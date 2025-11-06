from src.core.bot.base_cog import BaseCog
"""
Leaderboard ranking system Discord interface.

Displays global and player-specific rankings across multiple categories.

RIKI LAW Compliance:
    - Article VI: Discord UI layer only
    - Article VII: All logic delegated to LeaderboardService
    - Article I.5: Specific exception handling with embeds
"""

import discord
from discord.ext import commands
from typing import Optional

from src.core.infra.database_service import DatabaseService
from src.features.player.service import PlayerService
from src.features.leaderboard.service import LeaderboardService
from src.core.exceptions import InvalidOperationError
from src.core.logging.logger import get_logger
from src.utils.decorators import ratelimit
from src.utils.embed_builder import EmbedBuilder

logger = get_logger(__name__)


class LeaderboardCog(BaseCog):
    """
    Global leaderboard rankings and player stats.

    Commands:
        /top - View all leaderboard categories
        /top power - Top players by total power
        /top level - Top players by level
        /top ascension - Top players by highest floor
        /top fusions - Top players by total fusions
        /top wealth - Top players by rikis

    Prefix aliases: rt, rtop, riki top
    """

    def __init__(self, bot: commands.Bot):
        super().__init__(bot, self.__class__.__name__)
        self.bot = bot

    @commands.hybrid_group(
        name="top",
        aliases=["rt", "rtop", "leaderboard"],
        description="View global leaderboards and rankings",
        fallback="menu"
    )
    @ratelimit(uses=10, per_seconds=60, command_name="top")
    async def top(self, ctx: commands.Context):
        """Show leaderboard category menu with interactive selector."""
        await ctx.defer()

        embed = discord.Embed(
            title="🏆 Leaderboards",
            description="Choose a category to view rankings:",
            color=0xFFD700,  # Gold
            timestamp=discord.utils.utcnow()
        )

        # Show all available categories
        for category_key, category_info in LeaderboardService.CATEGORIES.items():
            icon = category_info["icon"]
            name = category_info["name"]
            embed.add_field(
                name=f"{icon} {name}",
                value=f"`/top {category_key}`",
                inline=True
            )

        embed.set_footer(
            text="Leaderboards update every 10 minutes • Use dropdown to view"
        )

        # Add interactive category selector
        view = LeaderboardCategoryView(ctx.author.id, self)
        await ctx.send(embed=embed, view=view)

    @top.command(
        name="power",
        aliases=["total_power"],
        description="Top players by total power"
    )
    @ratelimit(uses=10, per_seconds=60, command_name="top_power")
    async def top_power(self, ctx: commands.Context, page: int = 1):
        """View total power rankings."""
        await self._show_leaderboard(ctx, "total_power", page)

    @top.command(
        name="level",
        description="Top players by level"
    )
    @ratelimit(uses=10, per_seconds=60, command_name="top_level")
    async def top_level(self, ctx: commands.Context, page: int = 1):
        """View level rankings."""
        await self._show_leaderboard(ctx, "level", page)

    @top.command(
        name="ascension",
        aliases=["floor", "highest_floor"],
        description="Top players by ascension floor"
    )
    @ratelimit(uses=10, per_seconds=60, command_name="top_ascension")
    async def top_ascension(self, ctx: commands.Context, page: int = 1):
        """View ascension floor rankings."""
        await self._show_leaderboard(ctx, "highest_floor", page)

    @top.command(
        name="fusions",
        aliases=["total_fusions"],
        description="Top players by fusion count"
    )
    @ratelimit(uses=10, per_seconds=60, command_name="top_fusions")
    async def top_fusions(self, ctx: commands.Context, page: int = 1):
        """View fusion count rankings."""
        await self._show_leaderboard(ctx, "total_fusions", page)

    @top.command(
        name="wealth",
        aliases=["rikis", "rich"],
        description="Top players by rikis"
    )
    @ratelimit(uses=10, per_seconds=60, command_name="top_wealth")
    async def top_wealth(self, ctx: commands.Context, page: int = 1):
        """View wealth rankings."""
        await self._show_leaderboard(ctx, "rikis", page)

    @top.command(
        name="me",
        aliases=["rank", "myrank"],
        description="View your rankings across all categories"
    )
    @ratelimit(uses=10, per_seconds=60, command_name="top_me")
    async def top_me(self, ctx: commands.Context):
        """View player's rankings in all categories."""
        await ctx.defer()

        try:
            async with DatabaseService.get_session() as session:
                # Get player
                player = await PlayerService.get_player(session, ctx.author.id)
                if not player:
                    embed = EmbedBuilder.error(
                        title="Not Registered",
                        description="You need to register first!",
                        help_text="Use `/register` to start your journey."
                    )
                    await ctx.send(embed=embed, ephemeral=True)
                    return

                embed = discord.Embed(
                    title=f"🏆 {ctx.author.display_name}'s Rankings",
                    description="Your position across all leaderboards:",
                    color=0xFFD700,  # Gold
                    timestamp=discord.utils.utcnow()
                )

                # Get ranks for all categories
                for category_key, category_info in LeaderboardService.CATEGORIES.items():
                    icon = category_info["icon"]
                    name = category_info["name"]
                    value_format = category_info["format"]

                    # Try cached first, fallback to real-time
                    rank_data = await LeaderboardService.get_cached_rank(
                        session, player.discord_id, category_key
                    )

                    if not rank_data:
                        # Fallback to real-time
                        try:
                            rank_data = await LeaderboardService.get_realtime_rank(
                                session, player.discord_id, category_key
                            )
                        except Exception as e:
                            logger.warning(f"Failed to get rank for {category_key}: {e}")
                            continue

                    rank = rank_data["rank"]
                    value = rank_data["value"]

                    # Format rank display
                    if rank == 1:
                        rank_display = "🥇 #1"
                    elif rank == 2:
                        rank_display = "🥈 #2"
                    elif rank == 3:
                        rank_display = "🥉 #3"
                    else:
                        rank_display = f"#{rank:,}"

                    # Format value
                    value_display = value_format.format(value)

                    embed.add_field(
                        name=f"{icon} {name}",
                        value=f"{rank_display}\n{value_display}",
                        inline=True
                    )

                embed.set_thumbnail(url=ctx.author.display_avatar.url)
                embed.set_footer(
                    text="Rankings update every 10 minutes"
                )

                await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Leaderboard me error for {ctx.author.id}: {e}", exc_info=True)
            embed = EmbedBuilder.error(
                title="Error",
                description="Failed to load your rankings."
            )
            await ctx.send(embed=embed, ephemeral=True)

    # ========================================================================
    # HELPER METHODS
    # ========================================================================

    async def _show_leaderboard(
        self,
        ctx: commands.Context,
        category: str,
        page: int = 1
    ):
        """
        Generic leaderboard display method.

        Args:
            ctx: Command context
            category: Leaderboard category
            page: Page number (1-indexed)
        """
        await ctx.defer()

        # Validate page
        if page < 1:
            page = 1

        per_page = 10
        offset = (page - 1) * per_page

        try:
            async with DatabaseService.get_session() as session:
                category_info = LeaderboardService.CATEGORIES[category]
                icon = category_info["icon"]
                name = category_info["name"]
                value_format = category_info["format"]

                # Get cached leaderboard
                all_rankings = await LeaderboardService.get_cached_leaderboard(
                    session, category, limit=100
                )

                if not all_rankings:
                    # Fallback to real-time
                    all_rankings = await LeaderboardService.get_top_players(
                        session, category, limit=100
                    )

                # Paginate
                page_rankings = all_rankings[offset:offset + per_page]

                if not page_rankings:
                    embed = EmbedBuilder.error(
                        title="No Data",
                        description=f"Page {page} has no rankings.",
                        help_text="Try a lower page number."
                    )
                    await ctx.send(embed=embed, ephemeral=True)
                    return

                # Build embed
                embed = discord.Embed(
                    title=f"{icon} {name} Leaderboard",
                    description=f"Top players (Page {page})",
                    color=0xFFD700,  # Gold
                    timestamp=discord.utils.utcnow()
                )

                # Format rankings
                lines = []
                for entry in page_rankings:
                    rank = entry["rank"]
                    username = entry["username"][:20]  # Truncate long names
                    value = entry["value"]

                    # Rank display
                    if rank == 1:
                        rank_display = "🥇"
                    elif rank == 2:
                        rank_display = "🥈"
                    elif rank == 3:
                        rank_display = "🥉"
                    else:
                        rank_display = f"`#{rank:2}`"

                    # Value display
                    value_display = value_format.format(value)

                    lines.append(f"{rank_display} **{username}** — {value_display}")

                embed.description = "\n".join(lines)

                # Check if player is on current page
                player = await PlayerService.get_player(session, ctx.author.id)
                if player:
                    player_rank_data = await LeaderboardService.get_cached_rank(
                        session, player.discord_id, category
                    )
                    if player_rank_data:
                        player_rank = player_rank_data["rank"]
                        if offset < player_rank <= offset + per_page:
                            embed.set_footer(
                                text=f"You're on this page! • Rank #{player_rank:,}"
                            )
                        else:
                            embed.set_footer(
                                text=f"Your rank: #{player_rank:,} • Page {(player_rank - 1) // per_page + 1}"
                            )

                await ctx.send(embed=embed)

        except Exception as e:
            logger.error(
                f"Leaderboard display error for {category} page {page}: {e}",
                exc_info=True
            )
            embed = EmbedBuilder.error(
                title="Error",
                description="Failed to load leaderboard data."
            )
            await ctx.send(embed=embed, ephemeral=True)


class LeaderboardCategoryView(discord.ui.View):
    """Interactive dropdown for selecting leaderboard categories."""

    def __init__(self, user_id: int, cog: LeaderboardCog):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.cog = cog

        # Create dropdown options
        options = []
        for category_key, category_info in LeaderboardService.CATEGORIES.items():
            options.append(discord.SelectOption(
                label=category_info["name"],
                value=category_key,
                description=f"View {category_info['name'].lower()} rankings",
                emoji=category_info["icon"]
            ))

        self.select = discord.ui.Select(
            placeholder="Select a leaderboard category...",
            options=options,
            custom_id="leaderboard_category_select"
        )
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: discord.Interaction):
        """Handle category selection."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This dropdown isn't for you!",
                ephemeral=True
            )
            return

        category = self.select.values[0]

        # Create a mock context for the leaderboard display
        await interaction.response.defer(ephemeral=True)

        try:
            # Show the leaderboard in a new ephemeral message
            async with DatabaseService.get_session() as session:
                category_info = LeaderboardService.CATEGORIES[category]
                icon = category_info["icon"]
                name = category_info["name"]
                value_format = category_info["format"]

                # Get cached leaderboard
                all_rankings = await LeaderboardService.get_cached_leaderboard(
                    session, category, limit=10
                )

                if not all_rankings:
                    # Fallback to real-time
                    all_rankings = await LeaderboardService.get_top_players(
                        session, category, limit=10
                    )

                if not all_rankings:
                    embed = EmbedBuilder.warning(
                        title="No Data",
                        description=f"No rankings available for {name}."
                    )
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return

                # Build embed
                embed = discord.Embed(
                    title=f"{icon} {name} Leaderboard",
                    description="Top 10 players",
                    color=0xFFD700,
                    timestamp=discord.utils.utcnow()
                )

                # Format rankings
                lines = []
                for entry in all_rankings[:10]:
                    rank = entry["rank"]
                    username = entry["username"][:20]
                    value = entry["value"]

                    # Rank display
                    if rank == 1:
                        rank_display = "🥇"
                    elif rank == 2:
                        rank_display = "🥈"
                    elif rank == 3:
                        rank_display = "🥉"
                    else:
                        rank_display = f"`#{rank:2}`"

                    value_display = value_format.format(value)
                    lines.append(f"{rank_display} **{username}** — {value_display}")

                embed.description = "\n".join(lines)

                # Check player's rank
                player = await PlayerService.get_player(session, self.user_id)
                if player:
                    player_rank_data = await LeaderboardService.get_cached_rank(
                        session, player.discord_id, category
                    )
                    if player_rank_data:
                        player_rank = player_rank_data["rank"]
                        embed.set_footer(
                            text=f"Your rank: #{player_rank:,} • Use /top {category} for full view"
                        )
                    else:
                        embed.set_footer(
                            text=f"Use /top {category} for full view"
                        )

                await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Leaderboard dropdown error for {category}: {e}", exc_info=True)
            embed = EmbedBuilder.error(
                title="Error",
                description="Failed to load leaderboard data."
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

    async def on_timeout(self):
        """Disable dropdown on timeout."""
        self.select.disabled = True


async def setup(bot: commands.Bot):
    """Required for dynamic cog loading."""
    await bot.add_cog(LeaderboardCog(bot))
