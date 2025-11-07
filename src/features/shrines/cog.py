"""
Shrine management Discord interface.

Provides interactive shrine viewing, upgrading, collecting, and selling
through Discord commands and button-based UI.

RIKI LAW Compliance:
    - All business logic delegated to ShrineService (Article I.7)
    - No locks for read operations (Article I.11)
    - Pessimistic locking for state modifications (Article I.1)
    - Transaction logging via ShrineService (Article II)
    - Specific exception handling (Article I.5)
"""

import discord
from discord.ext import commands
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from src.core.bot.base_cog import BaseCog
from src.features.shrines.service import ShrineService
from src.core.config.config_manager import ConfigManager
from src.utils.decorators import ratelimit
from utils.embed_builder import EmbedBuilder


class ShrineCog(BaseCog):
    """
    Personal shrine management system.

    Allows players to view, upgrade, collect from, and sell their personal
    shrines that provide passive resource yields.

    Commands:
        shrines (rsh, rshrines, rikishrines) - View shrines and manage them
    """

    def __init__(self, bot: commands.Bot):
        super().__init__(bot, "ShrineCog")

    @commands.command(
        name="shrines",
        aliases=["rsh", "rshrines", "rikishrines"],
        description="View and manage your personal shrines"
    )
    @ratelimit(
        uses=ConfigManager.get("rate_limits.shrines.status.uses", 10),
        per_seconds=ConfigManager.get("rate_limits.shrines.status.period", 60),
        command_name="shrines"
    )
    async def shrines(self, ctx: commands.Context):
        """Show shrine overview with interactive management menu."""
        await self.safe_defer(ctx)

        try:
            async with self.get_session() as session:
                player = await self.require_player(ctx, session, ctx.author.id)
                if not player:
                    return

                # Get all shrines
                shrines = await ShrineService.list_shrines(session, player.discord_id)

                # Build shrine overview embed
                if not shrines:
                    embed = EmbedBuilder.info(
                        title="🏛️ Personal Shrines",
                        description=(
                            "You don't have any shrines yet!\n\n"
                            "**Shrines provide passive resource yields** that you can collect periodically.\n"
                            "Check the shop or special events to acquire shrine slots."
                        ),
                        footer="Shrines are a great way to earn passive income!"
                    )
                    await ctx.send(embed=embed)
                    return

                # Calculate summary stats
                total_shrines = len(shrines)
                ready_count = 0
                total_value_estimate = 0

                for shrine in shrines:
                    conf = ConfigManager.get(f"shrines.{shrine.shrine_type}", {})
                    cap_hours = int(conf.get("collection_cap_hours", 24))

                    # Check if ready
                    if shrine.last_collected_at:
                        elapsed = (datetime.utcnow() - shrine.last_collected_at) / timedelta(hours=1)
                        if elapsed >= cap_hours:
                            ready_count += 1
                    else:
                        ready_count += 1

                    # Estimate value (simplified)
                    player_snapshot = {
                        "rikis": int(getattr(player, "rikis", 0)),
                        "grace": int(getattr(player, "grace", 0)),
                    }
                    _, amount = ShrineService._compute_yield(conf, shrine.level, player_snapshot)
                    if player.player_class == "invoker":
                        amount = int(amount * 1.25)
                    total_value_estimate += amount

                embed = EmbedBuilder.primary(
                    title=f"🏛️ {ctx.author.name}'s Shrines",
                    description="Manage your passive resource shrines",
                    footer="Use buttons below to collect or manage shrines"
                )

                # Summary stats
                stats_text = (
                    f"**Total Shrines:** {total_shrines}\n"
                    f"**Ready to Collect:** {ready_count}\n"
                    f"**Est. Ready Value:** ~{total_value_estimate:,} resources"
                )
                embed.add_field(name="📊 Overview", value=stats_text, inline=False)

                # List shrines
                shrine_list = []
                for shrine in shrines:
                    conf = ConfigManager.get(f"shrines.{shrine.shrine_type}", {})
                    cap_hours = int(conf.get("collection_cap_hours", 24))

                    # Shrine emoji based on type
                    shrine_emoji = "⛩️" if shrine.shrine_type == "grace" else "🏛️"

                    # Check readiness
                    status = "✅ Ready"
                    if shrine.last_collected_at:
                        elapsed = (datetime.utcnow() - shrine.last_collected_at) / timedelta(hours=1)
                        if elapsed < cap_hours:
                            remaining = cap_hours - elapsed
                            status = f"⏳ {int(remaining)}h remaining"

                    shrine_line = (
                        f"{shrine_emoji} **{shrine.shrine_type.title()}** (Slot {shrine.slot}) - Level {shrine.level}\n"
                        f"  └ {status}"
                    )
                    shrine_list.append(shrine_line)

                if shrine_list:
                    embed.add_field(
                        name="🏛️ Your Shrines",
                        value="\n".join(shrine_list[:10]),  # Max 10 to avoid embed limits
                        inline=False
                    )

                # Send with interactive menu
                view = ShrineMenuView(ctx.author.id, self.bot, ctx, shrines)
                message = await ctx.send(embed=embed, view=view)
                view.message = message

                self.log_command_use("shrines", ctx.author.id, guild_id=ctx.guild.id if ctx.guild else None)

        except Exception as e:
            self.log_cog_error("shrines", e, user_id=ctx.author.id)
            if not await self.handle_standard_errors(ctx, e):
                await self.send_error(
                    ctx,
                    "Shrine Error",
                    "Unable to load your shrines.",
                    help_text="Please try again shortly."
                )


class ShrineMenuView(discord.ui.View):
    """Interactive menu for shrine management."""

    def __init__(self, user_id: int, bot: commands.Bot, ctx: commands.Context, shrines: List[Any]):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.bot = bot
        self.ctx = ctx
        self.shrines = shrines
        self.message: Optional[discord.Message] = None

    @discord.ui.button(
        label="💰 Collect All",
        style=discord.ButtonStyle.success,
        custom_id="collect_all_shrines"
    )
    async def collect_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Collect from all ready shrines."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This menu is not for you!", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=False)

        try:
            from src.core.infra.database_service import DatabaseService

            async with DatabaseService.get_transaction() as session:
                result = await ShrineService.collect_all_personal(session, self.user_id)
                await session.commit()

                # Build result embed
                if not result["collected"]:
                    embed = EmbedBuilder.warning(
                        title="No Shrines Ready",
                        description="None of your shrines are ready to collect yet.",
                        footer="Check back later!"
                    )
                    await interaction.followup.send(embed=embed)
                    return

                # Success embed
                totals = result["totals"]
                collected_count = len(result["collected"])
                pending_count = len(result["pending"])

                rewards_text = "\n".join([
                    f"**{key.replace('_', ' ').title()}:** +{amount:,}"
                    for key, amount in totals.items()
                ])

                embed = EmbedBuilder.success(
                    title="💰 Shrines Collected!",
                    description=f"Collected from **{collected_count}** shrine{'s' if collected_count != 1 else ''}!",
                    footer=f"{pending_count} shrine{'s' if pending_count != 1 else ''} still recharging"
                )

                if rewards_text:
                    embed.add_field(name="Rewards Earned", value=rewards_text, inline=False)

                # Show details for each collected shrine
                if len(result["collected"]) <= 5:
                    details = []
                    for c in result["collected"]:
                        granted_text = ", ".join([f"{v:,} {k}" for k, v in c["granted"].items()])
                        details.append(
                            f"⛩️ {c['type'].title()} (L{c['level']}) → {granted_text}"
                        )
                    if details:
                        embed.add_field(name="Details", value="\n".join(details), inline=False)

                await interaction.followup.send(embed=embed)

        except Exception as e:
            embed = EmbedBuilder.error(
                title="Collection Error",
                description=str(e) if str(e) else "Unable to collect from shrines.",
                footer="Please try again"
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(
        label="⬆️ Upgrade",
        style=discord.ButtonStyle.primary,
        custom_id="upgrade_shrine"
    )
    async def upgrade_shrine(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show shrine upgrade options."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This menu is not for you!", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            if not self.shrines:
                embed = EmbedBuilder.warning(
                    title="No Shrines",
                    description="You don't have any shrines to upgrade.",
                    footer="Acquire shrines first!"
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            # Show upgrade selection view
            view = ShrineUpgradeView(self.user_id, self.bot, self.shrines)

            embed = EmbedBuilder.info(
                title="⬆️ Upgrade Shrine",
                description="Select a shrine to upgrade. Upgrading increases yield but costs rikis.",
                footer="Higher levels = better rewards"
            )

            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            embed = EmbedBuilder.error(
                title="Upgrade Error",
                description="Unable to show upgrade options.",
                footer="Please try again"
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(
        label="🔍 Details",
        style=discord.ButtonStyle.secondary,
        custom_id="shrine_details"
    )
    async def shrine_details(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show detailed shrine information."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This menu is not for you!", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            from src.core.infra.database_service import DatabaseService
            from src.database.models.core.player import Player

            async with DatabaseService.get_session() as session:
                player = await session.get(Player, self.user_id)
                player_snapshot = {
                    "rikis": int(getattr(player, "rikis", 0)),
                    "grace": int(getattr(player, "grace", 0)),
                }

                embed = EmbedBuilder.primary(
                    title="🔍 Shrine Details",
                    description="Detailed information about your shrines",
                    footer="Upgrade shrines to increase yields"
                )

                for shrine in self.shrines[:10]:  # Limit to 10 for embed size
                    conf = ConfigManager.get(f"shrines.{shrine.shrine_type}", {})
                    cap_hours = int(conf.get("collection_cap_hours", 24))
                    target_key, current_yield = ShrineService._compute_yield(conf, shrine.level, player_snapshot)

                    # Apply invoker bonus
                    if player.player_class == "invoker":
                        current_yield = int(current_yield * 1.25)

                    # Next level yield
                    max_level = int(conf.get("max_level", 12))
                    if shrine.level < max_level:
                        _, next_yield = ShrineService._compute_yield(conf, shrine.level + 1, player_snapshot)
                        if player.player_class == "invoker":
                            next_yield = int(next_yield * 1.25)
                        upgrade_cost = ShrineService._next_level_cost(conf, shrine.level)
                        next_info = f"\nNext: {next_yield:,} {target_key} (Cost: {upgrade_cost:,} rikis)"
                    else:
                        next_info = "\n*Max Level*"

                    # Readiness
                    if shrine.last_collected_at:
                        elapsed = (datetime.utcnow() - shrine.last_collected_at) / timedelta(hours=1)
                        if elapsed < cap_hours:
                            remaining = cap_hours - elapsed
                            ready_status = f"⏳ Ready in {int(remaining)}h"
                        else:
                            ready_status = "✅ Ready to collect"
                    else:
                        ready_status = "✅ Ready to collect"

                    field_value = (
                        f"**Level:** {shrine.level}/{max_level}\n"
                        f"**Current Yield:** {current_yield:,} {target_key}\n"
                        f"**Cooldown:** {cap_hours}h\n"
                        f"**Status:** {ready_status}"
                        f"{next_info}"
                    )

                    embed.add_field(
                        name=f"⛩️ {shrine.shrine_type.title()} Shrine (Slot {shrine.slot})",
                        value=field_value,
                        inline=False
                    )

                await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            embed = EmbedBuilder.error(
                title="Details Error",
                description="Unable to load shrine details.",
                footer="Please try again"
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

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


class ShrineUpgradeView(discord.ui.View):
    """View for upgrading a specific shrine."""

    def __init__(self, user_id: int, bot: commands.Bot, shrines: List[Any]):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.bot = bot

        # Create dropdown options (max 25)
        options = []
        for shrine in shrines[:25]:
            conf = ConfigManager.get(f"shrines.{shrine.shrine_type}", {})
            max_level = int(conf.get("max_level", 12))
            upgrade_cost = ShrineService._next_level_cost(conf, shrine.level)

            label = f"{shrine.shrine_type.title()} (Slot {shrine.slot}) - L{shrine.level}"
            if len(label) > 100:
                label = label[:97] + "..."

            if shrine.level >= max_level:
                description = "MAX LEVEL"
            else:
                description = f"Upgrade to L{shrine.level + 1} for {upgrade_cost:,} rikis"
                if len(description) > 100:
                    description = description[:97] + "..."

            # Unique value: shrine_type:slot
            value = f"{shrine.shrine_type}:{shrine.slot}"

            options.append(discord.SelectOption(
                label=label,
                value=value,
                description=description,
                emoji="⛩️" if shrine.shrine_type == "grace" else "🏛️",
                default=False
            ))

        self.select = discord.ui.Select(
            placeholder="Choose a shrine to upgrade...",
            options=options,
            custom_id="shrine_upgrade_select"
        )
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: discord.Interaction):
        """Handle shrine upgrade selection."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This selection is not for you!", ephemeral=True)
            return

        shrine_value = self.select.values[0]
        shrine_type, slot_str = shrine_value.split(":")
        slot = int(slot_str)

        await interaction.response.defer(ephemeral=True)

        try:
            from src.core.infra.database_service import DatabaseService

            async with DatabaseService.get_transaction() as session:
                # Upgrade the shrine
                shrine = await ShrineService.upgrade(session, self.user_id, shrine_type, slot, levels=1)
                await session.commit()

                conf = ConfigManager.get(f"shrines.{shrine_type}", {})
                max_level = int(conf.get("max_level", 12))

                embed = EmbedBuilder.success(
                    title="⬆️ Shrine Upgraded!",
                    description=f"Your **{shrine_type.title()}** shrine (Slot {slot}) is now **Level {shrine.level}**!",
                    footer=f"Level {shrine.level}/{max_level}"
                )

                # Show new yield info
                from src.database.models.core.player import Player
                player = await session.get(Player, self.user_id)
                player_snapshot = {
                    "rikis": int(getattr(player, "rikis", 0)),
                    "grace": int(getattr(player, "grace", 0)),
                }
                target_key, new_yield = ShrineService._compute_yield(conf, shrine.level, player_snapshot)
                if player.player_class == "invoker":
                    new_yield = int(new_yield * 1.25)

                embed.add_field(
                    name="New Yield",
                    value=f"**{new_yield:,}** {target_key} per collection",
                    inline=False
                )

                await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            # Handle standard errors
            from src.core.exceptions import InvalidOperationError, InsufficientResourcesError

            if isinstance(e, InsufficientResourcesError):
                embed = EmbedBuilder.error(
                    title="Insufficient Rikis",
                    description=str(e),
                    help_text="Earn more rikis and try again."
                )
            elif isinstance(e, InvalidOperationError):
                embed = EmbedBuilder.error(
                    title="Cannot Upgrade",
                    description=str(e),
                    help_text="Check shrine level and requirements."
                )
            else:
                embed = EmbedBuilder.error(
                    title="Upgrade Error",
                    description="Unable to upgrade shrine.",
                    footer="Please try again"
                )

            await interaction.followup.send(embed=embed, ephemeral=True)

    async def on_timeout(self):
        """Disable all buttons visually when the view expires."""
        for item in self.children:
            item.disabled = True

        try:
            if self.message:
                await self.message.edit(view=self)
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot):
    """Setup function for loading the cog."""
    await bot.add_cog(ShrineCog(bot))
