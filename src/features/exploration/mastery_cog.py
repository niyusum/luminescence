"""
Exploration Mastery system Discord interface.

Displays sector completion ranks, relic bonuses, and progression tracking.

RIKI LAW Compliance:
    - Article VI: Discord UI layer only
    - Article VII: All logic delegated to MasteryService
    - Article I.5: Specific exception handling with embeds
"""

import discord
from discord.ext import commands
from typing import Optional

from src.core.infra.database_service import DatabaseService
from src.features.player.service import PlayerService
from src.features.exploration.mastery_service import MasteryService
from src.features.exploration.constants import RELIC_TYPES
from src.core.exceptions import InvalidOperationError
from src.core.logging.logger import get_logger
from src.utils.decorators import ratelimit
from src.utils.embed_builder import EmbedBuilder

logger = get_logger(__name__)


class MasteryCog(commands.Cog):
    """
    Exploration mastery progression tracking and relic management.

    Commands:
        /mastery - View all sector mastery ranks and active relics
        /mastery sector <sector_id> - View specific sector mastery details
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_group(
        name="mastery",
        description="View exploration mastery ranks and relic bonuses",
        fallback="overview"
    )
    @ratelimit(uses=10, per_seconds=60, command_name="mastery")
    async def mastery(self, ctx: commands.Context):
        """View mastery overview with all active relics."""
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

                # Get all active relics
                relics = await MasteryService.get_player_relics(session, player.discord_id)

                # Get active bonuses
                bonuses = await MasteryService.get_active_bonuses(session, player.discord_id)

                # Build embed
                embed = discord.Embed(
                    title=f"🏆 {ctx.author.display_name}'s Mastery",
                    description=(
                        "Complete exploration sectors to earn permanent relic bonuses.\n"
                        "Each sector has 3 mastery ranks with increasing rewards."
                    ),
                    color=0x9B59B6,  # Purple
                    timestamp=discord.utils.utcnow()
                )

                # Show total relics
                embed.add_field(
                    name="📦 Total Relics",
                    value=f"**{len(relics)}** active relics",
                    inline=True
                )

                # Show active bonuses summary
                if bonuses:
                    bonus_text = []
                    for relic_type, value in bonuses.items():
                        relic_info = RELIC_TYPES.get(relic_type, {})
                        icon = relic_info.get("icon", "🏆")
                        name = relic_info.get("name", relic_type)

                        if relic_type in ["energy_regen", "stamina_regen", "hp_boost"]:
                            bonus_text.append(f"{icon} **{name}:** +{value:,.0f}")
                        else:
                            bonus_text.append(f"{icon} **{name}:** +{value:.1f}%")

                    embed.add_field(
                        name="✨ Active Bonuses",
                        value="\n".join(bonus_text) if bonus_text else "No active bonuses",
                        inline=False
                    )
                else:
                    embed.add_field(
                        name="✨ Active Bonuses",
                        value="No active relics yet. Complete sectors to earn bonuses!",
                        inline=False
                    )

                # Show sector completion status (simplified)
                sector_status = []
                for sector_id in range(1, 7):
                    status = await MasteryService.get_sector_mastery_status(
                        session, player.discord_id, sector_id
                    )
                    rank = status["current_rank"]
                    stars = "★" * rank + "☆" * (3 - rank)
                    sector_status.append(f"Sector {sector_id}: {stars}")

                embed.add_field(
                    name="🗺️ Sector Progress",
                    value="\n".join(sector_status),
                    inline=False
                )

                embed.set_footer(
                    text="Use /mastery sector <id> to view detailed sector mastery"
                )

                await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Mastery overview error for {ctx.author.id}: {e}", exc_info=True)
            embed = EmbedBuilder.error(
                title="Error",
                description="Failed to load mastery data."
            )
            await ctx.send(embed=embed, ephemeral=True)

    @mastery.command(
        name="sector",
        description="View detailed mastery for a specific sector"
    )
    @ratelimit(uses=10, per_seconds=60, command_name="mastery_sector")
    async def mastery_sector(
        self,
        ctx: commands.Context,
        sector_id: int
    ):
        """View detailed mastery information for specific sector."""
        await ctx.defer()

        # Validate sector
        if sector_id < 1 or sector_id > 6:
            embed = EmbedBuilder.error(
                title="Invalid Sector",
                description="Sector must be between 1 and 6.",
                help_text="Example: `/mastery sector 1`"
            )
            await ctx.send(embed=embed, ephemeral=True)
            return

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

                # Get sector mastery status
                status = await MasteryService.get_sector_mastery_status(
                    session, player.discord_id, sector_id
                )

                # Build embed
                embed = discord.Embed(
                    title=f"🗺️ Sector {sector_id} Mastery",
                    description=f"Complete all 9 sublevels to unlock mastery ranks.",
                    color=0x9B59B6,  # Purple
                    timestamp=discord.utils.utcnow()
                )

                # Current rank
                current_rank = status["current_rank"]
                next_rank = status.get("next_rank")

                if status["fully_mastered"]:
                    embed.add_field(
                        name="🏆 Status",
                        value="**Fully Mastered!** ★★★",
                        inline=False
                    )
                elif current_rank == 0:
                    embed.add_field(
                        name="📊 Status",
                        value=f"Not started. Complete sector to earn Rank 1!",
                        inline=False
                    )
                else:
                    embed.add_field(
                        name="📊 Status",
                        value=f"Rank {current_rank}/3 ★{'★' * current_rank}{'☆' * (3 - current_rank)}\nNext: Rank {next_rank}",
                        inline=False
                    )

                # Show each rank status
                for rank_num in range(1, 4):
                    rank_key = f"rank_{rank_num}"
                    rank_data = status["ranks"][rank_key]

                    if rank_data["complete"]:
                        completed_at = rank_data["completed_at"]
                        timestamp = f"<t:{int(completed_at.timestamp())}:R>" if completed_at else "Unknown"
                        embed.add_field(
                            name=f"✅ Rank {rank_num}",
                            value=f"Completed {timestamp}",
                            inline=True
                        )
                    else:
                        embed.add_field(
                            name=f"🔒 Rank {rank_num}",
                            value="Not unlocked",
                            inline=True
                        )

                embed.set_footer(
                    text="Complete sectors multiple times to unlock higher ranks"
                )

                await ctx.send(embed=embed)

        except InvalidOperationError as e:
            embed = EmbedBuilder.error(
                title="Invalid Sector",
                description=str(e)
            )
            await ctx.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(
                f"Mastery sector error for {ctx.author.id} sector {sector_id}: {e}",
                exc_info=True
            )
            embed = EmbedBuilder.error(
                title="Error",
                description="Failed to load sector mastery data."
            )
            await ctx.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    """Required for dynamic cog loading."""
    await bot.add_cog(MasteryCog(bot))
