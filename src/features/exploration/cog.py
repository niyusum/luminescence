"""
Exploration and Matron combat interface.

The Discord UI layer for the Exploration feature. Enforces RIKI LAW by delegating 
all core logic and state mutation to the service layer and ensuring full observability 
through structured logging and command latency metrics.

RIKI LAW Compliance:
- Article I.4: All magic numbers are migrated to ConfigManager.
- Article I.5 & VII: All business logic exceptions are handled gracefully and converted to user-friendly embeds.
- Article I.2 & I.6: Transaction logging is atomic within the state-modifying transaction.
- Article VI: The cog remains thin, focusing only on presentation and command routing.
"""

import discord
from discord.ext import commands
from typing import Optional, Dict, Any, TYPE_CHECKING
import time

from src.core.bot.base_cog import BaseCog
from src.core.infra.database_service import DatabaseService
from src.core.infra.transaction_logger import TransactionLogger
from src.core.infra.redis_service import RedisService
from src.core.config.config_manager import ConfigManager
from src.features.player.service import PlayerService
from src.features.exploration.service import ExplorationService
from src.features.exploration.matron_logic import MatronService
from src.features.exploration.mastery_logic import MasteryService
from src.features.exploration.constants import RELIC_TYPES
from src.features.combat.service import CombatService
from src.core.exceptions import InsufficientResourcesError, InvalidOperationError, NotFoundError, CooldownError
from src.core.logging.logger import get_logger 
from src.utils.decorators import ratelimit
from utils.embed_builder import EmbedBuilder

# Type checking to prevent circular import warnings
if TYPE_CHECKING:
    from typing import Callable

logger = get_logger(__name__)

# RIKI LAW I.4: Standard Primary Color for UI
PRIMARY_COLOR = 0x2c2d31 
SUCCESS_COLOR = 0x00FF00
DISMISS_COLOR = 0x808080
TURN_UPDATE_COLOR = 0x0099FF
MASTERY_COLOR = 0x9B59B6


class ExplorationCog(BaseCog):
    """
    Exploration and Matron combat system.
    
    Speed-based combat with turn limits. No retaliation.
    """
    
    def __init__(self, bot: commands.Bot):
        """Initialize the Exploration Cog."""
        super().__init__(bot, self.__class__.__name__)
        self.bot = bot
    
    @commands.command(
        name="matron",
        aliases=["rmb", "rmatron", "rikimatron"],
        description="Challenge a sector Matron (speed combat)"
    )
    @ratelimit(
        uses=ConfigManager.get("rate_limits.exploration.explore.uses", 30),
        per_seconds=ConfigManager.get("rate_limits.exploration.explore.period", 60),
        command_name="matron"
    )
    async def matron(
        self,
        ctx: commands.Context,
        sector: int,
        sublevel: int
    ):
        """Challenge Matron boss."""
        start_time = time.perf_counter()
        await ctx.defer()
        
        # RIKI LAW I.4: Config-driven validation
        matron_max_sector = ConfigManager.get("exploration.matron_max_sector", default=6)
        matron_max_sublevel = ConfigManager.get("exploration.matron_max_sublevel", default=9)

        if sector < 1 or sector > matron_max_sector or sublevel < 1 or sublevel > matron_max_sublevel:
            await self.send_error(
                ctx, 
                "Invalid Target", 
                f"Sector must be 1-{matron_max_sector} and Sublevel 1-{matron_max_sublevel}.", 
                help_text="Example: `/matron 1 9`"
            )
            return
        
        try:
            async with DatabaseService.get_transaction() as session:
                # Read operation, no lock needed for command setup
                player = await self.require_player(session, ctx, ctx.author.id, lock=False)
                if not player:
                    return # self.require_player handles error message
                
                matron = MatronService.generate_matron(sector, sublevel)
                player_power = await CombatService.calculate_total_power(
                    session, player.discord_id, include_leader_bonus=True
                )

                # Log matron encounter start (RIKI LAW I.2)
                await TransactionLogger.log_transaction(
                    session=session,
                    player_id=player.discord_id,
                    transaction_type="exploration_matron_start",
                    details={
                        "zone": f"sector_{sector}_sublevel_{sublevel}",
                        "matron_name": matron["name"],
                        "matron_hp": matron["hp"],
                        "player_power": player_power
                    },
                    context=f"exploration:sector_{sector}_sublevel_{sublevel}"
                )
            
            embed = self._build_matron_embed(matron, player_power)
            
            view = MatronCombatView(
                user_id=ctx.author.id,
                matron=matron,
                player_power=player_power,
                cog_logger=self.log_cog_error
            )
            
            message = await ctx.send(embed=embed, view=view)
            view.set_message(message)

            # Log latency (Success) (RIKI LAW I.9)
            latency = (time.perf_counter() - start_time) * 1000
            self.log_command_use(
                "matron",
                ctx.author.id,
                guild_id=ctx.guild.id if ctx.guild else None,
                latency_ms=round(latency, 2),
                sector=sector,
                sublevel=sublevel
            )
        
        except Exception as e:
            # RIKI LAW I.5: Catch all for auditable failures
            latency = (time.perf_counter() - start_time) * 1000
            self.log_cog_error(
                "matron",
                e,
                user_id=ctx.author.id,
                guild_id=ctx.guild.id if ctx.guild else None,
                latency_ms=round(latency, 2),
                sector=sector,
                sublevel=sublevel
            )
            # Use BaseCog utility for standard error response (RIKI LAW I.5)
            if not await self.handle_standard_errors(ctx, e):
                 await self.send_error(
                    ctx,
                    "Matron Encounter Error",
                    "An unexpected error occurred while initiating the encounter.",
                    help_text="The team has been notified. Please try again later."
                )
    
    def _build_matron_embed(
        self,
        matron: Dict[str, Any],
        player_power: int
    ) -> discord.Embed:
        """Build matron encounter embed."""
        element_emoji = CombatService.get_element_emoji(matron["element"])
        
        embed = discord.Embed(
            title=f"🛡️ MATRON ENCOUNTER",
            description=f"Sector {matron['sector_id']} - Sublevel {matron['sublevel']}",
            color=PRIMARY_COLOR # RIKI LAW I.4: Consistent color
        )
        
        embed.add_field(
            name=f"⚔️ {matron['name']}",
            value=(
                f"{element_emoji} **{matron['element'].title()}**\n"
                f"**HP:** {matron['hp']:,}"
            ),
            inline=True
        )
        
        embed.add_field(
            name="💪 Your Total Power",
            value=f"{player_power:,}",
            inline=True
        )
        
        hp_bar = CombatService.render_hp_bar(
            matron["hp"], matron["max_hp"], width=10
        )
        embed.add_field(
            name="📊 Combat Info",
            value=(
                f"**HP:** {hp_bar}\n"
                f"**Turns:** 0 / {matron['optimal_turns']} (Optimal)\n"
                f"**Turn Limit:** {matron['turn_limit']}\n"
                f"⚠️ Matron dismisses you at turn limit!"
            ),
            inline=False
        )
        
        embed.add_field(
            name="💰 Reward Bonuses",
            value=(
                f"⭐ **Perfect:** ≤{matron['optimal_turns']} turns (+100% rewards)\n"
                f"🏃 **Fast:** ≤{matron['optimal_turns']+3} turns (+50% rewards)\n"
                f"✅ **Standard:** ≤{matron['turn_limit']} turns (base rewards)\n"
                f"🐌 **Slow:** >{matron['turn_limit']} turns (dismissed)"
            ),
            inline=False
        )
        
        if matron["is_sector_boss"]:
            embed.add_field(
                name="🏆 SECTOR BOSS",
                value="Extra rewards on victory!",
                inline=False
            )
        
        embed.set_footer(text="Speed Combat | Matrons don't fight back!")

        return embed

    @commands.command(
        name="explore",
        aliases=["re", "rexplore", "rikiexplore"],
        description="Explore a sector sublevel to gain progress and rewards"
    )
    @ratelimit(
        uses=ConfigManager.get("rate_limits.exploration.explore.uses", 30),
        per_seconds=ConfigManager.get("rate_limits.exploration.explore.period", 60),
        command_name="explore"
    )
    async def explore(
        self,
        ctx: commands.Context,
        sector: int,
        sublevel: int
    ):
        """Explore sector sublevel to gain progress, rewards, and encounter maidens."""
        start_time = time.perf_counter()
        await ctx.defer()

        # RIKI LAW I.4: Config-driven validation
        explore_max_sector = ConfigManager.get("exploration.explore_max_sector", default=7)
        explore_max_sublevel = ConfigManager.get("exploration.explore_max_sublevel", default=9)

        if sector < 1 or sector > explore_max_sector or sublevel < 1 or sublevel > explore_max_sublevel:
            await self.send_error(
                ctx, 
                "Invalid Target", 
                f"Sector must be 1-{explore_max_sector} and Sublevel 1-{explore_max_sublevel}.", 
                help_text="Example: rexplore 1 1"
            )
            return

        try:
            async with DatabaseService.get_transaction() as session:
                # Write operation, lock=True mandatory (RIKI LAW I.1)
                player = await self.require_player(session, ctx, ctx.author.id, lock=True)
                if not player:
                    return # self.require_player handles error message

                # RIKI LAW I.7: All logic in service
                result = await ExplorationService.explore_sublevel(
                    session, player, sector, sublevel
                )

                # Build result embed
                embed = discord.Embed(
                    title=f"🗺️ Sector {sector} - Sublevel {sublevel}",
                    description="Exploration complete!",
                    color=PRIMARY_COLOR # RIKI LAW I.4: Consistent color
                )

                embed.add_field(name="⚡ Energy", value=f"-{result['energy_cost']}", inline=True)
                embed.add_field(name="💰 Rewards", value=f"+{result['rikis_gained']:,} Rikis\n+{result['xp_gained']} XP", inline=True)

                progress_bar = self._render_progress_bar(result['current_progress'], width=10)
                embed.add_field(
                    name="📊 Progress",
                    value=f"{progress_bar} {result['current_progress']:.1f}%\n+{result['progress_gained']:.1f}% this exploration",
                    inline=False
                )

                if result.get('miniboss_ready'):
                    embed.add_field(
                        name="🔥 MINIBOSS READY",
                        value=f"Type `/matron {sector} 9` to challenge the Sector {sector} Matron boss!",
                        inline=False
                    )

                if result.get('maiden_encounter'):
                    maiden = result['maiden_encounter']
                    embed.add_field(
                        name="✨ Maiden Encountered!",
                        value=f"**{maiden['name']}** ({maiden['tier']}⭐) appeared!",
                        inline=False
                    )
            
            await ctx.send(embed=embed)

            # Log latency (Success) (RIKI LAW I.9)
            latency = (time.perf_counter() - start_time) * 1000
            self.log_command_use(
                "explore",
                ctx.author.id,
                guild_id=ctx.guild.id if ctx.guild else None,
                latency_ms=round(latency, 2),
                sector=sector,
                sublevel=sublevel
            )

        # RIKI LAW I.5: Specific and graceful exception handling
        except (InsufficientResourcesError, InvalidOperationError, NotFoundError, CooldownError) as e:
            latency = (time.perf_counter() - start_time) * 1000
            self.log_cog_error(
                "explore", e, user_id=ctx.author.id, latency_ms=round(latency, 2), 
                status="domain_error", error_type=type(e).__name__, sector=sector, sublevel=sublevel
            )
            # Use BaseCog utility to convert domain error to friendly embed
            await self.handle_standard_errors(ctx, e)

        except Exception as e:
            # Structured error logging for unexpected errors (RIKI LAW I.2 & I.5)
            latency = (time.perf_counter() - start_time) * 1000
            self.log_cog_error(
                "explore", e, user_id=ctx.author.id, guild_id=ctx.guild.id if ctx.guild else None,
                latency_ms=round(latency, 2), sector=sector, sublevel=sublevel
            )
            await self.send_error(
                ctx,
                "Exploration Error",
                "An unexpected error occurred during exploration.",
                help_text="The team has been notified. Please try again later."
            )

    def _render_progress_bar(self, progress: float, width: int = 10) -> str:
        """Render a text-based progress bar."""
        progress = max(0, min(100, progress))
        full_blocks = int((progress / 100) * width)
        empty_blocks = width - full_blocks
        return f"[{'█' * full_blocks}{'░' * empty_blocks}]"

    @commands.command(
        name="mastery",
        aliases=["rms", "rmastery", "rikimastery"],
        description="View exploration mastery ranks and relic bonuses"
    )
    @ratelimit(
        uses=ConfigManager.get("rate_limits.exploration.zones.uses", 10),
        per_seconds=ConfigManager.get("rate_limits.exploration.zones.period", 60),
        command_name="mastery"
    )
    async def mastery(self, ctx: commands.Context, sector_id: Optional[int] = None):
        """View mastery overview or detailed sector mastery."""
        start_time = time.perf_counter()
        # RIKI LAW: Use BaseCog safe_defer
        await self.safe_defer(ctx)

        if sector_id is not None:
            await self._show_sector_mastery(ctx, sector_id, start_time)
            return

        await self._show_mastery_overview(ctx, start_time)

    async def _show_mastery_overview(self, ctx: commands.Context, start_time: float):
        """Show mastery overview with all active relics."""

        try:
            # RIKI LAW: Use BaseCog get_session/require_player
            async with self.get_session() as session:
                player = await self.require_player(session, ctx, ctx.author.id, lock=False)
                if not player:
                    return

                relics = await MasteryService.get_player_relics(session, player.discord_id)
                bonuses = await MasteryService.get_active_bonuses(session, player.discord_id)

                embed = discord.Embed(
                    title=f"🏆 {ctx.author.display_name}'s Mastery",
                    description=("Complete exploration sectors to earn permanent relic bonuses."),
                    color=MASTERY_COLOR,
                    timestamp=discord.utils.utcnow()
                )

                embed.add_field(name="📦 Total Relics", value=f"**{len(relics)}** active relics", inline=True)

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

                    embed.add_field(name="✨ Active Bonuses", value="\n".join(bonus_text), inline=False)
                else:
                    embed.add_field(name="✨ Active Bonuses", value="No active relics yet. Complete sectors to earn bonuses!", inline=False)

                sector_status = []
                # RIKI LAW I.4: Use Config for Sector range if possible, but hardcode 6 for mastery if not configured
                max_mastery_sector = ConfigManager.get("exploration.max_mastery_sector", default=6) 
                for sector_id in range(1, max_mastery_sector + 1):
                    status = await MasteryService.get_sector_mastery_status(session, player.discord_id, sector_id)
                    rank = status["current_rank"]
                    stars = "★" * rank + "☆" * (3 - rank)
                    sector_status.append(f"Sector {sector_id}: {stars}")

                embed.add_field(name="🗺️ Sector Progress", value="\n".join(sector_status), inline=False)
                embed.set_footer(text="Use rmastery <sector_id> to view detailed sector mastery")

                await ctx.send(embed=embed)

                # Log latency (Success) (RIKI LAW I.9)
                latency = (time.perf_counter() - start_time) * 1000
                self.log_command_use(
                    "mastery", 
                    ctx.author.id, 
                    guild_id=ctx.guild.id if ctx.guild else None,
                    latency_ms=round(latency, 2)
                )

        except Exception as e:
            # RIKI LAW I.5: Structured Error Logging and standard handling
            latency = (time.perf_counter() - start_time) * 1000
            self.log_cog_error("mastery", e, user_id=ctx.author.id, latency_ms=round(latency, 2))
            if not await self.handle_standard_errors(ctx, e):
                await self.send_error(ctx, "Mastery Error", "Failed to load mastery data.")

    async def _show_sector_mastery(self, ctx: commands.Context, sector_id: int, start_time: float):
        """Show detailed mastery information for specific sector."""

        # RIKI LAW I.4: Use Config for Sector range
        max_mastery_sector = ConfigManager.get("exploration.max_mastery_sector", default=6)
        if sector_id < 1 or sector_id > max_mastery_sector:
            await self.send_error(ctx, "Invalid Sector", f"Sector must be between 1 and {max_mastery_sector}.", help_text="Example: rmastery 1")
            return

        try:
            async with self.get_session() as session:
                player = await self.require_player(session, ctx, ctx.author.id, lock=False)
                if not player:
                    return

                status = await MasteryService.get_sector_mastery_status(session, player.discord_id, sector_id)

                embed = discord.Embed(
                    title=f"🗺️ Sector {sector_id} Mastery",
                    description=f"Complete all {ConfigManager.get('exploration.sublevels_per_sector', default=9)} sublevels to unlock mastery ranks.",
                    color=MASTERY_COLOR,
                    timestamp=discord.utils.utcnow()
                )

                current_rank = status["current_rank"]

                if status["fully_mastered"]:
                    embed.add_field(name="🏆 Status", value="**Fully Mastered!** ★★★", inline=False)
                else:
                    stars = "★" * current_rank + "☆" * (3 - current_rank)
                    embed.add_field(name="🏆 Current Rank", value=f"{stars} Rank {current_rank}/3", inline=False)

                if not status["fully_mastered"]:
                    next_rank = status.get("next_rank", {})
                    if next_rank:
                        embed.add_field(
                            name="📈 Progress to Next Rank",
                            value=(
                                f"**Required:** Clear all {next_rank['sublevels_required']} sublevels\n"
                                f"**Reward:** {next_rank['relic_reward']['name']} {next_rank['relic_reward']['icon']}"
                            ),
                            inline=False
                        )

                sector_relics = [r for r in await MasteryService.get_player_relics(session, player.discord_id) if r.sector_id == sector_id]
                if sector_relics:
                    relic_lines = []
                    for relic in sector_relics:
                        relic_info = RELIC_TYPES.get(relic.relic_type, {})
                        icon = relic_info.get("icon", "🏆")
                        name = relic_info.get("name", relic.relic_type)
                        relic_lines.append(f"{icon} {name} (Rank {relic.mastery_rank})")

                    embed.add_field(name="🎁 Earned Relics", value="\n".join(relic_lines), inline=False)

                await ctx.send(embed=embed)

                # Log latency (Success) (RIKI LAW I.9)
                latency = (time.perf_counter() - start_time) * 1000
                self.log_command_use(
                    "mastery_sector", 
                    ctx.author.id, 
                    guild_id=ctx.guild.id if ctx.guild else None, 
                    latency_ms=round(latency, 2), 
                    sector=sector_id
                )

        except Exception as e:
            # RIKI LAW I.5: Structured Error Logging and standard handling
            latency = (time.perf_counter() - start_time) * 1000
            self.log_cog_error("mastery_sector", e, user_id=ctx.author.id, latency_ms=round(latency, 2), sector=sector_id)
            if not await self.handle_standard_errors(ctx, e):
                await self.send_error(ctx, "Mastery Error", "Failed to load sector mastery.")


class MatronCombatView(discord.ui.View):
    """
    Discord UI View for Matron combat, handling button clicks and state updates.
    Enforces concurrency rules and standard error handling.
    """
    
    def __init__(
        self,
        user_id: int,
        matron: Dict[str, Any],
        player_power: int,
        cog_logger: 'Callable' # Structured logger dependency
    ):
        """Initialize the combat view."""
        # RIKI LAW: View timeout
        super().__init__(timeout=60.0) 
        self.user_id = user_id
        self.matron = matron
        self.player_power = player_power
        self.turn_count = 0
        self.message: Optional[discord.Message] = None
        self.cog_logger = cog_logger
    
    def set_message(self, message: discord.Message):
        """Store the original message reference."""
        self.message = message
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Ensure only the command user can interact."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This battle is not yours!", ephemeral=True)
            return False
        return True

    @discord.ui.button(
        label="⚔️ Attack x1",
        style=discord.ButtonStyle.secondary,
        custom_id="matron_x1"
    )
    async def attack_x1(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        """Execute x1 attack (1 stamina)."""
        await self._execute_attack(interaction, "x1")
    
    @discord.ui.button(
        label="⚔️⚔️ Attack x3",
        style=discord.ButtonStyle.primary,
        custom_id="matron_x3"
    )
    async def attack_x3(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        """Execute x3 attack (3 stamina)."""
        await self._execute_attack(interaction, "x3")
    
    @discord.ui.button(
        label="💥 Attack x10",
        style=discord.ButtonStyle.danger,
        custom_id="matron_x10"
    )
    async def attack_x10(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        """Execute x10 attack (10 stamina + 10 gems)."""
        await self._execute_attack(interaction, "x10")
    
    async def _execute_attack(
        self,
        interaction: discord.Interaction,
        attack_type: str
    ):
        """Execute attack on matron."""
        # Interaction check is handled by the interaction_check method
        await interaction.response.defer()

        try:
            # RIKI LAW I.3: Acquire Redis lock for state modification
            async with RedisService.acquire_lock(f"exploration_combat:{self.user_id}", timeout=5):
                self.turn_count += 1

                # RIKI LAW I.1 & I.6: State mutation requires transaction and pessimistic lock
                async with DatabaseService.get_transaction() as session:
                    player = await PlayerService.get_player_with_regen(
                        session, self.user_id, lock=True
                    )

                    result = await MatronService.attack_matron(
                        session=session,
                        player=player,
                        matron=self.matron,
                        attack_type=attack_type,
                        turn_count=self.turn_count
                    )

                    self.matron["hp"] = result["matron_hp"]

                    # RIKI LAW I.2 & I.6: Transaction logging is now atomic in the primary transaction
                    await TransactionLogger.log_transaction(
                        session=session,
                        player_id=self.user_id,
                        transaction_type="exploration_matron_attack",
                        details={
                            "attack_type": attack_type,
                            "damage_dealt": result["damage_dealt"],
                            "matron_hp_remaining": result["matron_hp"],
                            "turn_number": result["turns_taken"],
                        },
                        context=f"exploration:sector_{self.matron['sector_id']}_sublevel_{self.matron['sublevel']}"
                    )

                # Check outcome
                if result["victory"]:
                    embed = self._build_victory_embed(result)
                    await interaction.edit_original_response(embed=embed, view=None)
                    self.stop()
                elif result["dismissed"]:
                    embed = self._build_dismissal_embed(result)
                    await interaction.edit_original_response(embed=embed, view=None)
                    self.stop()
                else:
                    embed = self._build_turn_embed(result)
                    
                    # Warn near turn limit
                    if self.turn_count >= self.matron["turn_limit"] - 2:
                        for item in self.children:
                            if isinstance(item, discord.ui.Button):
                                item.style = discord.ButtonStyle.danger

                    await interaction.edit_original_response(embed=embed, view=self)
        
        # RIKI LAW I.5: Specific error handling for domain exceptions
        except InsufficientResourcesError as e:
            await interaction.followup.send(
                embed=EmbedBuilder.error("Insufficient Resources", str(e), help_text="You don't have enough resources for this attack."),
                ephemeral=True
            )
            self.cog_logger("matron_attack", e, user_id=self.user_id, status="domain_error", error_type=type(e).__name__)
        
        except Exception as e:
            # RIKI LAW I.5: Generic failure logging
            self.cog_logger(
                "matron_attack",
                e,
                user_id=self.user_id,
                guild_id=interaction.guild_id,
                attack_type=attack_type,
                matron_name=self.matron["name"]
            )
            await interaction.followup.send(
                embed=EmbedBuilder.error("System Failure", "An unexpected error occurred. Combat aborted."),
                ephemeral=True
            )
            await interaction.edit_original_response(view=None)
            self.stop()
    
    def _build_turn_embed(self, result: Dict[str, Any]) -> discord.Embed:
        """Build turn result embed."""
        embed = discord.Embed(
            title=f"⚔️ TURN {result['turns_taken']}",
            color=TURN_UPDATE_COLOR
        )
        
        embed.add_field(name="Damage Dealt", value=f"⚔️ {result['damage_dealt']:,}", inline=True)
        
        hp_bar = CombatService.render_hp_bar(result["matron_hp"], self.matron["max_hp"], width=10)
        embed.add_field(name="Matron HP", value=f"{hp_bar} {result['matron_hp']:,}/{self.matron['max_hp']:,}", inline=True)
        
        optimal = self.matron["optimal_turns"]
        turn_limit = self.matron["turn_limit"]
        turns = result["turns_taken"]
        
        if turns <= optimal:
            status = "⭐ PERFECT pace!"
        elif turns <= optimal + 3:
            status = "🏃 FAST pace!"
        elif turns < turn_limit - 2:
            status = "✅ Standard pace"
        else:
            status = "🚨 WARNING: Near turn limit!"
        
        embed.add_field(
            name="Turn Status",
            value=(f"**Turns:** {turns} / {optimal} (Optimal)\n" f"**Turn Limit:** {turn_limit}\n" f"{status}"),
            inline=False
        )
        
        embed.set_footer(text=f"Stamina: {result['stamina_cost']} | Gems: {result['gem_cost']}")
        
        return embed
    
    def _build_victory_embed(self, result: Dict[str, Any]) -> discord.Embed:
        """Build victory embed."""
        rewards = result["rewards"]
        turn_bonus = rewards["turn_bonus"]
        
        bonus_emoji = {"perfect": "⭐", "fast": "🏃", "standard": "✅", "slow": "🐌"}
        bonus_text = {"perfect": "PERFECT CLEAR! (+100% rewards)", "fast": "FAST CLEAR! (+50% rewards)", "standard": "CLEAR (base rewards)", "slow": "SLOW CLEAR (-50% rewards)"}
        
        embed = discord.Embed(title="🏆 MATRON DEFEATED!", description=f"{self.matron['name']} has been conquered!", color=SUCCESS_COLOR)
        
        embed.add_field(name=f"{bonus_emoji[turn_bonus]} {bonus_text[turn_bonus]}", value=f"**Turns Used:** {result['turns_taken']}", inline=False)
        
        reward_text = f"**+{rewards['rikis']:,}** Rikis\n**+{rewards['xp']}** XP"
        if rewards.get("sector_clear_bonus"):
            bonus = rewards["sector_clear_bonus"]
            reward_text += f"\n\n**🏆 Sector Boss Bonus:**"
            reward_text += f"\n+{bonus['rikis']:,} Rikis"
            reward_text += f"\n🥈 Silver Token x1"
        
        embed.add_field(name="💰 Rewards", value=reward_text, inline=False)
        embed.set_footer(text="Matron defeated | Sector progress saved")
        
        return embed
    
    def _build_dismissal_embed(self, result: Dict[str, Any]) -> discord.Embed:
        """Build dismissal embed."""
        embed = discord.Embed(title="💨 DISMISSED", description=result["dismissal_text"], color=DISMISS_COLOR)
        
        embed.add_field(
            name="Combat Stats",
            value=(
                f"**Damage Dealt:** {result['damage_dealt']:,}\n"
                f"**Matron HP Remaining:** {result['matron_hp']:,}\n"
                f"**Turns Used:** {result['turns_taken']}"
            ),
            inline=False
        )
        
        embed.add_field(
            name="❌ No Rewards",
            value=(f"Stamina consumed: {result['stamina_cost']}\n" f"Gems consumed: {result['gem_cost']}"),
            inline=False
        )
        
        embed.add_field(
            name="💡 Tips",
            value=("• Upgrade your maiden collection\n" "• Use higher attack multipliers (x3, x10)\n" "• Allocate more stamina for more attempts\n" "• Set a leader for income boost"),
            inline=False
        )
        
        embed.set_footer(text="Better luck next time!")
        
        return embed
    
    async def on_timeout(self):
        """Disable all buttons visually when the view expires."""
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

        try:
            # If we still have access to the sent message, edit to reflect disabled state
            if self.message:
                await self.message.edit(view=self)
        except discord.HTTPException:
            pass

        self.stop()


async def setup(bot: commands.Bot):
    """Required for dynamic cog loading."""
    await bot.add_cog(ExplorationCog(bot))