"""
Unified player profile and statistics system.

Provides streamlined profile overview with detailed analytics behind interactive buttons.
Shows key metrics upfront with conditional action buttons based on player state.

RIKI LAW Compliance:
    - Read-only (no locks, Article I.11)
    - Player activity tracking (Article I.7)
    - Specific exception handling (Article I.5)
    - Command/Query separation (Article I.11)
"""

import discord
from discord.ext import commands
from typing import Optional, Dict, Any

from src.core.infra.database_service import DatabaseService
from src.features.player.service import PlayerService
from src.features.resource.service import ResourceService
from src.features.combat.service import CombatService
from src.features.ascension.token_service import TokenService
from src.features.ascension.constants import get_token_emoji, get_token_display_name
from src.features.exploration.mastery_service import MasteryService
from src.features.exploration.constants import RELIC_TYPES
from src.database.models.core.player import Player
from src.database.models.economy.transaction_log import TransactionLog
from src.core.exceptions import PlayerNotFoundError
from src.core.logging.logger import get_logger
from src.utils.decorators import ratelimit
from utils.embed_builder import EmbedBuilder
from sqlalchemy import select, desc

logger = get_logger(__name__)


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


class ProfileCog(commands.Cog):
    """
    Unified player profile system.

    Displays streamlined profile with key stats and interactive menu for
    detailed views and quick actions. Conditional buttons adapt to player state.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ===============================================================
    # Main Profile Command
    # ===============================================================
    @commands.hybrid_command(
        name="me",
        aliases=["rme", "profile", "mystats", "ms", "stats"],
        description="View your player profile and statistics"
    )
    @ratelimit(uses=10, per_seconds=60, command_name="me")
    async def me(self, ctx: commands.Context, user: Optional[discord.Member] = None):
        """
        Display unified player profile with key metrics.

        Shows brief summary with interactive buttons for detailed views and actions.
        """
        await ctx.defer()

        target = user or ctx.author
        is_self = target == ctx.author

        try:
            async with DatabaseService.get_transaction() as session:
                player: Optional[Player] = await PlayerService.get_player_with_regen(
                    session, target.id, lock=False
                )

                if not player:
                    if is_self:
                        embed = EmbedBuilder.error(
                            title="Not Registered",
                            description="You haven't registered yet!",
                            help_text="Use `/register` to create your account."
                        )
                    else:
                        embed = EmbedBuilder.error(
                            title="Player Not Found",
                            description=f"{target.mention} hasn't registered yet.",
                            footer="They can use /register to join RIKI RPG."
                        )
                    await ctx.send(embed=embed, ephemeral=True)
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
            await ctx.send(embed=embed, view=view)

        except Exception as e:
            logger.error(
                f"Profile command error for {target.id}: {e}",
                exc_info=True
            )
            embed = EmbedBuilder.error(
                title="Profile Error",
                description="Unable to load profile data.",
                help_text="Please try again shortly."
            )
            await ctx.send(embed=embed, ephemeral=True)

    # ===============================================================
    # Transactions Command
    # ===============================================================
    @commands.hybrid_command(
        name="transactions",
        description="View recent resource transaction history"
    )
    @ratelimit(uses=5, per_seconds=60, command_name="transactions")
    async def transactions(self, ctx: commands.Context, limit: Optional[int] = 10):
        """Display the player's recent resource transactions."""
        await ctx.defer()
        limit = max(1, min(limit or 10, 20))

        try:
            async with DatabaseService.get_transaction() as session:
                player = await PlayerService.get_player_with_regen(
                    session, ctx.author.id, lock=False
                )

                if not player:
                    await ctx.send(
                        embed=EmbedBuilder.error(
                            title="Not Registered",
                            description="You need to register first.",
                            help_text="Use `/register` to start your journey."
                        ),
                        ephemeral=True
                    )
                    return

                # Query recent transactions
                result = await session.execute(
                    select(TransactionLog)
                    .where(TransactionLog.player_id == ctx.author.id)
                    .where(TransactionLog.transaction_type.like("resource_%"))
                    .order_by(desc(TransactionLog.timestamp))
                    .limit(limit)
                )
                logs = result.scalars().all()

            if not logs:
                await ctx.send(
                    embed=EmbedBuilder.warning(
                        title="📜 No Transactions",
                        description="You have no resource transaction history yet."
                    )
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

        except Exception as e:
            logger.error(f"Transaction view error for {ctx.author.id}: {e}", exc_info=True)
            await ctx.send(
                embed=EmbedBuilder.error(
                    title="Transaction Error",
                    description="Unable to fetch transaction history.",
                    help_text="Please try again shortly."
                ),
                ephemeral=True
            )


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

        except Exception as e:
            logger.error(f"Advanced stats error for {self.user_id}: {e}", exc_info=True)
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


async def setup(bot: commands.Bot):
    """Required for Discord cog loading."""
    await bot.add_cog(ProfileCog(bot))
