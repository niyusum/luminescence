"""
Unified ascension and token management system.

Consolidates tower climbing, combat, and token redemption into a single
cohesive ascension feature cog.

LUMEN LAW Compliance:
    - Article I.6: Configuration drawn from ConfigManager, never literals. (CLEAN)
    - Article I.7: All business logic delegated to services (Thin Cogs, Thick Services)
    - Article I.9: Metrics for command latency and failures
    - Article II: Transaction logging and audit integrity enforced
    - Architectural Fix: Commands (tokens, redeem) moved out of View into Cog.
"""

import discord
from discord.ext import commands
from typing import Optional, Dict, Any, List
import time

from core.config.config_manager import ConfigManager
from src.core.bot.base_cog import BaseCog
from src.core.infra.database_service import DatabaseService
from src.core.logging.logger import get_logger, LogContext
from src.modules.player.service import PlayerService
from src.modules.ascension.service import AscensionService
from src.modules.ascension.token_logic import TokenService
from src.modules.combat.service import CombatService
from src.modules.maiden.constants import Element
from src.core.infra.transaction_logger import TransactionLogger
from src.core.infra.redis_service import RedisService
from src.core.exceptions import InsufficientResourcesError, InvalidOperationError
from src.utils.decorators import ratelimit
from src.ui import EmbedFactory, BaseView
from src.ui.emojis import Emojis

logger = get_logger(__name__)


class AscensionCog(BaseCog):
    """
    Unified ascension tower system.
    """

    def __init__(self, bot: commands.Bot):
        super().__init__(bot, "AscensionCog")

    # UTILITIES

    def _get_floor_color(self, floor: int) -> int:
        """Helper to determine embed color based on floor number, using ConfigManager."""
        # LUMEN LAW I.6: Configuration drawn from ConfigManager.
        FLOOR_COLOR_TIERS = ConfigManager.get("ASCENSION.FLOOR_COLOR_TIERS", {})
        for _, (start, end, color) in FLOOR_COLOR_TIERS.items():
            if start <= floor <= end:
                return color
        return 0x808080

    # ASCENSION TOWER COMMAND

    @commands.command(
        name="ascension",
        aliases=[],
        description="Climb the infinite tower (strategic combat)"
    )
    @ratelimit(
        uses=ConfigManager.get("rate_limits.ascension.climb.uses", 20),
        per_seconds=ConfigManager.get("rate_limits.ascension.climb.period", 60),
        command_name="ascension"
    )
    async def ascension(self, ctx: commands.Context):
        """Initiate ascension floor encounter."""
        start_time = time.perf_counter()
        await self.defer(ctx)

        try:
            async with self.get_session() as session:
                player = await self.require_player(ctx, session, ctx.author.id)
                if not player:
                    return

                combat_data = await AscensionService.initiate_floor(session, player)

                # LUMEN LAW Article II: Transaction Logging for floor initiation
                await TransactionLogger.log_transaction(
                    session=session,
                    player_id=ctx.author.id,
                    transaction_type="ascension_floor_initiate",
                    details={
                        "floor_number": combat_data["floor"],
                        "player_stats": combat_data["player_stats"],
                        "monster_name": combat_data["monster"]["name"],
                        "monster_hp": combat_data["monster"]["hp"],
                        "monster_atk": combat_data["monster"]["atk"],
                    },
                    context=f"ascension:floor_{combat_data['floor']}"
                )

            embed = self._build_floor_embed(combat_data)

            view = AscensionCombatView(
                user_id=ctx.author.id,
                combat_data=combat_data,
                cog_error_logger=self.log_cog_error
            )

            message = await ctx.send(embed=embed, view=view)
            view.set_message(message)

            # LUMEN LAW Article I.9: Latency Metric Logging
            latency = (time.perf_counter() - start_time) * 1000
            self.log_command_use(
                "ascension",
                ctx.author.id,
                guild_id=ctx.guild.id if ctx.guild else None,
                latency_ms=round(latency, 2)
            )

        except Exception as e:
            # LUMEN LAW Article II: Structured Error Logging
            self.log_cog_error(
                "ascension",
                e,
                user_id=ctx.author.id,
                guild_id=ctx.guild.id if ctx.guild else None,
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2)
            )
            if not await self.handle_standard_errors(ctx, e):
                await self.send_error(
                    ctx,
                    "Ascension Error",
                    "Failed to initiate floor encounter.",
                    help_text="Please try again."
                )

    # EMBED BUILDERS

    def _build_floor_embed(self, combat_data: Dict[str, Any]) -> discord.Embed:
        """Build floor encounter embed."""
        floor = combat_data["floor"]
        monster = combat_data["monster"]
        player_stats = combat_data["player_stats"]
        strategic = combat_data["strategic_power"]

        color = self._get_floor_color(floor)

        embed = discord.Embed(
            title=f"{Emojis.ASCENSION} FLOOR {floor} APPROACH",
            color=color
        )

        # Monster info
        element_emoji = CombatService.get_element_emoji(monster["element"])
        embed.add_field(
            name=f"{Emojis.ATTACK} {monster['name']}",
            value=(
                f"{element_emoji} **Element:** {monster['element'].title()}\n"
                f"**ATK:** {monster['atk']:,}\n"
                f"**HP:** {monster['hp']:,}"
            ),
            inline=True
        )

        # Player stats
        hp_bar = CombatService.render_hp_bar(
            player_stats["hp"], player_stats["max_hp"], width=10
        )
        embed.add_field(
            name=f"{Emojis.STAMINA} Your Stats",
            value=(
                f"**Power:** {player_stats['power']:,}\n"
                f"**Defense:** {player_stats['defense']:,}\n"
                f"**HP:** {hp_bar} {player_stats['hp']}/{player_stats['max_hp']}"
            ),
            inline=True
        )

        # Element bonuses
        if strategic["element_bonuses"]:
            bonus_text = "\n".join(
                f"{b['emoji']} **{b['name']}:** {b['bonus']}"
                for b in strategic["element_bonuses"]
            )
            embed.add_field(
                name=f"{Emojis.RADIANT} Active Generals",
                value=bonus_text,
                inline=False
            )

        # Combat gauges
        embed.add_field(
            name=f"{Emojis.TEMPEST} Combat Status",
            value=(
                f"**Critical Gauge:** ░░░░░░░░░░ 0%\n"
                f"**Momentum:** ░░░░░░░░░░ 0%"
            ),
            inline=False
        )

        # Milestone indicator
        if monster.get("is_milestone"):
            embed.add_field(
                name=f"{Emojis.VICTORY} MILESTONE BOSS",
                value=(
                    f"Special mechanics active!\n"
                    f"Extra rewards on victory!"
                ),
                inline=False
            )

        embed.set_footer(text="Strategic Combat | Best 6 Maidens (One Per Element)")

        return embed

    # --------------------------------------------------------------------------
    # TOKEN INVENTORY COMMAND (MOVED FROM VIEW CLASS - FIXING INDENTATION BUG)
    # --------------------------------------------------------------------------

    @commands.command(
        name="tokens",
        aliases=[],
        description="View your token inventory"
    )
    @ratelimit(
        uses=ConfigManager.get("rate_limits.ascension.rewards.uses", 10),
        per_seconds=ConfigManager.get("rate_limits.ascension.rewards.period", 60),
        command_name="tokens"
    )
    async def tokens(self, ctx: commands.Context):
        """Display token inventory with redemption info."""
        start_time = time.perf_counter()
        await self.defer(ctx)

        try:
            async with self.get_session() as session:
                player = await self.require_player(ctx, session, ctx.author.id)
                if not player:
                    return

                # LUMEN LAW Article I.11: Read-only operation uses no lock
                inventory = await TokenService.get_player_tokens(
                    session, player.discord_id
                )

            # LUMEN LAW I.6: Configuration drawn from ConfigManager.
            TOKEN_TIERS = ConfigManager.get("ASCENSION.TOKEN_TIERS", {})

            # Build inventory embed
            embed = discord.Embed(
                title=f"{Emojis.TOKEN} Token Inventory",
                description=(
                    "Redeem tokens for random maidens!\n"
                    "Higher tier tokens = Higher tier maidens"
                ),
                color=0xFFD700
            )

            total_tokens = sum(inventory.values())
            has_tokens = False

            # LUMEN LAW I.6: Iterate over keys from ConfigManager
            for token_type, token_data in TOKEN_TIERS.items():
                quantity = inventory.get(token_type, 0)
                tier_range = token_data.get("tier_range", (1, 1))

                if quantity > 0:
                    has_tokens = True

                status = Emojis.SUCCESS if quantity > 0 else Emojis.ERROR

                embed.add_field(
                    name=f"{status} {token_data.get('emoji', Emojis.HELP)} {token_data.get('name', token_type.title())}",
                    value=(
                        f"**Quantity:** {quantity}\n"
                        f"**Tier Range:** T{tier_range[0]}-T{tier_range[1]}\n"
                        f"*{token_data.get('description', 'No description provided.')}*"
                    ),
                    inline=True
                )

            embed.add_field(
                name=f"{Emojis.INFO} Summary",
                value=f"**Total Tokens:** {total_tokens}",
                inline=False
            )

            if has_tokens:
                first_token = next(iter(TOKEN_TIERS), 'bronze')
                embed.add_field(
                    name=f"{Emojis.TIP} How to Redeem",
                    value=(
                        "Use `/redeem <token_type>` to redeem!\n"
                        f"Example: `/redeem {first_token}`"
                    ),
                    inline=False
                )
            else:
                embed.add_field(
                    name=f"{Emojis.TIP} How to Earn Tokens",
                    value=(
                        "Clear ascension tower floors to earn tokens!\n"
                        "• Floors 1-10: Bronze tokens\n"
                        "• Floors 11-25: Bronze/Silver mix\n"
                        "• Floors 26+: Higher tier tokens\n\n"
                        "Use `/ascension` to climb the tower!"
                    ),
                    inline=False
                )

            embed.set_footer(text=f"Player: {ctx.author.name}")
            embed.timestamp = discord.utils.utcnow()

            await ctx.send(embed=embed)

            # LUMEN LAW Article I.9: Latency Metric Logging
            latency = (time.perf_counter() - start_time) * 1000
            self.log_command_use(
                "tokens",
                ctx.author.id,
                guild_id=ctx.guild.id if ctx.guild else None,
                latency_ms=round(latency, 2)
            )

        except Exception as e:
            # LUMEN LAW Article II: Structured Error Logging
            self.log_cog_error(
                "tokens",
                e,
                user_id=ctx.author.id,
                guild_id=ctx.guild.id if ctx.guild else None,
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2)
            )
            if not await self.handle_standard_errors(ctx, e):
                await self.send_error(
                    ctx,
                    "Token Error",
                    "Failed to load token inventory.",
                    help_text="Please try again."
                )

    # --------------------------------------------------------------------------
    # TOKEN REDEMPTION COMMAND (MOVED FROM VIEW CLASS - FIXING INDENTATION BUG)
    # --------------------------------------------------------------------------

    @commands.command(
        name="redeem",
        aliases=[],
        description="Redeem a token for a random maiden"
    )
    @ratelimit(
        uses=ConfigManager.get("rate_limits.ascension.rewards.uses", 10),
        per_seconds=ConfigManager.get("rate_limits.ascension.rewards.period", 60),
        command_name="redeem"
    )
    async def redeem(
        self,
        ctx: commands.Context,
        token_type: str
    ):
        """Redeem token for random maiden in tier range."""
        start_time = time.perf_counter()
        await self.defer(ctx)

        token_type = token_type.lower()
        # LUMEN LAW I.6: Configuration drawn from ConfigManager.
        TOKEN_TIERS = ConfigManager.get("ASCENSION.TOKEN_TIERS", {})

        if token_type not in TOKEN_TIERS:
            # LUMEN LAW I.6: Use keys from ConfigManager for validation list
            valid_types = ", ".join(TOKEN_TIERS.keys())
            first_token = next(iter(TOKEN_TIERS), 'bronze')
            await self.send_error(
                ctx,
                "Invalid Token Type",
                f"{Emojis.ERROR} `{token_type}` is not a valid token type.",
                help_text=f"Valid types: **{valid_types}**\nExample: `/redeem {first_token}`"
            )
            return

        try:
            async with self.get_session() as session:
                # LUMEN LAW Article I.1: Pessimistic locking for state mutation
                player = await self.require_player(ctx, session, ctx.author.id, lock=True)
                if not player:
                    return

                # LUMEN LAW I.7: All business logic delegated to services
                result = await TokenService.redeem_token(
                    session=session,
                    player=player,
                    token_type=token_type
                )


            # Build success embed
            token_info = TOKEN_TIERS.get(
                token_type,
                {"name": token_type.title(), "emoji": Emojis.HELP, "color": 0x808080}
            )
            maiden_base = result["maiden_base"]
            tier = result["tier"]
            tokens_remaining = result["tokens_remaining"]

            element_obj = Element.from_string(maiden_base.element)
            element_emoji = element_obj.emoji if element_obj else Emojis.HELP
            element_name = element_obj.display_name if element_obj else maiden_base.element

            embed = discord.Embed(
                title=f"{Emojis.RADIANT} Token Redeemed Successfully!",
                description=f"You used a **{token_info['name']}** {token_info['emoji']}",
                color=token_info["color"]
            )

            # Maiden info
            embed.add_field(
                name=f"{Emojis.MAIDEN} Maiden Summoned",
                value=(
                    f"**{maiden_base.name}**\n"
                    f"{element_emoji} {element_name}\n"
                    f"**Tier {tier}**"
                ),
                inline=True
            )

            # Stats
            embed.add_field(
                name=f"{Emojis.INFO} Base Stats",
                value=(
                    f"**ATK:** {maiden_base.base_atk:,}\n"
                    f"**DEF:** {maiden_base.base_def:,}"
                ),
                inline=True
            )

            # Remaining tokens
            embed.add_field(
                name=f"{Emojis.TOKEN} Tokens Remaining",
                value=(
                    f"{token_info['emoji']} **{token_info['name']}:** {tokens_remaining}"
                ),
                inline=False
            )

            embed.set_footer(text="Added to your collection! • Use /collection to view")
            embed.timestamp = discord.utils.utcnow()

            await ctx.send(embed=embed)

            # LUMEN LAW Article I.9: Latency Metric Logging
            latency = (time.perf_counter() - start_time) * 1000
            self.log_command_use(
                "redeem",
                ctx.author.id,
                guild_id=ctx.guild.id if ctx.guild else None,
                token_type=token_type,
                latency_ms=round(latency, 2)
            )

        # LUMEN LAW Article I.5 & Article VII: Specific Exception Handling
        except InsufficientResourcesError as e:
            token_info = TOKEN_TIERS.get(
                token_type,
                {"name": token_type.title(), "emoji": Emojis.HELP}
            )
            await self.send_error(
                ctx,
                "Insufficient Tokens",
                f"You don't have any {token_info['name']} {token_info['emoji']}!",
                help_text=(
                    "Earn tokens by clearing ascension tower floors.\n"
                    "Use `/tokens` to view your inventory."
                )
            )

        except InvalidOperationError as e:
            await self.send_error(
                ctx,
                "Redemption Error",
                str(e),
                help_text="Please report this issue to support."
            )

        except Exception as e:
            # LUMEN LAW Article II: Structured Error Logging
            self.log_cog_error(
                "redeem",
                e,
                user_id=ctx.author.id,
                guild_id=ctx.guild.id if ctx.guild else None,
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2)
            )
            if not await self.handle_standard_errors(ctx, e):
                await self.send_error(
                    ctx,
                    "Redemption Error",
                    "An unexpected error occurred while redeeming your token.",
                    help_text="Please try again or contact support if this persists."
                )


# VIEW COMPONENTS (CLASS REMAINS UNCHANGED, IT NO LONGER HAS COMMAND METHODS)
class AscensionCombatView(discord.ui.View):
    """Interactive combat view with attack buttons."""

    def __init__(
        self,
        user_id: int,
        combat_data: Dict[str, Any],
        cog_error_logger: callable
    ):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.combat_data = combat_data
        self.message: Optional[discord.Message] = None
        self.cog_error_logger = cog_error_logger

    def set_message(self, message: discord.Message):
        self.message = message

    @discord.ui.button(
        label=f"{Emojis.ATTACK} Attack x1",
        style=discord.ButtonStyle.secondary,
        custom_id="ascension_x1"
    )
    async def attack_x1(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        """Execute x1 attack (1 stamina)."""
        await self._execute_attack(interaction, "x1")

    @discord.ui.button(
        label=f"{Emojis.ATTACK}{Emojis.ATTACK} Attack x3",
        style=discord.ButtonStyle.primary,
        custom_id="ascension_x3"
    )
    async def attack_x3(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        """Execute x3 attack (3 stamina)."""
        await self._execute_attack(interaction, "x3")

    @discord.ui.button(
        label=f"{Emojis.CRITICAL} Attack x10",
        style=discord.ButtonStyle.danger,
        custom_id="ascension_x10"
    )
    async def attack_x10(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        """Execute x10 attack (10 stamina + 10 lumenite)."""
        await self._execute_attack(interaction, "x10")

    @discord.ui.button(
        label=f"{Emojis.RETREAT} Retreat",
        style=discord.ButtonStyle.secondary,
        custom_id="ascension_retreat"
    )
    async def retreat(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        """Retreat from combat."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This battle is not yours!",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"{Emojis.RETREAT} Retreated",
            description="You have retreated from the tower.",
            color=0x808080
        )

        await interaction.response.edit_message(embed=embed, view=None)

    async def _execute_attack(
        self,
        interaction: discord.Interaction,
        attack_type: str
    ):
        """Execute attack and update combat state."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This battle is not yours!",
                ephemeral=True
            )
            return

        await interaction.response.defer()

        guild_id = interaction.guild_id
        floor = self.combat_data["floor"]
        lock_key = f"ascension_combat:{self.user_id}:{floor}"

        try:
            # LUMEN LAW Article I.3: Redis lock for concurrent button prevention
            async with RedisService.acquire_lock(lock_key, timeout=5):
                async with DatabaseService.get_transaction() as session:
                    # LUMEN LAW Article I.1: Pessimistic locking for state mutation
                    player = await PlayerService.get_player_with_regen(
                        session, self.user_id, lock=True
                    )

                    result = await AscensionService.execute_attack_turn(
                        session=session,
                        player=player,
                        monster=self.combat_data["monster"],
                        attack_type=attack_type,
                        combat_state=self.combat_data["combat_state"]
                    )

                    # LUMEN LAW Article II: Transaction Logging for attack action
                    await TransactionLogger.log_transaction(
                        session=session,
                        player_id=self.user_id,
                        transaction_type="ascension_attack",
                        details={
                            "floor_number": self.combat_data["floor"],
                            "attack_type": attack_type,
                            "damage_dealt": result.get("player_damage", 0),
                            "boss_hp_remaining": result["boss_hp"],
                            "player_hp_remaining": result["player_hp"],
                            "turn_number": result["turns_taken"],
                            "critical": result.get("critical", False),
                            "stamina_cost": result.get("stamina_cost", 0),
                            "lumenite_cost": result.get("lumenite_cost", 0),
                        },
                        context=f"ascension:floor_{self.combat_data['floor']}"
                    )

                # Update View State
                self.combat_data["monster"]["hp"] = result["boss_hp"]
                self.combat_data["combat_state"]["player_hp"] = result["player_hp"]
                self.combat_data["combat_state"]["critical_gauge"] = result["critical_gauge"]
                self.combat_data["combat_state"]["momentum"] = result["momentum"]
                self.combat_data["combat_state"]["turns_taken"] = result["turns_taken"]

                # Check outcome
                if result["victory"]:
                    # LUMEN LAW I.1: Need a new transaction for state modification
                    async with DatabaseService.get_transaction() as session:
                        player = await PlayerService.get_player_with_regen(
                            session, self.user_id, lock=True
                        )
                        victory_result = await AscensionService.resolve_victory(
                            session=session,
                            player=player,
                            floor=self.combat_data["floor"],
                            turns_taken=result["turns_taken"]
                        )

                        # LUMEN LAW Article II: Transaction Logging for victory
                        await TransactionLogger.log_transaction(
                            session=session,
                            player_id=self.user_id,
                            transaction_type="ascension_floor_victory",
                            details={
                                "floor_number": self.combat_data["floor"],
                                "rewards": victory_result.get("rewards", {}),
                                "turns_taken": result["turns_taken"],
                                "damage_dealt": result.get("player_damage", 0),
                                "damage_taken": result.get("boss_damage", 0),
                                "is_record": victory_result.get("is_record", False),
                            },
                            context=f"ascension:floor_{self.combat_data['floor']}"
                        )

                    embed = self._build_victory_embed(result, victory_result)
                    view = AscensionVictoryView(self.user_id, victory_result["new_floor"])

                    await interaction.edit_original_response(embed=embed, view=view)

                elif result["defeat"]:
                    # LUMEN LAW I.1: No state change on defeat, only logging
                    async with DatabaseService.get_transaction() as session:
                        # LUMEN LAW Article II: Transaction Logging for defeat
                        await TransactionLogger.log_transaction(
                            session=session,
                            player_id=self.user_id,
                            transaction_type="ascension_floor_defeat",
                            details={
                                "floor_number": self.combat_data["floor"],
                                "turns_survived": result["turns_taken"],
                                "damage_dealt": result.get("player_damage", 0),
                                "damage_taken": result.get("boss_damage", 0),
                                "final_player_hp": result["player_hp"],
                            },
                            context=f"ascension:floor_{self.combat_data['floor']}"
                        )

                    embed = self._build_defeat_embed(result)
                    await interaction.edit_original_response(embed=embed, view=None)

                else:
                    embed = self._build_combat_turn_embed(result)
                    await interaction.edit_original_response(embed=embed, view=self)

        # LUMEN LAW Article I.5 & Article VII: Specific Exception Handling
        except InsufficientResourcesError as e:
            embed = EmbedFactory.error(
                title="Insufficient Resources",
                description=str(e),
                help_text="You don't have enough resources for this attack."
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

        # LUMEN LAW Article II: Structured Error Logging for audit
        except Exception as e:
            self.cog_error_logger(
                "ascension_combat_view",
                e,
                user_id=self.user_id,
                guild_id=guild_id,
                floor_number=floor,
                lock_key=lock_key
            )
            embed = EmbedFactory.error(
                title="Combat Error",
                description="Failed to execute attack.",
                help_text="Please try again. Your action has been logged for audit."
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

    # EMBED BUILDERS (VIEW)

    def _build_combat_turn_embed(self, result: Dict[str, Any]) -> discord.Embed:
        """Build combat turn result embed."""
        monster = self.combat_data["monster"]

        embed = discord.Embed(
            title=f"{Emojis.ATTACK} TURN {result['turns_taken']}",
            color=0x00FF00 if result["critical"] else 0x0099FF
        )

        # Combat log
        combat_log = "\n".join(result["combat_log"])
        embed.add_field(
            name="Combat Log",
            value=combat_log,
            inline=False
        )

        # Boss HP
        boss_hp_bar = CombatService.render_hp_bar(
            result["boss_hp"], monster["max_hp"], width=10
        )
        embed.add_field(
            name=f"Boss HP",
            value=f"{boss_hp_bar} {result['boss_hp']:,}/{monster['max_hp']:,}",
            inline=False
        )

        # Player HP
        player_max_hp = self.combat_data["player_stats"]["max_hp"]
        player_hp_bar = CombatService.render_hp_bar(
            result["player_hp"], player_max_hp, width=10
        )
        embed.add_field(
            name="Your HP",
            value=f"{player_hp_bar} {result['player_hp']}/{player_max_hp}",
            inline=False
        )

        # Gauges
        crit_gauge = result["critical_gauge"]
        crit_bar = "█" * (crit_gauge // 10) + "░" * (10 - crit_gauge // 10)

        momentum = result["momentum"]
        momentum_bar = "█" * (momentum // 10) + "░" * (10 - momentum // 10)

        momentum_status = ""
        if momentum >= 80:
            momentum_status = f" {Emojis.CRITICAL} MAXIMUM!"
        elif momentum >= 50:
            momentum_status = f" {Emojis.INFERNAL} BLAZING!"
        elif momentum >= 30:
            momentum_status = f" {Emojis.TEMPEST} RISING!"

        embed.add_field(
            name=f"{Emojis.TEMPEST} Combat Status",
            value=(
                f"**Critical Gauge:** {crit_bar} {crit_gauge}%\n"
                f"**Momentum:** {momentum_bar} {momentum}%{momentum_status}"
            ),
            inline=False
        )

        embed.set_footer(text=f"Stamina: {result['stamina_cost']} | Lumenite: {result['lumenite_cost']}")

        return embed

    def _build_victory_embed(
        self,
        combat_result: Dict[str, Any],
        victory_result: Dict[str, Any]
    ) -> discord.Embed:
        """Build victory embed."""
        floor = self.combat_data["floor"]
        rewards = victory_result["rewards"]

        embed = discord.Embed(
            title=f"{Emojis.VICTORY} VICTORY!",
            description=f"**Floor {floor} Cleared!**",
            color=0x00FF00
        )

        # Combat stats
        embed.add_field(
            name=f"{Emojis.ATTACK} Combat Stats",
            value=(
                f"**Damage Dealt:** {combat_result['player_damage']:,}\n"
                f"**Damage Taken:** {combat_result['boss_damage']:,}\n"
                f"**Turns:** {combat_result['turns_taken']}"
            ),
            inline=True
        )

        # Rewards
        reward_text = f"**+{rewards['lumees']:,}** Lumees\n**+{rewards['xp']}** XP"

        # LUMEN LAW I.6: Use ConfigManager for token tiers
        TOKEN_TIERS = ConfigManager.get("ASCENSION.TOKEN_TIERS", {})
        if rewards.get("token"):
            token_data = rewards["token"]
            token_info = TOKEN_TIERS.get(
                token_data["type"],
                {"emoji": Emojis.HELP, "name": token_data["type"].title()}
            )
            reward_text += f"\n{token_info['emoji']} **{token_info['name']}** x{token_data['quantity']}"

        embed.add_field(
            name=f"{Emojis.LUMEES} Rewards",
            value=reward_text,
            inline=True
        )

        # Record indicator
        if victory_result["is_record"]:
            embed.add_field(
                name=f"{Emojis.CELEBRATION} NEW RECORD!",
                value=f"Highest floor reached: **{floor}**",
                inline=False
            )

        # Milestone bonus
        if rewards.get("milestone_bonus"):
            bonus_text = "\n".join(
                f"**{k}:** {v}" for k, v in rewards["milestone_bonus"].items()
            )
            embed.add_field(
                name=f"{Emojis.VICTORY} Milestone Bonus",
                value=bonus_text,
                inline=False
            )

        embed.set_footer(text=f"Next Floor: {victory_result['new_floor']}")

        return embed

    def _build_defeat_embed(self, result: Dict[str, Any]) -> discord.Embed:
        """Build defeat embed."""
        embed = discord.Embed(
            title="💀 DEFEATED",
            description="Your HP reached 0...",
            color=0xFF0000
        )

        embed.add_field(
            name="Combat Stats",
            value=(
                f"**Damage Dealt:** {result['player_damage']:,}\n"
                f"**Damage Taken:** {result['boss_damage']:,}\n"
                f"**Turns Survived:** {result['turns_taken']}"
            ),
            inline=False
        )

        embed.add_field(
            name="💡 Tips",
            value=(
                "• Upgrade your DEF maidens\n"
                "• Allocate more HP stat points\n"
                "• Build momentum before big attacks\n"
                "• Use Umbral general to reduce boss ATK"
            ),
            inline=False
        )

        embed.set_footer(text="No rewards granted | Stamina consumed")

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


class AscensionVictoryView(discord.ui.View):
    """Post-victory action buttons."""

    def __init__(self, user_id: int, next_floor: int):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.next_floor = next_floor

    @discord.ui.button(
        label="➡️ Next Floor",
        style=discord.ButtonStyle.primary,
        custom_id="ascension_next"
    )
    async def next_floor(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        """Continue to next floor."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This is not your ascension!",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"Use `/ascension` to challenge Floor {self.next_floor}!",
            ephemeral=True
        )

    @discord.ui.button(
        label="📊 View Stats",
        style=discord.ButtonStyle.secondary,
        custom_id="ascension_stats"
    )
    async def view_stats(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        """View ascension stats."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This is not your ascension!",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "Use `/profile` to view your progression stats!",
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(AscensionCog(bot))
