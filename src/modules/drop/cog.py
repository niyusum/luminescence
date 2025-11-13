from src.core.bot.base_cog import BaseCog
import discord
from discord.ext import commands
from typing import Optional
import time

from src.core.infra.database_service import DatabaseService
from src.modules.player.service import PlayerService
from src.modules.drop.service import DropService
from src.core.infra.redis_service import RedisService
from src.core.infra.transaction_logger import TransactionLogger
from src.core.config.config_manager import ConfigManager
from core.event.bus.event_bus import EventBus
from src.core.exceptions import InsufficientResourcesError, ValidationError
from src.core.logging.logger import get_logger
from src.utils.decorators import ratelimit
from utils.embed_builder import EmbedBuilder

logger = get_logger(__name__)


class DropCog(BaseCog):
    """
    DROP system for auric coin generation.

    Players spend drop charges to gain auric coin, which is used for summoning maidens.
    DROP charges regenerate over time. Class and leader bonuses affect auric coin gained.

    LUMEN LAW Compliance:
        - SELECT FOR UPDATE on state changes (Article I.1)
        - Transaction logging (Article I.2)
        - Redis locks for multi-drop (Article I.3)
        - ConfigManager for all values (Article I.4)
        - Specific exception handling (Article I.5)
        - Single commit per transaction (Article I.6)
        - All logic through PlayerService (Article I.7)
    """

    def __init__(self, bot: commands.Bot):
        super().__init__(bot, "DropCog")
        self.bot = bot

    @commands.command(
        name="drop",
        aliases=["d"],
        description="Drop an AuricCoin for summoning",
    )
    @ratelimit(
        uses=ConfigManager.get("rate_limits.drop.drop.uses", 20),
        per_seconds=ConfigManager.get("rate_limits.drop.drop.period", 60),
        command_name="charge"
    )
    async def charge(self, ctx: commands.Context):
        """Drop an AuricCoin (1 charge per use)."""
        start_time = time.perf_counter()
        await ctx.defer()

        try:
            async with RedisService.acquire_lock(f"drop:{ctx.author.id}", timeout=5):
                async with DatabaseService.get_transaction() as session:
                    player = await self.require_player(ctx, session, ctx.author.id, lock=True)
                    if not player:
                        return

                    if player.DROP_CHARGES < 1:
                        raise InsufficientResourcesError(
                            resource="DROP_CHARGES",
                            required=1,
                            current=player.DROP_CHARGES,
                        )

                    result = await DropService.perform_drop(
                        session, player, charges=1
                    )

                    await TransactionLogger.log_transaction(
                        session=session,
                        player_id=ctx.author.id,
                        transaction_type="drop_performed",
                        details={
                            "auric_coin_gained": result["auric_coin_gained"],
                            "has_charge_after": result["has_charge"],
                            "modifiers_applied": result.get("modifiers_applied", {}),
                        },
                        context="drop_command",
                    )

                    await EventBus.publish(
                        "drop_completed",
                        {
                            "player_id": ctx.author.id,
                            "auric_coin_gained": result["auric_coin_gained"],
                            "has_charge": result["has_charge"],
                            "channel_id": ctx.channel.id,
                            "__topic__": "drop_completed",
                            "timestamp": discord.utils.utcnow(),
                        },
                    )

                    # --- Embed Construction ---
                    status_text = "✅ Ready!" if result['has_charge'] else f"⏳ {result['next_available']}"

                    embed = EmbedBuilder.success(
                        title="💎 DROP Complete",
                        description=(
                            f"+**{result['auric_coin_gained']} AuricCoin**\n"
                            f"**Total AuricCoin:** {result['total_auric_coin']}"
                        ),
                        footer=f"Next drop: {status_text}"
                    )

                    view = DropActionView(ctx.author.id, result["total_auric_coin"])
                    message = await ctx.send(embed=embed, view=view)
                    view.message = message

            # Log successful execution
            latency = (time.perf_counter() - start_time) * 1000
            self.log_command_use(
                "drop",
                ctx.author.id,
                guild_id=ctx.guild.id if ctx.guild else None,
                latency_ms=round(latency, 2),
                auric_coin_gained=result["auric_coin_gained"]
            )

        except Exception as e:
            # Standardized error handling
            latency = (time.perf_counter() - start_time) * 1000
            self.log_cog_error(
                "drop",
                e,
                user_id=ctx.author.id,
                guild_id=ctx.guild.id if ctx.guild else None,
                latency_ms=round(latency, 2)
            )

            if not await self.handle_standard_errors(ctx, e):
                await self.send_error(
                    ctx,
                    "DROP Failed",
                    "An unexpected error occurred while performing drop.",
                    help_text="Please try again in a moment."
                )


class DropActionView(discord.ui.View):
    """Action buttons after drop completion."""

    def __init__(self, user_id: int, total_auric_coin: int):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.total_auric_coin = total_auric_coin
        self.message: Optional[discord.Message] = None

        if total_auric_coin < 1:
            self.summon_button.disabled = True

    def set_message(self, message: discord.Message):
        self.message = message

    @discord.ui.button(
        label="✨ Summon Now",
        style=discord.ButtonStyle.primary,
        custom_id="quick_summon_after_drop",
    )
    async def summon_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button is not for you!", ephemeral=True)
            return

        await interaction.response.send_message(
            f"You have **{self.total_auric_coin}** auric coin available!\nUse `/summon` to summon powerful maidens.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="🔁 Drop Again",
        style=discord.ButtonStyle.success,
        custom_id="drop_again",
    )
    async def drio_again_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button is not for you!", ephemeral=True)
            return

        await interaction.response.send_message(
            "Use `/charge` to continue dropping and gaining more auric coin!", ephemeral=True
        )

    @discord.ui.button(
        label="📊 View Profile",
        style=discord.ButtonStyle.secondary,
        custom_id="view_profile_after_drop",
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
    await bot.add_cog(DropCog(bot))
