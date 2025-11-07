"""
Daily rewards system.

Handles the claim of daily rewards, applying streak bonuses, leader/class
modifiers, and ensuring atomic state changes via pessimistic locking.

RIKI LAW Compliance:
    - Article I.1: SELECT FOR UPDATE (Pessimistic Locking) for state mutation
    - Article I.9: Command latency metrics for observability
    - Article II: Structured Transaction and Error logging with full context
    - Article I.5: Specific exception handling (CooldownError)
    - Article I.7: All business logic delegated to DailyService
"""

from src.core.bot.base_cog import BaseCog
import discord
from discord.ext import commands
from typing import Optional
import time

from src.core.infra.database_service import DatabaseService
from src.features.player.service import PlayerService
from src.features.daily.service import DailyService
from src.core.infra.transaction_logger import TransactionLogger
from src.core.event.event_bus import EventBus
from src.core.config.config_manager import ConfigManager
from src.core.exceptions import CooldownError
from src.core.logging.logger import get_logger, LogContext
from src.utils.decorators import ratelimit
from utils.embed_builder import EmbedBuilder

logger = get_logger(__name__)


class DailyCog(BaseCog):
    """
    Daily rewards system.

    Commands:
        /daily (rd) - Claim daily rewards.
    """

    def __init__(self, bot: commands.Bot):
        super().__init__(bot, self.__class__.__name__)
        self.bot = bot

    @commands.command(
        name="daily",
        aliases=["rd", "rdaily", "rikidaily"],
        description="Claim your daily rewards",
    )
    @ratelimit(
        uses=ConfigManager.get("rate_limits.daily.claim.uses", 5),
        per_seconds=ConfigManager.get("rate_limits.daily.claim.period", 60),
        command_name="daily"
    )
    async def daily(self, ctx: commands.Context):
        """Claim daily rewards."""
        # RIKI LAW Article I.9 - Latency Metric Start
        start_time = time.perf_counter()
        await ctx.defer()

        try:
            async with DatabaseService.get_transaction() as session:
                # RIKI LAW Article I.1: Pessimistic locking for state mutation
                player = await PlayerService.get_player_with_regen(
                    session, ctx.author.id, lock=True
                )

                if not player:
                    embed = EmbedBuilder.error(
                        title="Not Registered",
                        description="You need to register first!",
                        help_text="Use `/register` to create your account.",
                    )
                    await ctx.send(embed=embed, ephemeral=True)
                    return

                # RIKI LAW Article I.7: All business logic delegated to service
                result = await DailyService.claim_daily(session, player)

                # RIKI LAW Article II: Transaction logging
                await TransactionLogger.log_transaction(
                    session=session,
                    player_id=ctx.author.id,
                    transaction_type="daily_claimed",
                    details={
                        "rikis_gained": result["rikis_gained"],
                        "grace_gained": result["grace_gained"],
                        "streak": result["streak"],
                        "bonus_applied": result.get("bonus_applied", False),
                        "modifiers_applied": result.get("modifiers_applied", {}),
                    },
                    context=f"command:/{ctx.command.name} guild:{ctx.guild.id if ctx.guild else 'DM'}",
                )

                await EventBus.publish(
                    "daily_claimed",
                    {
                        "player_id": ctx.author.id,
                        "streak": result["streak"],
                        "timestamp": discord.utils.utcnow(),
                    },
                )

            # --- Embed Construction ---
            embed = EmbedBuilder.success(
                title="🎁 Daily Rewards Claimed!",
                description=(
                    f"You've successfully claimed your daily rewards!\n\n"
                    f"**Day {result['streak']} Streak** 🔥"
                ),
                footer="Come back tomorrow for more rewards!",
            )

            embed.add_field(
                name="💰 Rewards Received",
                value=f"**+{result['rikis_gained']:,}** Rikis\n**+{result['grace_gained']}** Grace",
                inline=True,
            )

            if result.get("bonus_applied"):
                embed.add_field(
                    name="🎉 Streak Bonus",
                    value=f"**+{result.get('bonus_amount', 0):,}** extra rikis!\nKeep your streak going!",
                    inline=True,
                )

            # Display applied modifiers (leader/class bonuses)
            modifiers = result.get("modifiers_applied", {})
            income_boost = modifiers.get("income_boost", 1.0)
            xp_boost = modifiers.get("xp_boost", 1.0)

            if income_boost > 1.0 or xp_boost > 1.0:
                lines = []
                if income_boost > 1.0:
                    lines.append(f"💰 **Income Boost:** +{(income_boost - 1.0) * 100:.0f}%")
                if xp_boost > 1.0:
                    lines.append(f"📈 **XP Boost:** +{(xp_boost - 1.0) * 100:.0f}%")
                embed.add_field(
                    name="✨ Modifier Bonus",
                    value="\n".join(lines),
                    inline=False,
                )

            embed.add_field(
                name="⏰ Next Daily",
                value="Available in 24 hours\nDon't break your streak!",
                inline=False,
            )

            await ctx.send(embed=embed)

            # RIKI LAW Article I.9 - Latency Metric Logging (Success)
            latency = (time.perf_counter() - start_time) * 1000
            self.log_command_use(
                "daily",
                ctx.author.id,
                guild_id=ctx.guild.id if ctx.guild else None,
                latency_ms=round(latency, 2)
            )

        except CooldownError as e:
            # RIKI LAW Article I.5: Specific exception handled
            hours = int(e.remaining_seconds // 3600)
            minutes = int((e.remaining_seconds % 3600) // 60)

            embed = EmbedBuilder.warning(
                title="Daily Rewards On Cooldown",
                description=(
                    f"You've already claimed your daily rewards!\n\n"
                    f"⏰ **Next claim in:** {hours}h {minutes}m"
                ),
                footer="Daily rewards reset every 24 hours",
            )

            embed.add_field(
                name="💡 While You Wait",
                value=(
                    "• Use `/pray` to gain grace\n"
                    "• Use `/summon` to get maidens\n"
                    "• Try `/fusion` to upgrade your collection"
                ),
                inline=False,
            )

            await ctx.send(embed=embed, ephemeral=True)

            # RIKI LAW Article I.9 - Latency Metric Logging (Cooldown)
            latency = (time.perf_counter() - start_time) * 1000
            self.log_command_use(
                "daily",
                ctx.author.id,
                guild_id=ctx.guild.id if ctx.guild else None,
                latency_ms=round(latency, 2),
                status="cooldown"
            )


        except Exception as e:
            # RIKI LAW Article II: Structured Error Logging
            latency = (time.perf_counter() - start_time) * 1000
            self.log_cog_error(
                "daily",
                e,
                user_id=ctx.author.id,
                guild_id=ctx.guild.id if ctx.guild else None,
                latency_ms=round(latency, 2)
            )
            
            embed = EmbedBuilder.error(
                title="Daily Claim Failed",
                description="An error occurred while claiming daily rewards.",
                help_text="Please try again in a moment.",
            )
            await ctx.send(embed=embed, ephemeral=True)

    @commands.command(name="rd", hidden=True)
    async def daily_short(self, ctx: commands.Context):
        """Alias: rd -> daily"""
        await self.daily(ctx)


async def setup(bot: commands.Bot):
    await bot.add_cog(DailyCog(bot))