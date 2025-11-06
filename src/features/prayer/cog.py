from src.core.bot.base_cog import BaseCog
import discord
from discord.ext import commands
from typing import Optional

from src.core.infra.database_service import DatabaseService
from src.features.player.service import PlayerService
from src.features.prayer.service import PrayerService
from src.core.infra.redis_service import RedisService
from src.core.infra.transaction_logger import TransactionLogger
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

    @commands.hybrid_command(
        name="pray",
        aliases=["rp", "rpray"],
        description="Perform a prayer to gain grace for summoning",
    )
    @ratelimit(uses=10, per_seconds=60, command_name="pray")
    async def pray(self, ctx: commands.Context):
        """Perform a prayer to gain grace (1 charge per use)."""
        await ctx.defer()

        try:
            async with RedisService.acquire_lock(f"pray:{ctx.author.id}", timeout=5):
                async with DatabaseService.get_transaction() as session:
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
                        player_id=ctx.author.id,
                        transaction_type="prayer_performed",
                        details={
                            "grace_gained": result["grace_gained"],
                            "has_charge_after": result["has_charge"],
                            "modifiers_applied": result.get("modifiers_applied", {}),
                        },
                        context=f"command:/{ctx.command.name} guild:{ctx.guild.id if ctx.guild else 'DM'}",
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
                    # Simple display: +X grace, total balance, regen timer
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
                    await ctx.send(embed=embed, view=view)

        except InsufficientResourcesError as e:
            embed = EmbedBuilder.error(
                title="Insufficient Prayer Charges",
                description=f"You need **{e.required}** prayer charges, but only have **{e.current}**.",
                help_text="Prayer charges regenerate every 5 minutes. Wait a bit and try again!",
            )

            try:
                async with DatabaseService.get_transaction() as session:
                    player = await PlayerService.get_player_with_regen(
                        session, ctx.author.id, lock=False
                    )
                    if player:
                        embed.add_field(
                            name="⏳ Next Charge",
                            value=f"Regenerates in: {player.get_prayer_regen_display()}",
                            inline=False,
                        )
            except Exception:
                pass

            await ctx.send(embed=embed, ephemeral=True)

        except ValidationError as e:
            embed = EmbedBuilder.error(
                title="Invalid Input",
                description=str(e),
                help_text="Prayer uses 1 charge and regenerates every 5 minutes.",
            )
            await ctx.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Prayer error for user {ctx.author.id}: {e}", exc_info=True)
            embed = EmbedBuilder.error(
                title="Prayer Failed",
                description="An error occurred while performing prayers.",
                help_text="Please try again in a moment.",
            )
            await ctx.send(embed=embed, ephemeral=True)

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
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(PrayCog(bot))
