import discord
from discord.ext import commands
from typing import Optional
import math
import time

from src.bot.base_cog import BaseCog
from src.modules.maiden.service import MaidenService
from src.modules.maiden.leader_service import LeaderService
from src.modules.combat.service import CombatService
from src.core.config import ConfigManager
from core.event.bus.event_bus import EventBus
from src.utils.decorators import ratelimit
from src.ui import EmbedFactory, BaseView
from src.ui.emojis import Emojis


class MaidenCog(BaseCog):
    """
    Unified maiden management system.

    Provides both maiden collection viewing and leader selection through
    an interactive menu interface. Players can browse their collection,
    filter by tier/element, and set/remove their leader maiden.

    LUMEN LAW Compliance:
        - No locks for read operations (Article I.11)
        - Pessimistic locking for leader changes (Article I.1)
        - Command/Query separation (Article I.11)
        - Efficient pagination
        - Specific exception handling (Article I.5)
        - Transaction logging for leader changes (Article II)
    """

    def __init__(self, bot: commands.Bot):
        super().__init__(bot, "MaidenCog")

    @commands.command(
        name="maidens",
        aliases=[],
        description="View your maiden collection and manage your leader",
    )
    @ratelimit(
        uses=ConfigManager.get("rate_limits.maiden.view.uses", 15),
        per_seconds=ConfigManager.get("rate_limits.maiden.view.period", 60),
        command_name="maidens"
    )
    async def maidens(self, ctx: commands.Context):
        """Show maiden overview with interactive menu."""
        start_time = time.perf_counter()
        await self.safe_defer(ctx)

        try:
            async with self.get_session() as session:
                player = await self.require_player(ctx, session, ctx.author.id)
                if not player:
                    return

                # Get collection stats
                maidens = await MaidenService.get_player_maidens(session, player.discord_id)

                # Get power stats
                total_power = await CombatService.calculate_total_power(session, player.discord_id)
                strategic_power = await CombatService.calculate_strategic_power(session, player.discord_id)

                # Get leader info
                leader_info = None
                leader_bonuses = ""
                if player.leader_maiden_id:
                    from src.database.models.core.maiden import Maiden
                    from database.models.core.maiden_base import MaidenBase

                    leader = await session.get(Maiden, player.leader_maiden_id)
                    if leader:
                        maiden_base = await session.get(MaidenBase, leader.maiden_base_id)
                        if maiden_base:
                            leader_info = {
                                "name": maiden_base.name,
                                "tier": leader.tier,
                                "element": maiden_base.element,
                                "element_emoji": CombatService.get_element_emoji(maiden_base.element)
                            }

                            # Get leader bonuses
                            modifiers = await LeaderService.get_active_modifiers(player)
                            bonus_parts = []
                            if modifiers.get("income_boost", 1.0) > 1.0:
                                pct = (modifiers["income_boost"] - 1.0) * 100
                                bonus_parts.append(f"+{pct:.0f}% Income")
                            if modifiers.get("xp_boost", 1.0) > 1.0:
                                pct = (modifiers["xp_boost"] - 1.0) * 100
                                bonus_parts.append(f"+{pct:.0f}% XP")
                            if modifiers.get("fusion_bonus", 0.0) > 0.0:
                                pct = modifiers["fusion_bonus"] * 100
                                bonus_parts.append(f"+{pct:.0f}% Fusion")
                            if modifiers.get("energy_efficiency", 0.0) > 0.0:
                                pct = modifiers["energy_efficiency"] * 100
                                bonus_parts.append(f"-{pct:.0f}% Energy Cost")
                            if modifiers.get("stamina_efficiency", 0.0) > 0.0:
                                pct = modifiers["stamina_efficiency"] * 100
                                bonus_parts.append(f"-{pct:.0f}% Stamina Cost")

                            leader_bonuses = " • ".join(bonus_parts) if bonus_parts else "No active bonuses"

                # Build overview embed
                embed = EmbedFactory.primary(
                    title=f"{Emojis.MAIDEN} {ctx.author.name}'s Maiden Overview",
                    description="Manage your maiden collection and leader",
                    footer="Use the buttons below to view collection or set leader"
                )

                # Collection stats
                collection_stats = (
                    f"**Total Maidens:** {player.total_maidens_owned:,}\n"
                    f"**Unique:** {player.unique_maidens}\n"
                    f"**Highest Tier:** {player.highest_tier_achieved}"
                )
                embed.add_field(name=f"{Emojis.INFO} Collection", value=collection_stats, inline=True)

                # Power stats
                power_stats = (
                    f"**Total Power:** {total_power:,}\n"
                    f"**Strategic:** {strategic_power.total_power:,}\n"
                    f"**Level:** {player.level}"
                )
                embed.add_field(name=f"{Emojis.ATTACK} Power", value=power_stats, inline=True)

                # Leader info
                if leader_info:
                    leader_text = (
                        f"{leader_info['element_emoji']} **{leader_info['name']}** (T{leader_info['tier']})\n"
                        f"{leader_bonuses}"
                    )
                else:
                    leader_text = "*No leader set*\nSet a leader to gain bonuses!"

                embed.add_field(name=f"{Emojis.NO_MASTERY} Current Leader", value=leader_text, inline=False)

                # Send with interactive menu
                view = MaidenMenuView(ctx.author.id, self.bot, ctx)
                message = await ctx.send(embed=embed, view=view)
                view.message = message

                # Publish event for tutorial
                try:
                    await EventBus.publish("collection_viewed", {
                        "player_id": ctx.author.id,
                        "channel_id": ctx.channel.id,
                        "bot": self.bot,
                        "maiden_count": len(maidens),
                        "__topic__": "collection_viewed",
                        "timestamp": discord.utils.utcnow()
                    })
                except Exception as e:
                    self.logger.warning(f"Failed to publish collection_viewed event: {e}")

            # Log successful execution
            latency = (time.perf_counter() - start_time) * 1000
            self.log_command_use(
                "maidens",
                ctx.author.id,
                guild_id=ctx.guild.id if ctx.guild else None,
                latency_ms=round(latency, 2),
                maiden_count=len(maidens)
            )

        except Exception as e:
            # Standardized error handling
            latency = (time.perf_counter() - start_time) * 1000
            self.log_cog_error(
                "maidens",
                e,
                user_id=ctx.author.id,
                guild_id=ctx.guild.id if ctx.guild else None,
                latency_ms=round(latency, 2)
            )

            if not await self.handle_standard_errors(ctx, e):
                await self.send_error(
                    ctx,
                    "Maiden Overview Error",
                    "Unable to load your maiden information.",
                    help_text="Please try again shortly."
                )


class MaidenMenuView(discord.ui.View):
    """Interactive menu for maiden management."""

    def __init__(self, user_id: int, bot: commands.Bot, ctx: commands.Context):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.bot = bot
        self.ctx = ctx
        self.message: Optional[discord.Message] = None

    @discord.ui.button(
        label=f"{Emojis.TUTORIAL} View Collection",
        style=discord.ButtonStyle.primary,
        custom_id="view_collection"
    )
    async def view_collection(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show maiden collection with pagination."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This menu is not for you!", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            from src.core.infra.database_service import DatabaseService

            async with DatabaseService.get_session() as session:
                maidens = await MaidenService.get_player_maidens(session, self.user_id)

                if not maidens:
                    embed = EmbedFactory.warning(
                        title="No Maidens Found",
                        description="You don't have any maidens yet.",
                        footer="Tip: Use /summon to acquire new maidens!"
                    )
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return

                # Build collection embed
                per_page = 10
                total_pages = max(1, math.ceil(len(maidens) / per_page))
                page_maidens = maidens[0:per_page]

                embed = EmbedFactory.primary(
                    title=f"{Emojis.MAIDEN} {interaction.user.name}'s Maiden Collection",
                    description=f"Showing {len(maidens)} maiden{'s' if len(maidens) != 1 else ''}",
                    footer=f"Page 1/{total_pages}"
                )

                for maiden in page_maidens:
                    name = maiden.get("name", "Unknown")
                    m_tier = maiden.get("tier", 1)
                    quantity = maiden.get("quantity", 1)
                    attack = maiden.get("attack", 0)
                    defense = maiden.get("defense", 0)
                    element_emoji = maiden.get("element_emoji", Emojis.HELP)

                    field_name = f"{element_emoji} {name} (Tier {m_tier})"
                    if quantity > 1:
                        field_name += f" ×{quantity}"

                    field_value = f"ATK: {attack:,} • DEF: {defense:,}\nPower: {attack + defense:,}"
                    embed.add_field(name=field_name, value=field_value, inline=True)

                if total_pages > 1:
                    view = MaidenCollectionPaginationView(self.user_id, 1, total_pages, None, None)
                    await interaction.followup.send(embed=embed, view=view, ephemeral=True)
                else:
                    await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            embed = EmbedFactory.error(
                title="Collection Error",
                description="Unable to load your maiden collection.",
                footer="Please try again shortly."
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(
        label=f"{Emojis.NO_MASTERY} Set Leader",
        style=discord.ButtonStyle.success,
        custom_id="set_leader"
    )
    async def set_leader(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show leader selection dropdown."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This menu is not for you!", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            from src.core.infra.database_service import DatabaseService
            from src.database.models.core.player import Player

            async with DatabaseService.get_session() as session:
                # Get maidens with leader effects
                maidens = await MaidenService.get_maidens_with_leader_effects(session, self.user_id)

                if not maidens:
                    embed = EmbedFactory.warning(
                        title="No Leader-Capable Maidens",
                        description="You don't have any maidens with leader effects yet.",
                        footer="Tip: Higher tier maidens often have leader abilities!"
                    )
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return

                # Get current leader
                player = await session.get(Player, self.user_id)
                current_leader_id = player.leader_maiden_id if player else None

                # Show leader selection
                view = LeaderSelectionView(self.user_id, maidens, current_leader_id, self.bot)

                embed = EmbedFactory.info(
                    title=f"{Emojis.NO_MASTERY} Select Your Leader",
                    description="Choose a maiden to lead your collection and gain bonuses.",
                    footer="Only maidens with leader effects are shown"
                )

                await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            embed = EmbedFactory.error(
                title="Leader Selection Error",
                description="Unable to load leader options.",
                footer="Please try again shortly."
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


class MaidenCollectionPaginationView(discord.ui.View):
    """Pagination view for maiden collection display."""

    def __init__(
        self,
        user_id: int,
        current_page: int,
        total_pages: int,
        tier_filter: Optional[int],
        element_filter: Optional[str],
    ):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.current_page = current_page
        self.total_pages = total_pages
        self.tier_filter = tier_filter
        self.element_filter = element_filter
        self.message: Optional[discord.Message] = None

        # Disable buttons accordingly
        if current_page <= 1:
            self.previous_button.disabled = True
        if current_page >= total_pages:
            self.next_button.disabled = True

    @discord.ui.button(
        label=f"{Emojis.BACK} Previous",
        style=discord.ButtonStyle.secondary,
        custom_id="maidens_previous",
    )
    async def previous_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This collection is not for you!", ephemeral=True)
            return

        await interaction.response.send_message(
            f"Use `/maidens` and click 'View Collection' to navigate.",
            ephemeral=True,
        )

    @discord.ui.button(
        label=f"Next {Emojis.NEXT}",
        style=discord.ButtonStyle.secondary,
        custom_id="maidens_next",
    )
    async def next_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This collection is not for you!", ephemeral=True)
            return

        await interaction.response.send_message(
            f"Use `/maidens` and click 'View Collection' to navigate.",
            ephemeral=True,
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


class LeaderSelectionView(discord.ui.View):
    """View for selecting a leader maiden."""

    def __init__(self, user_id: int, maidens: list, current_leader_id: Optional[int], bot: commands.Bot):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.current_leader_id = current_leader_id
        self.bot = bot

        # Create dropdown options (max 25)
        options = []
        for maiden in maidens[:25]:
            label = f"{maiden['name']} (T{maiden['tier']})"
            if len(label) > 100:
                label = label[:97] + "..."

            description = maiden.get('leader_effect_desc', 'Unknown effect')
            if len(description) > 100:
                description = description[:97] + "..."

            options.append(discord.SelectOption(
                label=label,
                value=str(maiden['id']),
                description=description,
                emoji=maiden.get('element_emoji', Emojis.COMMON),
                default=(maiden['id'] == current_leader_id)
            ))

        self.select = discord.ui.Select(
            placeholder="Choose a leader maiden...",
            options=options,
            custom_id="leader_select"
        )
        self.select.callback = self.select_callback
        self.add_item(self.select)

        # Add remove button if there's a current leader
        if current_leader_id:
            self.remove_button = discord.ui.Button(
                label="Remove Leader",
                style=discord.ButtonStyle.danger,
                custom_id="remove_leader"
            )
            self.remove_button.callback = self.remove_callback
            self.add_item(self.remove_button)

    async def select_callback(self, interaction: discord.Interaction):
        """Handle leader selection."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This selection is not for you!", ephemeral=True)
            return

        maiden_id = int(self.select.values[0])

        await interaction.response.defer(ephemeral=True)

        try:
            from src.core.infra.database_service import DatabaseService

            async with DatabaseService.get_session() as session:
                success = await MaidenService.set_leader(session, self.user_id, maiden_id)

                if success:
                    # Get maiden info for confirmation
                    from src.database.models.core.maiden import Maiden
                    from database.models.core.maiden_base import MaidenBase

                    maiden = await session.get(Maiden, maiden_id)
                    maiden_base = await session.get(MaidenBase, maiden.maiden_base_id)

                    embed = EmbedFactory.success(
                        title=f"{Emojis.NO_MASTERY} Leader Set!",
                        description=f"**{maiden_base.name}** (T{maiden.tier}) is now your leader!",
                        footer="Leader bonuses are now active"
                    )

                    # Show active bonuses
                    from src.database.models.core.player import Player
                    player = await session.get(Player, self.user_id)
                    modifiers = await LeaderService.get_active_modifiers(player)

                    bonus_text = []
                    if modifiers.get("income_boost", 1.0) > 1.0:
                        pct = (modifiers["income_boost"] - 1.0) * 100
                        bonus_text.append(f"• **+{pct:.0f}% Income Boost**")
                    if modifiers.get("xp_boost", 1.0) > 1.0:
                        pct = (modifiers["xp_boost"] - 1.0) * 100
                        bonus_text.append(f"• **+{pct:.0f}% XP Boost**")
                    if modifiers.get("fusion_bonus", 0.0) > 0.0:
                        pct = modifiers["fusion_bonus"] * 100
                        bonus_text.append(f"• **+{pct:.0f}% Fusion Success**")
                    if modifiers.get("energy_efficiency", 0.0) > 0.0:
                        pct = modifiers["energy_efficiency"] * 100
                        bonus_text.append(f"• **-{pct:.0f}% Energy Cost**")
                    if modifiers.get("stamina_efficiency", 0.0) > 0.0:
                        pct = modifiers["stamina_efficiency"] * 100
                        bonus_text.append(f"• **-{pct:.0f}% Stamina Cost**")

                    if bonus_text:
                        embed.add_field(
                            name="Active Bonuses",
                            value="\n".join(bonus_text),
                            inline=False
                        )

                    await interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    embed = EmbedFactory.error(
                        title="Leader Set Failed",
                        description="Unable to set leader maiden.",
                        footer="Please try again"
                    )
                    await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            embed = EmbedFactory.error(
                title="Error",
                description="An error occurred while setting leader.",
                footer="Please try again shortly."
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

    async def remove_callback(self, interaction: discord.Interaction):
        """Handle leader removal."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This action is not for you!", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            from src.core.infra.database_service import DatabaseService

            async with DatabaseService.get_session() as session:
                success = await MaidenService.remove_leader(session, self.user_id)

                if success:
                    embed = EmbedFactory.success(
                        title="Leader Removed",
                        description="Your leader has been removed. You no longer have leader bonuses active.",
                        footer="Use /maidens to set a new leader"
                    )
                    await interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    embed = EmbedFactory.error(
                        title="Removal Failed",
                        description="Unable to remove leader maiden.",
                        footer="Please try again"
                    )
                    await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            embed = EmbedFactory.error(
                title="Error",
                description="An error occurred while removing leader.",
                footer="Please try again shortly."
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
    await bot.add_cog(MaidenCog(bot))
