"""
Unified player management system.

Consolidates registration, profile viewing, stat allocation, and transaction history
into a single cohesive player management cog.

RIKI LAW Compliance:
    - All business logic delegated to services (Article I.7)
    - BaseCog pattern for standardized error handling
    - Read-only operations use no locks (Article I.11)
    - State modifications use pessimistic locking (Article I.1)
    - Transaction logging via services (Article II)
    - Specific exception handling (Article I.5)
"""

import discord
from discord.ext import commands
from typing import Optional, Dict, Any

from src.core.bot.base_cog import BaseCog
from src.core.infra.database_service import DatabaseService
from src.modules.player.service import PlayerService
from src.modules.player.transaction_service import TransactionService
from src.modules.player.allocation_logic import AllocationService
from src.modules.resource.service import ResourceService
from src.modules.combat.service import CombatService
from src.modules.ascension.token_logic import TokenService
from src.modules.ascension.constants import get_token_emoji, get_token_display_name
from src.modules.exploration.mastery_logic import MasteryService
from src.modules.exploration.constants import RELIC_TYPES
from src.modules.tutorial.service import TutorialService
from src.database.models.core.player import Player
from src.database.models.economy.transaction_log import TransactionLog
from src.core.config.config_manager import ConfigManager
from src.core.infra.transaction_logger import TransactionLogger
from src.core.event.event_bus import EventBus
from src.core.exceptions import (
    PlayerNotFoundError,
    ValidationError,
    DatabaseError,
    InvalidOperationError
)
from src.utils.decorators import ratelimit
from src.utils.embed_builder import EmbedBuilder
from src.core.constants import MAX_POINTS_PER_STAT
from src.core.validation import InputValidator


def _safe_value(text: str, limit: int = 1024) -> str:
    """Truncate text to Discord field limits."""
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _as_dict(value: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Safely convert value to dict."""
    return value if isinstance(value, dict) else {}


def _fusion_success_rate(player: Player) -> float:
    """Calculate fusion success rate percentage."""
    method = getattr(player, "calculate_fusion_success_rate", None)
    if callable(method):
        try:
            rate = float(method())
            return max(0.0, min(rate, 100.0))
        except Exception:
            pass

    stats = _as_dict(getattr(player, "stats", None))
    successes = int(stats.get("fusions_successful", 0))
    total = int(getattr(player, "total_fusions", 0)) or int(stats.get("fusions_total", 0)) or 0

    if total <= 0:
        return 0.0

    return round((successes / total) * 100.0, 1)


class PlayerCog(BaseCog):
    """
    Unified player management system.

    Handles player registration, profile viewing, stat allocation,
    and transaction history through a cohesive interface.

    Commands:
        /register (rr) - Create your RIKI RPG account
        /me (rme, profile, mystats, ms, stats) - View player profile
        /allocate (alloc, ralloc, rallocate) - Allocate stat points
        /transactions (rt, rtrans) - View transaction history
    """

    def __init__(self, bot: commands.Bot, *, support_url: str = "https://discord.gg/yourserver"):
        super().__init__(bot, "PlayerCog")
        self.support_url = support_url

    # ===============================================================
    # REGISTRATION COMMAND
    # ===============================================================

    @commands.command(
        name="register",
        aliases=["rr", "rregister", "rikiregister"],
        description="Register your RIKI RPG account and begin your journey"
    )
    async def register(self, ctx: commands.Context):
        """Register a new player account with ToS acknowledgement."""
        await self.safe_defer(ctx)

        try:
            async with self.get_session() as session:
                existing = await session.get(Player, ctx.author.id, with_for_update=True)
                if existing:
                    embed = EmbedBuilder.warning(
                        title="Already Registered",
                        description=(
                            f"Welcome back, {ctx.author.mention}!\n"
                            f"You registered on <t:{int(existing.created_at.timestamp())}:D>."
                        ),
                        footer=f"Level {existing.level} • {existing.total_maidens_owned} Maidens"
                    )
                    embed.add_field(
                        name="Next Steps",
                        value="`/me` to view profile • `/pray` to gain grace • `/summon` to pull maidens",
                        inline=False
                    )
                    await ctx.send(embed=embed)
                    return

                starting_rikis = ConfigManager.get("player.starting_rikis", 1000)
                starting_grace = ConfigManager.get("player.starting_grace", 5)
                starting_energy = ConfigManager.get("player.starting_max_energy", 100)
                starting_stamina = ConfigManager.get("player.starting_max_stamina", 50)

                new_player = Player(
                    discord_id=ctx.author.id,
                    username=ctx.author.name,
                    rikis=starting_rikis,
                    grace=starting_grace,
                    energy=starting_energy,
                    max_energy=starting_energy,
                    stamina=starting_stamina,
                    max_stamina=starting_stamina,
                    tutorial_completed=False,
                    tutorial_step=0
                )

                session.add(new_player)
                await session.flush()

                await TransactionLogger.log_transaction(
                    session=session,
                    player_id=ctx.author.id,
                    transaction_type="player_registered",
                    details={
                        "username": ctx.author.name,
                        "starting_rikis": starting_rikis,
                        "starting_grace": starting_grace,
                        "starting_energy": starting_energy,
                        "starting_stamina": starting_stamina
                    },
                    context=f"command:/{ctx.command.name} guild:{ctx.guild.id if ctx.guild else 'DM'}"
                )

                await session.commit()

            # Public welcome + ToS post
            embed = EmbedBuilder.success(
                title="🎉 Welcome to RIKI RPG!",
                description=(
                    f"{ctx.author.mention} has joined the world of RIKI!\n\n"
                    "By registering, you agree to follow our **Terms of Service** and community rules.\n"
                    "Be kind, no cheating, and have fun."
                ),
                footer="Use /help for all commands"
            )
            embed.add_field(
                name="📜 Terms of Service",
                value="Review and accept to continue using the bot.",
                inline=False
            )
            embed.add_field(
                name="💬 Support",
                value=f"[Join our Support Server]({self.support_url}) for help, events, and announcements.",
                inline=False
            )
            embed.add_field(
                name="🚀 First Steps",
                value="`/pray` to gain grace • `/summon` to pull maidens • `/me` to view your profile",
                inline=False
            )

            view = TosAgreeView(player_id=ctx.author.id, support_url=self.support_url)
            message = await ctx.send(embed=embed, view=view)
            view.message = message

            self.log_command_use("register", ctx.author.id, guild_id=ctx.guild.id if ctx.guild else None)

        except ValidationError as e:
            await self.send_error(ctx, "Registration Failed", str(e), help_text="Contact support.")
        except DatabaseError as e:
            self.log_cog_error("register", e, user_id=ctx.author.id)
            await self.send_error(ctx, "Registration Error", "System error during registration.", help_text="Try again shortly.")
        except Exception as e:
            self.log_cog_error("register", e, user_id=ctx.author.id)
            if not await self.handle_standard_errors(ctx, e):
                await self.send_error(ctx, "Something Went Wrong", "Unexpected error.", help_text="Please try again later.")

    # ===============================================================
    # PROFILE COMMAND
    # ===============================================================

    @commands.command(
        name="me",
        aliases=["rme", "rstats", "rikistats"],
        description="View your player profile and statistics"
    )
    @ratelimit(
        uses=ConfigManager.get("rate_limits.player.profile.uses", 15),
        per_seconds=ConfigManager.get("rate_limits.player.profile.period", 60),
        command_name="me"
    )
    async def me(self, ctx: commands.Context, user: Optional[discord.Member] = None):
        """
        Display unified player profile with key metrics.

        Shows brief summary with interactive buttons for detailed views and actions.
        """
        await self.safe_defer(ctx)

        target = user or ctx.author
        is_self = target == ctx.author

        try:
            async with self.get_session() as session:
                player: Optional[Player] = await PlayerService.get_player_with_regen(
                    session, target.id, lock=False
                )

                if not player:
                    if is_self:
                        await self.send_error(
                            ctx,
                            "Not Registered",
                            "You haven't registered yet!",
                            help_text="Use `/register` to create your account."
                        )
                    else:
                        await self.send_error(
                            ctx,
                            "Player Not Found",
                            f"{target.mention} hasn't registered yet.",
                            help_text="They can use /register to join RIKI RPG."
                        )
                    return

                # Get combat power
                total_power = await CombatService.calculate_total_power(
                    session, player.discord_id, include_leader_bonus=True
                )

                # Get strategic power
                strategic = await CombatService.calculate_strategic_power(
                    session, player.discord_id, include_leader_bonus=True
                )

            # Build streamlined profile embed
            level = int(getattr(player, "level", 0))
            experience = int(getattr(player, "experience", 0))
            created_at = getattr(player, "created_at", None)
            created_ts = int(created_at.timestamp()) if created_at else None

            title = f"👤 {target.display_name}"
            desc_parts = [f"Level {level} • {experience:,} XP"]
            if created_ts:
                desc_parts.append(f"Playing since <t:{created_ts}:D>")

            embed = EmbedBuilder.primary(
                title=title,
                description=" • ".join(desc_parts),
                footer=f"Player ID: {player.discord_id}"
            )
            embed.timestamp = discord.utils.utcnow()

            # === 1. TOTAL POWER ===
            embed.add_field(
                name="⚔️ Total Power",
                value=f"**{total_power:,}**\n*All {player.total_maidens_owned} maidens*",
                inline=True
            )

            # === 2. RIKIS ===
            rikis = int(getattr(player, "rikis", 0))
            embed.add_field(
                name="💰 Rikis",
                value=f"**{rikis:,}**",
                inline=True
            )

            # === 3. RIKI GEMS ===
            gems = int(getattr(player, "riki_gems", 0))
            embed.add_field(
                name="💎 Riki Gems",
                value=f"**{gems:,}**",
                inline=True
            )

            # === 4. GRACE ===
            grace = int(getattr(player, "grace", 0))
            embed.add_field(
                name="🙏 Grace",
                value=f"**{grace:,}**",
                inline=True
            )

            # === 5. COLLECTION STATS ===
            total_maidens_owned = int(getattr(player, "total_maidens_owned", 0))
            unique_maidens = int(getattr(player, "unique_maidens", 0))
            highest_tier_achieved = getattr(player, "highest_tier_achieved", "—")

            embed.add_field(
                name="🎴 Collection",
                value=(
                    f"**Total:** {total_maidens_owned:,}\n"
                    f"**Unique:** {unique_maidens:,}\n"
                    f"**Max Tier:** {highest_tier_achieved}"
                ),
                inline=True
            )

            # === 6. PROGRESSION ===
            embed.add_field(
                name="🗼 Progression",
                value=(
                    f"**Ascension:** Floor {player.highest_floor_ascended}\n"
                    f"**Exploration:** Sector {player.highest_sector_reached}"
                ),
                inline=True
            )

            # Set thumbnail
            if target.display_avatar:
                embed.set_thumbnail(url=target.display_avatar.url)

            # Add interactive menu with conditional buttons
            view = UnifiedProfileView(
                ctx.author.id,
                is_self,
                player,
                self.bot,
                target
            )
            message = await ctx.send(embed=embed, view=view)
            view.message = message

            self.log_command_use("me", ctx.author.id, guild_id=ctx.guild.id if ctx.guild else None, viewed_user=target.id)

        except Exception as e:
            self.log_cog_error("me", e, user_id=ctx.author.id)
            if not await self.handle_standard_errors(ctx, e):
                await self.send_error(
                    ctx,
                    "Profile Error",
                    "Unable to load profile data.",
                    help_text="Please try again shortly."
                )

    # ===============================================================
    # ALLOCATION COMMAND
    # ===============================================================

    @commands.command(
        name="allocate",
        aliases=["rall", "rallocate", "rikiallocate"],
        description="Allocate stat points to Energy, Stamina, or HP"
    )
    @ratelimit(
        uses=ConfigManager.get("rate_limits.player.allocate.uses", 10),
        per_seconds=ConfigManager.get("rate_limits.player.allocate.period", 60),
        command_name="allocate"
    )
    async def allocate(self, ctx: commands.Context):
        """View stat allocation interface."""
        await self.safe_defer(ctx)

        try:
            async with self.get_session() as session:
                player = await self.require_player(ctx, session, ctx.author.id)
                if not player:
                    return

                # Check if player has points
                if player.stat_points_available == 0:
                    embed = EmbedBuilder.warning(
                        title="No Points Available",
                        description="You don't have any stat points to allocate!",
                        footer="Gain points each time you level up"
                    )

                    # Show current allocation
                    spent = player.stat_points_spent
                    total_spent = spent["energy"] + spent["stamina"] + spent["hp"]

                    embed.add_field(
                        name="📊 Current Stats",
                        value=(
                            f"⚡ **Energy:** {player.max_energy} "
                            f"({spent['energy']} points)\n"
                            f"💪 **Stamina:** {player.max_stamina} "
                            f"({spent['stamina']} points)\n"
                            f"❤️ **HP:** {player.max_hp} "
                            f"({spent['hp']} points)\n\n"
                            f"**Total Allocated:** {total_spent} points"
                        ),
                        inline=False
                    )

                    embed.add_field(
                        name="💡 Gain More Points",
                        value="Level up to gain 5 allocation points!",
                        inline=False
                    )

                    await ctx.send(embed=embed, ephemeral=True)
                    return

                # Show allocation UI
                embed = EmbedBuilder.primary(
                    title="📊 Stat Allocation",
                    description=(
                        f"**Available Points:** {player.stat_points_available}\n\n"
                        "Choose how to allocate your stat points!"
                    ),
                    footer="Gain points per level | Full refresh on allocation"
                )

                # Current stats
                spent = player.stat_points_spent
                embed.add_field(
                    name="Current Max Stats",
                    value=(
                        f"⚡ Energy: {player.max_energy}\n"
                        f"💪 Stamina: {player.max_stamina}\n"
                        f"❤️ HP: {player.max_hp}"
                    ),
                    inline=True
                )

                # Total spent
                total_spent = spent["energy"] + spent["stamina"] + spent["hp"]
                embed.add_field(
                    name="Points Invested",
                    value=(
                        f"⚡ {spent['energy']} in Energy\n"
                        f"💪 {spent['stamina']} in Stamina\n"
                        f"❤️ {spent['hp']} in HP\n"
                        f"**Total:** {total_spent} points"
                    ),
                    inline=True
                )

                # Recommended builds
                builds = AllocationService.get_recommended_builds(player.level)
                build_text = ""
                for name, build in builds.items():
                    build_text += (
                        f"**{name.title()}**\n"
                        f"{build['description']}\n"
                        f"⚡{build['energy']} 💪{build['stamina']} ❤️{build['hp']}\n"
                        f"✅ {build['pros']}\n"
                        f"❌ {build['cons']}\n\n"
                    )

                embed.add_field(
                    name="📋 Recommended Builds",
                    value=build_text,
                    inline=False
                )

                view = AllocationView(ctx.author.id, player.stat_points_available)
                message = await ctx.send(embed=embed, view=view)
                view.message = message

                self.log_command_use("allocate", ctx.author.id, guild_id=ctx.guild.id if ctx.guild else None)

        except Exception as e:
            self.log_cog_error("allocate", e, user_id=ctx.author.id)
            if not await self.handle_standard_errors(ctx, e):
                await self.send_error(
                    ctx,
                    "Allocation Error",
                    "Failed to load allocation interface.",
                    help_text="Please try again."
                )

    # ===============================================================
    # TRANSACTIONS COMMAND
    # ===============================================================

    @commands.command(
        name="transactions",
        aliases=["rlog", "rtransactions", "rikitransactions"],
        description="View recent resource transaction history"
    )
    @ratelimit(
        uses=ConfigManager.get("rate_limits.player.profile.uses", 15),
        per_seconds=ConfigManager.get("rate_limits.player.profile.period", 60),
        command_name="transactions"
    )
    async def transactions(self, ctx: commands.Context, limit: Optional[int] = 10):
        """Display the player's recent resource transactions."""
        await self.safe_defer(ctx)
        limit = max(1, min(limit or 10, 20))

        try:
            async with self.get_session() as session:
                player = await self.require_player(ctx, session, ctx.author.id)
                if not player:
                    return

                # Get recent transactions via service
                logs = await TransactionService.get_recent_transactions(
                    session, ctx.author.id, limit=limit
                )

            if not logs:
                await self.send_info(
                    ctx,
                    "📜 No Transactions",
                    "You have no resource transaction history yet."
                )
                return

            embed = discord.Embed(
                title=f"📜 Resource Transactions (Last {len(logs)})",
                description="Recent rikis, grace, and gem changes",
                color=0x2C2D31
            )

            for log in logs:
                details = log.details or {}
                tx_type = log.transaction_type.replace("resource_", "").replace("_", " ").title()

                granted = details.get("granted") or details.get("resources_granted") or {}
                consumed = details.get("consumed") or details.get("resources_consumed") or {}
                mods = details.get("modifiers_applied") or {}

                # Build transaction lines
                lines = []
                lines.extend([f"+{v:,} {k}" for k, v in granted.items() if v > 0])
                lines.extend([f"-{v:,} {k}" for k, v in consumed.items() if v > 0])

                # Add modifier info
                bonus_lines = []
                if mods.get("income_boost", 1.0) > 1.0:
                    bonus_lines.append(f"💰 +{(mods['income_boost'] - 1.0) * 100:.0f}% income")
                if mods.get("xp_boost", 1.0) > 1.0:
                    bonus_lines.append(f"📈 +{(mods['xp_boost'] - 1.0) * 100:.0f}% XP")

                # Timestamp
                ts = int(log.timestamp.timestamp())
                when = f"<t:{ts}:R>"

                field_value = (
                    ("\n".join(lines) or "No resource change")
                    + (f"\n✨ {'; '.join(bonus_lines)}" if bonus_lines else "")
                    + f"\n*{when}*"
                )

                embed.add_field(
                    name=f"{tx_type}",
                    value=_safe_value(field_value),
                    inline=False
                )

            await ctx.send(embed=embed)

            self.log_command_use("transactions", ctx.author.id, guild_id=ctx.guild.id if ctx.guild else None)

        except Exception as e:
            self.log_cog_error("transactions", e, user_id=ctx.author.id)
            if not await self.handle_standard_errors(ctx, e):
                await self.send_error(
                    ctx,
                    "Transaction Error",
                    "Unable to fetch transaction history.",
                    help_text="Please try again shortly."
                )


# ===============================================================
# VIEWS AND INTERACTIVE COMPONENTS
# ===============================================================

class TosAgreeView(discord.ui.View):
    """Public post with buttons; only the registering user can 'Agree'."""

    def __init__(self, player_id: int, support_url: str):
        super().__init__(timeout=600)
        self.player_id = player_id
        self.message: Optional[discord.Message] = None

        # Update support button URL
        for item in self.children:
            if isinstance(item, discord.ui.Button) and item.style == discord.ButtonStyle.link:
                item.url = support_url

    @discord.ui.button(label="✅ I Agree", style=discord.ButtonStyle.success, custom_id="tos_agree")
    async def agree(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("This button is not for you!", ephemeral=True)
            return

        async with DatabaseService.get_transaction() as session:
            player = await session.get(Player, self.player_id, with_for_update=True)
            if player:
                done = await TutorialService.complete_step(session, player, "tos_agreed")
                await session.commit()

                # Announce publicly in the same channel
                try:
                    channel = interaction.channel
                    if channel and done:
                        embed = EmbedBuilder.success(
                            title=f"🎉 Tutorial Complete: {done['title']}",
                            description=done["congrats"],
                            footer="You're all set — try `/pray` next!"
                        )
                        await channel.send(embed=embed)
                        # Plain text reward line (ToS likely has no rewards)
                        rk = done["reward"].get("rikis", 0)
                        gr = done["reward"].get("grace", 0)
                        if rk or gr:
                            parts = []
                            if rk:
                                parts.append(f"+{rk} rikis")
                            if gr:
                                parts.append(f"+{gr} grace")
                            await channel.send(f"You received {' and '.join(parts)} as a tutorial reward!")
                except Exception:
                    pass

                # Also publish the tutorial event with topic metadata
                try:
                    await EventBus.publish("tos_agreed", {
                        "player_id": self.player_id,
                        "channel_id": interaction.channel_id,
                        "__topic__": "tos_agreed"
                    })
                except Exception:
                    pass

        # Private confirmation (so the clicker gets immediate feedback)
        await interaction.response.send_message(
            "Thanks! You've accepted the ToS. Start with `/pray`, then try `/summon`.",
            ephemeral=True
        )

    @discord.ui.button(label="🔗 Support Server", style=discord.ButtonStyle.link, url="https://discord.gg/yourserver")
    async def support(self, *_):
        pass

    async def on_timeout(self):
        """Disable all buttons visually when the view expires."""
        for item in self.children:
            if isinstance(item, discord.ui.Button) and item.style != discord.ButtonStyle.link:
                item.disabled = True

        try:
            if self.message:
                await self.message.edit(view=self)
        except discord.HTTPException:
            pass


class UnifiedProfileView(discord.ui.View):
    """Interactive menu for unified profile with conditional buttons."""

    def __init__(
        self,
        user_id: int,
        is_self: bool,
        player: Player,
        bot: commands.Bot,
        target: discord.Member
    ):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.is_self = is_self
        self.player = player
        self.bot = bot
        self.target = target
        self.message: Optional[discord.Message] = None

        # Remove action buttons if viewing someone else
        if not is_self:
            self.remove_item(self.allocate_button)
            self.remove_item(self.pray_button)
            self.remove_item(self.summon_button)
            # Mail button will be added conditionally, so check if it exists before removing
            try:
                self.remove_item(self.mail_button)
            except ValueError:
                pass  # Button not in view
        else:
            # Remove allocate button if no points available
            if player.stat_points_available <= 0:
                self.remove_item(self.allocate_button)
            else:
                # Update button label with points count
                self.allocate_button.label = f"⚗️ Allocate Points (+{player.stat_points_available} available!)"

            # TODO: Add mail button conditionally when mail system exists
            # For now, always remove it
            try:
                self.remove_item(self.mail_button)
            except ValueError:
                pass

    def set_message(self, message: discord.Message):
        self.message = message

    # === ROW 1: Advanced Stats ===
    @discord.ui.button(
        label="📊 Advanced Stats",
        style=discord.ButtonStyle.primary,
        custom_id="advanced_stats",
        row=0
    )
    async def advanced_stats_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        """Show comprehensive statistics in ephemeral message."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This button isn't for you!",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            # Build comprehensive stats embed (from old stats_cog.py)
            async with DatabaseService.get_transaction() as session:
                # Get token inventory
                token_inventory = await TokenService.get_player_tokens(
                    session, self.player.discord_id
                )

                # Get mastery bonuses
                mastery_bonuses = await MasteryService.get_active_bonuses(
                    session, self.player.discord_id
                )

                # Get combat power
                total_power = await CombatService.calculate_total_power(
                    session, self.player.discord_id, include_leader_bonus=True
                )

                strategic = await CombatService.calculate_strategic_power(
                    session, self.player.discord_id, include_leader_bonus=True
                )

            embed = EmbedBuilder.info(
                title=f"📊 Advanced Statistics for {self.target.display_name}",
                description=f"Level {self.player.level} • Comprehensive Analytics",
                footer=f"Player ID: {self.player.discord_id}"
            )
            embed.timestamp = discord.utils.utcnow()

            # === RESOURCES & STAT ALLOCATION ===
            spent = self.player.stat_points_spent
            total_spent = spent["energy"] + spent["stamina"] + spent["hp"]

            embed.add_field(
                name="⚡ Resources & Allocation",
                value=_safe_value(
                    f"**Energy:** {self.player.energy}/{self.player.max_energy} (+{spent['energy']} pts)\n"
                    f"**Stamina:** {self.player.stamina}/{self.player.max_stamina} (+{spent['stamina']} pts)\n"
                    f"**HP:** {self.player.hp}/{self.player.max_hp} (+{spent['hp']} pts)\n"
                    f"*Available: {self.player.stat_points_available} pts*"
                ),
                inline=True
            )

            # === COMBAT POWER BREAKDOWN ===
            embed.add_field(
                name="⚔️ Combat Power",
                value=_safe_value(
                    f"**Total Power:** {total_power:,}\n"
                    f"*(All {self.player.total_maidens_owned} maidens)*\n\n"
                    f"**Strategic Power:** {strategic.total_power:,}\n"
                    f"**Strategic Defense:** {strategic.total_defense:,}\n"
                    f"*(Best 6, one per element)*"
                ),
                inline=True
            )

            # === TOKEN INVENTORY ===
            if any(qty > 0 for qty in token_inventory.values()):
                token_lines = []
                for token_type in ["bronze", "silver", "gold", "platinum", "diamond"]:
                    qty = token_inventory.get(token_type, 0)
                    if qty > 0:
                        emoji = get_token_emoji(token_type)
                        name = get_token_display_name(token_type)
                        token_lines.append(f"{emoji} **{name}:** {qty}")

                if token_lines:
                    embed.add_field(
                        name="🎫 Token Inventory",
                        value=_safe_value("\n".join(token_lines)),
                        inline=True
                    )

            # === MASTERY BONUSES ===
            if mastery_bonuses:
                bonus_lines = []
                for relic_type, value in mastery_bonuses.items():
                    if value > 0:
                        relic_info = RELIC_TYPES.get(relic_type)
                        if relic_info:
                            icon = relic_info["icon"]
                            name = relic_info["name"]

                            # Format based on type
                            if relic_type in ["shrine_income", "combine_rate", "attack_boost",
                                            "defense_boost", "xp_gain", "stamina_regen", "energy_regen"]:
                                bonus_lines.append(f"{icon} **{name}:** +{value:.1f}%")
                            else:
                                bonus_lines.append(f"{icon} **{name}:** +{value:.0f}")

                if bonus_lines:
                    embed.add_field(
                        name="🏆 Mastery Bonuses",
                        value=_safe_value("\n".join(bonus_lines)),
                        inline=False
                    )

            # === COLLECTION ===
            embed.add_field(
                name="🎴 Collection",
                value=_safe_value(
                    f"**Total Maidens:** {self.player.total_maidens_owned:,}\n"
                    f"**Unique Maidens:** {self.player.unique_maidens:,}\n"
                    f"**Highest Tier:** {self.player.highest_tier_achieved}"
                ),
                inline=True
            )

            # === CURRENCY ===
            embed.add_field(
                name="💰 Currency",
                value=_safe_value(
                    f"**Rikis:** {self.player.rikis:,}\n"
                    f"**Grace:** {self.player.grace:,}\n"
                    f"**Gems:** {self.player.riki_gems:,}"
                ),
                inline=True
            )

            # === PROGRESSION ===
            embed.add_field(
                name="🗼 Progression",
                value=_safe_value(
                    f"**Ascension:** Floor {self.player.highest_floor_ascended}\n"
                    f"**Exploration:** Sector {self.player.highest_sector_reached}\n"
                    f"**Experience:** {self.player.experience:,} XP"
                ),
                inline=True
            )

            # === SUMMON STATISTICS ===
            total_summons = int(getattr(self.player, "total_summons", 0))
            pity_counter = int(getattr(self.player, "pity_counter", 0))
            pity_percentage = (pity_counter / 90) * 100 if pity_counter > 0 else 0.0

            embed.add_field(
                name="✨ Summon Statistics",
                value=_safe_value(
                    f"**Total Summons:** {total_summons:,}\n"
                    f"**Pity Counter:** {pity_counter}/90 ({pity_percentage:.1f}%)"
                ),
                inline=True
            )

            # === FUSION STATISTICS ===
            total_fusions = int(getattr(self.player, "total_fusions", 0))
            success_rate = _fusion_success_rate(self.player)
            fusion_shards: Dict[str, int] = _as_dict(getattr(self.player, "fusion_shards", None))
            total_shards = int(sum(int(v or 0) for v in fusion_shards.values()))

            embed.add_field(
                name="⚗️ Fusion Statistics",
                value=_safe_value(
                    f"**Total Fusions:** {total_fusions:,}\n"
                    f"**Success Rate:** {success_rate:.1f}%\n"
                    f"**Fusion Shards:** {total_shards:,}"
                ),
                inline=True
            )

            # === PRAYER STATISTICS ===
            stats_json = _as_dict(getattr(self.player, "stats", None))
            prayers_performed = int(stats_json.get("prayers_performed", 0))
            has_charge = int(getattr(self.player, "prayer_charges", 0)) >= 1
            prayer_status = "✅ Ready!" if has_charge else "⏳ Regenerating"

            embed.add_field(
                name="🙏 Prayer Statistics",
                value=_safe_value(
                    f"**Total Prayers:** {prayers_performed:,}\n"
                    f"**Status:** {prayer_status}"
                ),
                inline=True
            )

            # === ECONOMY STATISTICS ===
            rikis_earned = int(stats_json.get("total_rikis_earned", 0))
            rikis_spent = int(stats_json.get("total_rikis_spent", 0))
            net_rikis = rikis_earned - rikis_spent

            embed.add_field(
                name="💹 Economy Statistics",
                value=_safe_value(
                    f"**Earned:** {rikis_earned:,} rikis\n"
                    f"**Spent:** {rikis_spent:,} rikis\n"
                    f"**Net:** {net_rikis:,} rikis"
                ),
                inline=False
            )

            # === TOP FUSION SHARDS ===
            if total_shards > 0:
                sorted_shards = sorted(
                    ((k, int(v or 0)) for k, v in fusion_shards.items()),
                    key=lambda x: x[1],
                    reverse=True
                )[:3]
                shard_text = "\n".join(
                    f"**{tier.replace('_', ' ').title()}:** {count:,}"
                    for tier, count in sorted_shards if count > 0
                ) or "No shards collected yet"

                embed.add_field(
                    name="🔷 Top Fusion Shards",
                    value=_safe_value(shard_text),
                    inline=True
                )

            # Set thumbnail
            if self.target.display_avatar:
                embed.set_thumbnail(url=self.target.display_avatar.url)

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception:
            embed = EmbedBuilder.error(
                title="Advanced Stats Error",
                description="Unable to load detailed statistics.",
                help_text="Please try again shortly."
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

    # === ROW 2 (Conditional): Allocate Points ===
    @discord.ui.button(
        label="⚗️ Allocate Points",
        style=discord.ButtonStyle.success,
        custom_id="allocate_points",
        row=1
    )
    async def allocate_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        """Link to allocation command."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This button isn't for you!",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"Use `/allocate` to spend your {self.player.stat_points_available} stat points!",
            ephemeral=True
        )

    # === ROW 2 (Conditional): Mail Button (Future Feature) ===
    @discord.ui.button(
        label="📬 Mail",
        style=discord.ButtonStyle.primary,
        custom_id="view_mail",
        row=1
    )
    async def mail_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        """Link to mail command (future feature)."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This button isn't for you!",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "Use `/mail` to check your messages! (Coming soon)",
            ephemeral=True
        )

    # === ROW 3: Quick Actions ===
    @discord.ui.button(
        label="🎴 Collection",
        style=discord.ButtonStyle.secondary,
        custom_id="view_collection",
        row=2
    )
    async def collection_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        """Link to maidens command."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This button isn't for you!",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "Use `/maidens` to view your collection!",
            ephemeral=True
        )

    @discord.ui.button(
        label="🙏 Pray",
        style=discord.ButtonStyle.secondary,
        custom_id="pray_action",
        row=2
    )
    async def pray_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        """Link to pray command."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This button isn't for you!",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "Use `/pray` to gain grace!",
            ephemeral=True
        )

    @discord.ui.button(
        label="✨ Summon",
        style=discord.ButtonStyle.secondary,
        custom_id="summon_action",
        row=2
    )
    async def summon_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        """Link to summon command."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This button isn't for you!",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "Use `/summon` to call new maidens!",
            ephemeral=True
        )

    async def on_timeout(self):
        """Disable all buttons on timeout."""
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


class AllocationView(discord.ui.View):
    """Interactive view for stat allocation."""

    def __init__(self, user_id: int, available_points: int):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.available_points = available_points
        self.message: Optional[discord.Message] = None

    def set_message(self, message: discord.Message):
        self.message = message

    @discord.ui.button(
        label="✏️ Allocate Points",
        style=discord.ButtonStyle.primary,
        custom_id="allocate_modal"
    )
    async def allocate_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        """Open allocation modal."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This allocation interface is not for you!",
                ephemeral=True
            )
            return

        modal = AllocationModal(self.user_id, self.available_points)
        await interaction.response.send_modal(modal)

    @discord.ui.button(
        label="📊 Preview Build",
        style=discord.ButtonStyle.secondary,
        custom_id="preview_build"
    )
    async def preview_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        """Preview recommended builds."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This allocation interface is not for you!",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "Use the recommended builds shown above as a guide! "
            "Click **Allocate Points** to customize your allocation.",
            ephemeral=True
        )

    async def on_timeout(self):
        """Disable buttons on timeout."""
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


class AllocationModal(discord.ui.Modal, title="Allocate Stat Points"):
    """Modal for stat point allocation input."""

    energy = discord.ui.TextInput(
        label="Energy Points",
        placeholder="0",
        default="0",
        required=False,
        max_length=3
    )

    stamina = discord.ui.TextInput(
        label="Stamina Points",
        placeholder="0",
        default="0",
        required=False,
        max_length=3
    )

    hp = discord.ui.TextInput(
        label="HP Points",
        placeholder="0",
        default="0",
        required=False,
        max_length=3
    )

    def __init__(self, user_id: int, available_points: int):
        super().__init__()
        self.user_id = user_id
        self.available_points = available_points

    async def on_submit(self, interaction: discord.Interaction):
        """Process allocation."""
        await interaction.response.defer()

        try:
            # Validate and parse input using InputValidator
            energy_pts = InputValidator.validate_non_negative_integer(
                self.energy.value or 0, "energy", max_value=MAX_POINTS_PER_STAT
            )
            stamina_pts = InputValidator.validate_non_negative_integer(
                self.stamina.value or 0, "stamina", max_value=MAX_POINTS_PER_STAT
            )
            hp_pts = InputValidator.validate_non_negative_integer(
                self.hp.value or 0, "hp", max_value=MAX_POINTS_PER_STAT
            )

            total = energy_pts + stamina_pts + hp_pts
            if total == 0:
                raise ValidationError("allocation", "Must allocate at least 1 point")

            if total > self.available_points:
                raise ValidationError(
                    "allocation",
                    f"Insufficient points. Have {self.available_points}, trying to spend {total}"
                )

            # Execute allocation
            async with DatabaseService.get_transaction() as session:
                player = await PlayerService.get_player_with_regen(
                    session, self.user_id, lock=True
                )

                result = await AllocationService.allocate_points(
                    session,
                    player,
                    energy=energy_pts,
                    stamina=stamina_pts,
                    hp=hp_pts
                )

                await session.commit()

            # Success embed
            embed = EmbedBuilder.success(
                title="✅ Stats Allocated!",
                description=f"Successfully invested {total} points"
            )

            # Show changes
            old_max = result["old_max_stats"]
            new_max = result["new_max_stats"]

            # Calculate actual gains
            energy_gain = new_max['max_energy'] - old_max['max_energy']
            stamina_gain = new_max['max_stamina'] - old_max['max_stamina']
            hp_gain = new_max['max_hp'] - old_max['max_hp']

            embed.add_field(
                name="New Max Stats",
                value=(
                    f"⚡ **Energy:** {new_max['max_energy']}" + (f" (+{energy_gain})" if energy_gain > 0 else "") + "\n"
                    f"💪 **Stamina:** {new_max['max_stamina']}" + (f" (+{stamina_gain})" if stamina_gain > 0 else "") + "\n"
                    f"❤️ **HP:** {new_max['max_hp']}" + (f" (+{hp_gain})" if hp_gain > 0 else "")
                ),
                inline=False
            )

            # Resources refreshed
            embed.add_field(
                name="💫 Resources Refreshed",
                value="All resources restored to new maximum values!",
                inline=False
            )

            # Remaining points
            if result["points_remaining"] > 0:
                embed.add_field(
                    name="Points Remaining",
                    value=f"{result['points_remaining']} unspent points",
                    inline=False
                )

            await interaction.edit_original_response(embed=embed, view=None)

        except ValueError as e:
            embed = EmbedBuilder.error(
                title="Invalid Input",
                description=str(e),
                help_text="Enter valid positive numbers for allocation."
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

        except InvalidOperationError as e:
            embed = EmbedBuilder.error(
                title="Allocation Failed",
                description=str(e)
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception:
            embed = EmbedBuilder.error(
                title="Allocation Error",
                description="An unexpected error occurred.",
                help_text="Please try again."
            )
            await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    """Required for Discord cog loading."""
    await bot.add_cog(PlayerCog(bot))
