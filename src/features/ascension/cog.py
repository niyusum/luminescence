"""
Ascension tower climbing interface with turn-based strategic combat.

RIKI LAW Compliance:
- Article VI: Discord layer only handles UI
- Article VII: No business logic in cog
- Article I.5: Specific exception handling
"""

import discord
from discord.ext import commands
from typing import Optional, Dict, Any

from src.core.infra.database_service import DatabaseService
from src.features.player.service import PlayerService
from src.features.ascension.service import AscensionService
from src.features.combat.service import CombatService
from src.core.infra.transaction_logger import TransactionLogger
from src.core.infra.redis_service import RedisService
from src.core.exceptions import InsufficientResourcesError, InvalidOperationError
from src.core.logging.logger import get_logger
from src.utils.decorators import ratelimit
from utils.embed_builder import EmbedBuilder

logger = get_logger(__name__)


class AscensionCog(commands.Cog):
    """
    Ascension tower climbing system.
    
    Strategic turn-based combat using best 6 maidens (one per element).
    Boss fights back, player HP at risk, token rewards.
    """
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    @commands.hybrid_command(
        name="ascension",
        aliases=["ra", "tower"],
        description="Climb the infinite tower (strategic combat)"
    )
    @ratelimit(uses=10, per_seconds=60, command_name="ascension")
    async def ascension(self, ctx: commands.Context):
        """Initiate ascension floor encounter."""
        await ctx.defer()
        
        try:
            async with DatabaseService.get_transaction() as session:
                player = await PlayerService.get_player_with_regen(
                    session, ctx.author.id, lock=False
                )
                
                if not player:
                    embed = EmbedBuilder.error(
                        title="Not Registered",
                        description="You need to register first!",
                        help_text="Use `/register` to create your account."
                    )
                    await ctx.send(embed=embed, ephemeral=True)
                    return
                
                # Initiate floor
                combat_data = await AscensionService.initiate_floor(session, player)

                # Log floor initiation
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

            # Build floor encounter embed
            embed = self._build_floor_embed(combat_data)
            
            # Create combat view
            view = AscensionCombatView(
                user_id=ctx.author.id,
                combat_data=combat_data
            )
            
            message = await ctx.send(embed=embed, view=view)
            view.set_message(message)
        
        except Exception as e:
            logger.error(f"Ascension command error: {e}", exc_info=True)
            embed = EmbedBuilder.error(
                title="Ascension Error",
                description="Failed to initiate floor encounter.",
                help_text="Please try again."
            )
            await ctx.send(embed=embed, ephemeral=True)
    
    def _build_floor_embed(self, combat_data: Dict[str, Any]) -> discord.Embed:
        """Build floor encounter embed."""
        floor = combat_data["floor"]
        monster = combat_data["monster"]
        player_stats = combat_data["player_stats"]
        strategic = combat_data["strategic_power"]
        
        # Determine color by floor
        if floor <= 25:
            color = 0x808080  # Gray
        elif floor <= 50:
            color = 0x00FF00  # Green
        elif floor <= 100:
            color = 0x0099FF  # Blue
        elif floor <= 150:
            color = 0x9932CC  # Purple
        else:
            color = 0xFF4500  # Orange Red
        
        embed = discord.Embed(
            title=f"🗼 FLOOR {floor} APPROACH",
            color=color
        )
        
        # Monster info
        element_emoji = CombatService.get_element_emoji(monster["element"])
        embed.add_field(
            name=f"⚔️ {monster['name']}",
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
            name="💪 Your Stats",
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
                name="✨ Active Generals",
                value=bonus_text,
                inline=False
            )
        
        # Combat gauges
        embed.add_field(
            name="⚡ Combat Status",
            value=(
                f"**Critical Gauge:** ░░░░░░░░░░ 0%\n"
                f"**Momentum:** ░░░░░░░░░░ 0%"
            ),
            inline=False
        )
        
        # Milestone indicator
        if monster.get("is_milestone"):
            embed.add_field(
                name="🏆 MILESTONE BOSS",
                value=(
                    f"Special mechanics active!\n"
                    f"Extra rewards on victory!"
                ),
                inline=False
            )
        
        embed.set_footer(text="Strategic Combat | Best 6 Maidens (One Per Element)")
        
        return embed


class AscensionCombatView(discord.ui.View):
    """Interactive combat view with attack buttons."""
    
    def __init__(self, user_id: int, combat_data: Dict[str, Any]):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.combat_data = combat_data
        self.message: Optional[discord.Message] = None
    
    def set_message(self, message: discord.Message):
        self.message = message
    
    @discord.ui.button(
        label="⚔️ Attack x1",
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
        label="⚔️⚔️ Attack x3",
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
        label="💥 Attack x10",
        style=discord.ButtonStyle.danger,
        custom_id="ascension_x10"
    )
    async def attack_x10(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        """Execute x10 attack (10 stamina + 10 gems)."""
        await self._execute_attack(interaction, "x10")
    
    @discord.ui.button(
        label="🚪 Retreat",
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
            title="🚪 Retreated",
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

        try:
            # Acquire Redis lock to prevent double-clicks
            floor_id = self.combat_data["floor"]
            lock_key = f"ascension_combat:{self.user_id}:{floor_id}"

            async with RedisService.acquire_lock(lock_key, timeout=5):
                async with DatabaseService.get_transaction() as session:
                    player = await PlayerService.get_player_with_regen(
                        session, self.user_id, lock=True
                    )

                    # Execute attack turn
                    result = await AscensionService.execute_attack_turn(
                        session=session,
                        player=player,
                        monster=self.combat_data["monster"],
                        attack_type=attack_type,
                        combat_state=self.combat_data["combat_state"]
                    )

                    # Log attack action
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
                            "gem_cost": result.get("gem_cost", 0),
                        },
                        context=f"ascension:floor_{self.combat_data['floor']}"
                    )

                # Update monster HP
                self.combat_data["monster"]["hp"] = result["boss_hp"]
                self.combat_data["combat_state"]["player_hp"] = result["player_hp"]
                self.combat_data["combat_state"]["critical_gauge"] = result["critical_gauge"]
                self.combat_data["combat_state"]["momentum"] = result["momentum"]
                self.combat_data["combat_state"]["turns_taken"] = result["turns_taken"]

                # Check outcome
                if result["victory"]:
                    # Victory!
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

                        # Log victory
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
                    # Defeated!
                    async with DatabaseService.get_transaction() as session:
                        # Log defeat
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
                    # Continue combat
                    embed = self._build_combat_turn_embed(result)
                    await interaction.edit_original_response(embed=embed, view=self)
        
        except InsufficientResourcesError as e:
            embed = EmbedBuilder.error(
                title="Insufficient Resources",
                description=str(e),
                help_text="You don't have enough resources for this attack."
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        
        except Exception as e:
            logger.error(f"Attack execution error: {e}", exc_info=True)
            embed = EmbedBuilder.error(
                title="Combat Error",
                description="Failed to execute attack.",
                help_text="Please try again."
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    def _build_combat_turn_embed(self, result: Dict[str, Any]) -> discord.Embed:
        """Build combat turn result embed."""
        monster = self.combat_data["monster"]
        
        embed = discord.Embed(
            title=f"⚔️ TURN {result['turns_taken']}",
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
            momentum_status = " 💥 MAXIMUM!"
        elif momentum >= 50:
            momentum_status = " 🔥 BLAZING!"
        elif momentum >= 30:
            momentum_status = " ⚡ RISING!"
        
        embed.add_field(
            name="⚡ Combat Status",
            value=(
                f"**Critical Gauge:** {crit_bar} {crit_gauge}%\n"
                f"**Momentum:** {momentum_bar} {momentum}%{momentum_status}"
            ),
            inline=False
        )
        
        embed.set_footer(text=f"Stamina: {result['stamina_cost']} | Gems: {result['gem_cost']}")
        
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
            title="🏆 VICTORY!",
            description=f"**Floor {floor} Cleared!**",
            color=0x00FF00
        )
        
        # Combat stats
        embed.add_field(
            name="⚔️ Combat Stats",
            value=(
                f"**Damage Dealt:** {combat_result['player_damage']:,}\n"
                f"**Damage Taken:** {combat_result['boss_damage']:,}\n"
                f"**Turns:** {combat_result['turns_taken']}"
            ),
            inline=True
        )
        
        # Rewards
        reward_text = f"**+{rewards['rikis']:,}** Rikis\n**+{rewards['xp']}** XP"
        if rewards.get("token"):
            token_data = rewards["token"]
            from src.features.ascension.constants import TOKEN_TIERS
            token_info = TOKEN_TIERS[token_data["type"]]
            reward_text += f"\n{token_info['emoji']} **{token_info['name']}** x{token_data['quantity']}"
        
        embed.add_field(
            name="💰 Rewards",
            value=reward_text,
            inline=True
        )
        
        # Record indicator
        if victory_result["is_record"]:
            embed.add_field(
                name="🎉 NEW RECORD!",
                value=f"Highest floor reached: **{floor}**",
                inline=False
            )
        
        # Milestone bonus
        if rewards.get("milestone_bonus"):
            bonus_text = "\n".join(
                f"**{k}:** {v}" for k, v in rewards["milestone_bonus"].items()
            )
            embed.add_field(
                name="🏆 Milestone Bonus",
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
        """Disable buttons on timeout."""
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
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