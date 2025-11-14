import discord
from discord.ext import commands
from typing import Optional, List, Dict, Any, TYPE_CHECKING
import time

from src.core.bot.base_cog import BaseCog
from src.core.infra.database_service import DatabaseService
from src.core.infra.transaction_logger import TransactionLogger
from src.core.infra.redis_service import RedisService
from src.core.config import ConfigManager
from core.event.bus.event_bus import EventBus
from src.modules.player.service import PlayerService
from src.modules.fusion.service import FusionService
from src.core.exceptions import InsufficientResourcesError, InvalidFusionError, NotFoundError
from src.core.logging.logger import get_logger
from src.utils.decorators import ratelimit
from src.ui import EmbedFactory, BaseView
from src.ui.emojis import Emojis

if TYPE_CHECKING:
    from typing import Callable

logger = get_logger(__name__)


class FusionCog(BaseCog):
    """
    Maiden fusion system for tier progression.

    Handles the Discord command interface and passes execution to FusionService.
    """

    def __init__(self, bot: commands.Bot):
        """Initialize the Fusion Cog."""
        super().__init__(bot, self.__class__.__name__)
        self.bot = bot

    @commands.command(
        name="fusion",
        aliases=[],
        description="Fuse two maidens to create a higher tier maiden",
    )
    @ratelimit(
        uses=ConfigManager.get("rate_limits.fusion.main.uses", 15),
        per_seconds=ConfigManager.get("rate_limits.fusion.main.period", 60),
        command_name="fusion"
    )
    async def fusion(self, ctx: commands.Context):
        """Open the fusion interface."""
        start_time = time.perf_counter()
        await self.safe_defer(ctx)

        try:
            async with DatabaseService.get_transaction() as session:
                # Retrieve player, no lock needed for read-only UI load
                player = await self.require_player(
                    session, ctx, ctx.author.id, lock=False
                )
                if not player:
                    return

                fusable_maidens = await FusionService.get_fusable_maidens(
                    session, player.discord_id
                )

                if not fusable_maidens:
                    await self.send_error(
                        ctx,
                        "No Fusable Maidens",
                        (
                            "You need **2 or more** of the same maiden at the same tier to fuse."
                        ),
                        help_text="Tip: Use `/summon` to get new maidens.",
                        warning=True
                    )
                    return

                embed = EmbedFactory.primary(
                    title=f"{Emojis.FUSION} Fusion System",
                    description="Select maidens to fuse into a higher tier!\n\n**Choose carefully:** Fusion has a chance of failure at higher tiers.",
                    footer=f"{len(fusable_maidens)} fusable maidens available",
                )

                # Display by tier
                by_tier: Dict[int, List[Dict[str, Any]]] = {}
                for maiden in fusable_maidens:
                    by_tier.setdefault(maiden["tier"], []).append(maiden)

                tier_text = "\n".join(
                    f"• **Tier {tier}**: {len(maidens)} option{'s' if len(maidens) > 1 else ''}"
                    for tier, maidens in sorted(by_tier.items())
                )

                embed.add_field(
                    name="Available by Tier", value=tier_text or "None", inline=False
                )

                embed.add_field(
                    name=f"{Emojis.TIP} Fusion Tips",
                    value=(
                        "• Higher tiers have lower success rates\n"
                        "• Failed fusions grant fusion shards\n"
                        "• Use shards for guaranteed fusions\n"
                        "• Save your best maidens!"
                    ),
                    inline=False,
                )

                view = FusionSelectionView(
                    ctx.author.id,
                    fusable_maidens,
                    self.log_cog_error
                )

                message = await ctx.send(embed=embed, view=view)
                view.message = message

            # Log latency (Success)
            latency = (time.perf_counter() - start_time) * 1000
            self.log_command_use(
                "fusion",
                ctx.author.id,
                guild_id=ctx.guild.id if ctx.guild else None,
                latency_ms=round(latency, 2),
            )

        except Exception as e:
            # Structured Error Logging
            latency = (time.perf_counter() - start_time) * 1000
            self.log_cog_error(
                "fusion_ui_load",
                e,
                user_id=ctx.author.id,
                guild_id=ctx.guild.id if ctx.guild else None,
                latency_ms=round(latency, 2),
                status="unexpected_ui_failure"
            )
            if not await self.handle_standard_errors(ctx, e):
                await self.send_error(
                    ctx,
                    "Fusion Error",
                    "Unable to load fusion interface. The system has been notified.",
                )


class FusionSelectionView(discord.ui.View):
    """Interactive view for selecting maidens to fuse."""

    def __init__(
        self,
        user_id: int,
        fusable_maidens: List[Dict[str, Any]],
        cog_logger: 'Callable'
    ):
        """Initialize the fusion selection view."""
        # LUMEN LAW POSITIONAL MARKER: VIEW TIMEOUT SET
        super().__init__(timeout=300)
        self.user_id = user_id
        self.fusable_maidens = fusable_maidens
        self.message: Optional[discord.Message] = None
        self.cog_logger = cog_logger
        self.add_item(TierSelectDropdown(user_id, fusable_maidens, cog_logger))

    @discord.ui.button(
        label=f"{Emojis.INFO} View Fusion Rates",
        style=discord.ButtonStyle.secondary,
        custom_id="view_fusion_rates",
    )
    async def view_rates(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ):
        """Show the current fusion success rates."""
        # LUMEN LAW POSITIONAL MARKER: USER VALIDATION
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This button is not for you!", ephemeral=True
            )
            return
        
        # LUMEN LAW POSITIONAL MARKER: CONFIGMANAGER USE
        fusion_rates = ConfigManager.get("fusion.base_rates", default={
            1: 0.95, 2: 0.90, 3: 0.85, 4: 0.75, 5: 0.65, 6: 0.55,
            7: 0.45, 8: 0.35, 9: 0.25, 10: 0.15, 11: 0.10
        })

        rates_embed = EmbedFactory.info(
            title="Fusion Success Rates",
            description="Higher tiers have lower success rates. Failed fusions grant shards!",
            footer="Rates may be boosted during events",
        )

        rates_text = "\n".join([
            f"**Tier {tier} → {tier + 1}**: {rate * 100:.0f}%"
            for tier, rate in sorted(fusion_rates.items())
        ])

        rates_embed.add_field(name="Base Rates", value=rates_text, inline=False)
        rates_embed.add_field(
            name=f"{Emojis.LUMENITE} Fusion Shards",
            value=(
                f"Failed fusions grant shards. Collect **{ConfigManager.get('fusion.shard_guarantee_count', default=10)}** shards of a tier to "
                "guarantee a fusion to the next tier!"
            ),
            inline=False,
        )

        await interaction.response.send_message(embed=rates_embed, ephemeral=True)

    async def on_timeout(self):
        """Disable all buttons visually when the view expires."""
        # LUMEN LAW POSITIONAL MARKER: VIEW TIMEOUT HANDLER
        for item in self.children:
            item.disabled = True

        try:
            # If we still have access to the sent message, edit to reflect disabled state
            if self.message:
                await self.message.edit(view=self)
        except discord.HTTPException:
            pass


class TierSelectDropdown(discord.ui.Select):
    """Dropdown for selecting fusion tier."""

    def __init__(
        self,
        user_id: int,
        fusable_maidens: List[Dict[str, Any]],
        cog_logger: 'Callable'
    ):
        """Initialize the tier selection dropdown."""
        self.user_id = user_id
        self.fusable_maidens = fusable_maidens
        self.cog_logger = cog_logger

        by_tier: Dict[int, List[Dict[str, Any]]] = {}
        for maiden in fusable_maidens:
            by_tier.setdefault(maiden["tier"], []).append(maiden)

        options = [
            discord.SelectOption(
                label=f"Tier {tier} Fusion",
                description=f"{len(maidens)} option{'s' if len(maidens) > 1 else ''} available",
                value=str(tier),
            )
            for tier, maidens in sorted(by_tier.items())
        ]

        super().__init__(
            placeholder="Select tier to fuse...",
            min_values=1,
            max_values=1,
            options=options[:25],
        )

    async def callback(self, interaction: discord.Interaction):
        """Handle tier selection."""
        # LUMEN LAW POSITIONAL MARKER: USER VALIDATION
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This selection is not for you!", ephemeral=True
            )
            return

        selected_tier = int(self.values[0])
        tier_maidens = [m for m in self.fusable_maidens if m["tier"] == selected_tier]

        embed = EmbedFactory.primary(
            title=f"Tier {selected_tier} Fusion",
            description=(
                f"Select which Tier {selected_tier} maiden to fuse.\n\n"
                f"This will fuse **2 copies** to create **1 Tier {selected_tier + 1}** maiden."
            ),
            footer=f"{len(tier_maidens)} options available",
        )

        view = MaidenSelectView(self.user_id, tier_maidens, self.cog_logger)
        await interaction.response.edit_message(embed=embed, view=view)


class MaidenSelectView(discord.ui.View):
    """View for selecting a specific maiden to fuse."""

    def __init__(self, user_id: int, tier_maidens: List[Dict[str, Any]], cog_logger: 'Callable'):
        """Initialize the maiden selection view."""
        super().__init__(timeout=300)
        self.user_id = user_id
        self.tier_maidens = tier_maidens
        self.cog_logger = cog_logger
        self.add_item(MaidenSelectDropdown(user_id, tier_maidens, cog_logger))

    @discord.ui.button(
        label=f"{Emojis.BACK} Back",
        style=discord.ButtonStyle.secondary,
        custom_id="back_to_tier_select",
    )
    async def back_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        """Go back to the initial tier selection view."""
        # LUMEN LAW POSITIONAL MARKER: USER VALIDATION
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This button is not for you!", ephemeral=True
            )
            return

        await interaction.response.send_message(
            "Use `/fusion` to restart the fusion process.", ephemeral=True
        )


class MaidenSelectDropdown(discord.ui.Select):
    """Dropdown for selecting specific maiden and executing fusion."""

    def __init__(self, user_id: int, tier_maidens: List[Dict[str, Any]], cog_logger: 'Callable'):
        """Initialize the maiden selection dropdown."""
        self.user_id = user_id
        self.tier_maidens = tier_maidens
        self.cog_logger = cog_logger

        options = [
            discord.SelectOption(
                label=f"{m['name']} (Tier {m['tier']})",
                description=f"{m['element']} • x{m['quantity']} owned",
                value=str(m["id"]),
            )
            for m in tier_maidens[:25]
        ]

        super().__init__(
            placeholder="Select maiden to fuse...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        """Execute the fusion transaction."""
        start_time = time.perf_counter()
        
        # LUMEN LAW POSITIONAL MARKER: USER VALIDATION
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This selection is not for you!", ephemeral=True
            )
            return

        # LUMEN LAW POSITIONAL MARKER: DEFER RESPONSE
        await interaction.response.defer()

        maiden_id = int(self.values[0])

        # LUMEN LAW POSITIONAL MARKER: LOG CONTEXT
        log_context = {
            "maiden_id": maiden_id,
            "tier_selected": self.tier_maidens[0]["tier"] if self.tier_maidens else 0,
            "guild_id": interaction.guild_id,
        }

        try:
            # LUMEN LAW POSITIONAL MARKER: REDIS LOCK
            async with RedisService.acquire_lock(f"fusion:{self.user_id}", timeout=10):
                # LUMEN LAW POSITIONAL MARKER: DATABASE TRANSACTION
                async with DatabaseService.get_transaction() as session:
                    # LUMEN LAW POSITIONAL MARKER: PESSIMISTIC LOCK (SELECT FOR UPDATE)
                    player = await PlayerService.get_player_with_regen(
                        session, self.user_id, lock=True
                    )

                    if not player:
                        raise NotFoundError("Player profile not found after lock.")

                    # LUMEN LAW POSITIONAL MARKER: SERVICE CALL ONLY (NO BUSINESS LOGIC)
                    result = await FusionService.attempt_fusion(session, player, maiden_id)

                    # LUMEN LAW POSITIONAL MARKER: TRANSACTION LOGGING
                    await TransactionLogger.log_transaction(
                        session=session,
                        player_id=self.user_id,
                        transaction_type="fusion_attempted",
                        details={
                            "maiden_id": maiden_id,
                            "success": result["success"],
                            "tier_from": result["tier_from"],
                            "tier_to": result["tier_to"],
                            "cost": result.get("cost", 0),
                        },
                        context=f"fusion guild:{interaction.guild_id}",
                    )

                # LUMEN LAW POSITIONAL MARKER: EVENT PUBLISHING (SIDE EFFECT)
                await EventBus.publish(
                    "fusion_completed",
                    {
                        "player_id": self.user_id,
                        "success": result["success"],
                        "tier_from": result["tier_from"],
                        "tier_to": result["tier_to"],
                        "channel_id": interaction.channel_id,
                        "timestamp": discord.utils.utcnow(),
                    },
                )

                # Fusion outcome embeds
                if result["success"]:
                    embed = EmbedFactory.success(
                        title=f"{Emojis.FUSION} Fusion Successful!",
                        description=(
                            f"**{result['maiden_name']}** has been upgraded!\n\n"
                            f"**Tier {result['tier_from']} → Tier {result['tier_to']}**"
                        ),
                        footer=f"Fusion #{player.total_fusions}",
                    )
                    embed.add_field(
                        name="New Stats",
                        value=f"ATK: {result.get('attack', 0):,}\nDEF: {result.get('defense', 0):,}",
                        inline=True,
                    )
                else:
                    embed = EmbedFactory.warning(
                        title="Fusion Failed",
                        description=(
                            f"The fusion did not succeed.\n\n"
                            f"**Tier {result['tier_from']}** maidens were lost."
                        ),
                        footer="Better luck next time!",
                    )
                    # LUMEN LAW POSITIONAL MARKER: CONFIGMANAGER USE
                    embed.add_field(
                        name=f"{Emojis.LUMENITE} Consolation",
                        value=(
                            f"+1 Tier {result['tier_from']} Fusion Shard\n\nCollect "
                            f"{ConfigManager.get('fusion.shard_guarantee_count', default=10)} shards for a guaranteed fusion!"
                        ),
                        inline=False,
                    )

                # LUMEN LAW POSITIONAL MARKER: DISABLE BUTTONS AFTER USE
                await interaction.edit_original_response(embed=embed, view=None)

            # Log latency (Success)
            latency = (time.perf_counter() - start_time) * 1000
            self.cog_logger(
                "fusion_execute",
                None,
                user_id=self.user_id,
                latency_ms=round(latency, 2),
                status="success",
                **log_context
            )

        # LUMEN LAW POSITIONAL MARKER: SPECIFIC EXCEPTION HANDLING
        except (InsufficientResourcesError, InvalidFusionError, NotFoundError) as e:
            # Log domain error
            latency = (time.perf_counter() - start_time) * 1000
            self.cog_logger(
                "fusion_execute",
                e,
                user_id=self.user_id,
                latency_ms=round(latency, 2),
                status="domain_error",
                error_type=type(e).__name__,
                **log_context
            )
            # Send friendly response for domain error
            embed = EmbedFactory.error(title="Fusion Error", description=str(e))
            await interaction.followup.send(embed=embed, ephemeral=True)
            # Disable view after failure to prevent re-try
            await interaction.edit_original_response(view=None)

        except Exception as e:
            # Catch-all for auditable failures
            latency = (time.perf_counter() - start_time) * 1000
            self.cog_logger(
                "fusion_execute",
                e,
                user_id=self.user_id,
                latency_ms=round(latency, 2),
                status="unexpected_failure",
                error_type=type(e).__name__,
                **log_context
            )
            embed = EmbedFactory.error(
                title="System Error", description="An unexpected error occurred during fusion. The team has been notified."
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            # Disable view after critical failure
            await interaction.edit_original_response(view=None)


async def setup(bot: commands.Bot):
    """Required for dynamic cog loading."""
    await bot.add_cog(FusionCog(bot))