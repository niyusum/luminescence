from src.core.bot.base_cog import BaseCog
import discord
from discord.ext import commands
from typing import Optional
import time

from src.core.infra.database_service import DatabaseService
from src.modules.player.service import PlayerService
from src.modules.prayer.service import PrayerService
from src.core.infra.redis_service import RedisService
from src.core.infra.transaction_logger import TransactionLogger
from src.core.config.config_manager import ConfigManager
from src.core.event.event_bus import EventBus
from src.core.exceptions import InsufficientResourcesError, ValidationError
from src.core.logging.logger import get_logger
from src.utils.decorators import ratelimit
from utils.embed_builder import EmbedBuilder

logger = get_logger(__name__)


class PrayCog(BaseCog):
    """
    Prayer system for grace generation.

    Players spend prayer charges to gain grace, which is used for summoning maidens.
    Prayer charges regenerate over time. Class and leader bonuses affect grace gained.

    RIKI LAW Compliance:
        - SELECT FOR UPDATE on state changes (Article I.1)
        - Transaction logging (Article I.2)
        - Redis locks for multi-prayer (Article I.3)
        - ConfigManager for all values (Article I.4)
        - Specific exception handling (Article I.5)
        - Single commit per transaction (Article I.6)
        - All logic through PlayerService (Article I.7)
    """

    def __init__(self, bot: commands.Bot):
        super().__init__(bot, "PrayCog")
        self.bot = bot

    @commands.command(
        name="pray",
        aliases=["rp", "rpray", "rikipray"],
        description="Perform a prayer to gain grace for summoning",
    )
    @ratelimit(
        uses=ConfigManager.get("rate_limits.prayer.pray.uses", 20),
        per_seconds=ConfigManager.get("rate_limits.prayer.pray.period", 60),
        command_name="pray"
    )
    async def pray(self, ctx: commands.Context):
        """Perform a prayer to gain grace (1 charge per use)."""
        start_time = time.perf_counter()
        await ctx.defer()

        try:
            async with RedisService.acquire_lock(f"pray:{ctx.author.id}", timeout=5):
                async with DatabaseService.get_transaction() as session:
                    player = await self.require_player(ctx, session, ctx.author.id, lock=True)
                    if not player:
                        return

                    if player.prayer_charges < 1:
                        raise InsufficientResourcesError(
                            resource="prayer_charges",
                            required=1,
                            current=player.prayer_charges,
                        )

                    result = await PrayerService.perform_prayer(
                        session, player, charges=1
                    )

                    await TransactionLogger.log_transaction(
                        session=session,
                        player_id=ctx.author.id,
                        transaction_type="prayer_performed",
                        details={
                            "grace_gained": result["grace_gained"],
                            "has_charge_after": result["has_charge"],
                            "modifiers_applied": result.get("modifiers_applied", {}),
                        },
                        context="prayer_command",
                    )

                    await EventBus.publish(
                        "prayer_completed",
                        {
                            "player_id": ctx.author.id,
                            "grace_gained": result["grace_gained"],
                            "has_charge": result["has_charge"],
                            "channel_id": ctx.channel.id,
                            "__topic__": "prayer_completed",
                            "timestamp": discord.utils.utcnow(),
                        },
                    )

                    # --- Embed Construction ---
                    status_text = "✅ Ready!" if result['has_charge'] else f"⏳ {result['next_available']}"

                    embed = EmbedBuilder.success(
                        title="🙏 Prayer Complete",
                        description=(
                            f"+**{result['grace_gained']} Grace**\n"
                            f"**Total Grace:** {result['total_grace']}"
                        ),
                        footer=f"Next prayer: {status_text}"
                    )

                    view = PrayActionView(ctx.author.id, result["total_grace"])
                    message = await ctx.send(embed=embed, view=view)
                    view.message = message

            # Log successful execution
            latency = (time.perf_counter() - start_time) * 1000
            self.log_command_use(
                "pray",
                ctx.author.id,
                guild_id=ctx.guild.id if ctx.guild else None,
                latency_ms=round(latency, 2),
                grace_gained=result["grace_gained"]
            )

        except Exception as e:
            # Standardized error handling
            latency = (time.perf_counter() - start_time) * 1000
            self.log_cog_error(
                "pray",
                e,
                user_id=ctx.author.id,
                guild_id=ctx.guild.id if ctx.guild else None,
                latency_ms=round(latency, 2)
            )

            if not await self.handle_standard_errors(ctx, e):
                await self.send_error(
                    ctx,
                    "Prayer Failed",
                    "An unexpected error occurred while performing prayer.",
                    help_text="Please try again in a moment."
                )

    @commands.command(name="rp", hidden=True)
    async def pray_short(self, ctx: commands.Context):
        """Alias: rp -> pray"""
        await self.pray(ctx)


class PrayActionView(discord.ui.View):
    """Action buttons after prayer completion."""

    def __init__(self, user_id: int, total_grace: int):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.total_grace = total_grace
        self.message: Optional[discord.Message] = None

        if total_grace < 1:
            self.summon_button.disabled = True

    def set_message(self, message: discord.Message):
        self.message = message

    @discord.ui.button(
        label="✨ Summon Now",
        style=discord.ButtonStyle.primary,
        custom_id="quick_summon_after_pray",
    )
    async def summon_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button is not for you!", ephemeral=True)
            return

        await interaction.response.send_message(
            f"You have **{self.total_grace}** grace available!\nUse `/summon` to summon powerful maidens.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="🔁 Pray Again",
        style=discord.ButtonStyle.success,
        custom_id="pray_again",
    )
    async def pray_again_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button is not for you!", ephemeral=True)
            return

        await interaction.response.send_message(
            "Use `/pray` to continue praying and gaining more grace!", ephemeral=True
        )

    @discord.ui.button(
        label="📊 View Profile",
        style=discord.ButtonStyle.secondary,
        custom_id="view_profile_after_pray",
    )
    async def profile_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button is not for you!", ephemeral=True)
            return

        await interaction.response.send_message(
            "Use `/profile` to view your updated stats!", ephemeral=True
        )

    async def on_timeout(self):
        """Disable all buttons visually when the view expires."""
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

        try:
            if self.message:
                await self.message.edit(view=self)
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(PrayCog(bot))
