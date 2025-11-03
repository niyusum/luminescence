"""
Exploration and Matron combat interface.

RIKI LAW Compliance:
- Article VI: Discord layer only
- Article VII: No business logic
"""

import discord
from discord.ext import commands
from typing import Optional, Dict, Any

from src.core.database_service import DatabaseService
from src.features.player.service import PlayerService
from src.features.exploration.matron_service import MatronService
from src.features.combat.service import CombatService
from src.core.exceptions import InsufficientResourcesError, InvalidOperationError
from src.core.logger import get_logger
from src.utils.decorators import ratelimit
from utils.embed_builder import EmbedBuilder

logger = get_logger(__name__)


class ExplorationCog(commands.Cog):
    """
    Exploration and Matron combat system.
    
    Speed-based combat with turn limits. No retaliation.
    """
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    @commands.hybrid_command(
        name="matron",
        aliases=["boss", "mb"],
        description="Challenge a sector Matron (speed combat)"
    )
    @ratelimit(uses=10, per_seconds=60, command_name="matron")
    async def matron(
        self,
        ctx: commands.Context,
        sector: int,
        sublevel: int
    ):
        """Challenge Matron boss."""
        await ctx.defer()
        
        # Validate input
        if sector < 1 or sector > 6:
            embed = EmbedBuilder.error(
                title="Invalid Sector",
                description="Sector must be between 1 and 6.",
                help_text="Example: `/matron 1 9`"
            )
            await ctx.send(embed=embed, ephemeral=True)
            return
        
        if sublevel < 1 or sublevel > 9:
            embed = EmbedBuilder.error(
                title="Invalid Sublevel",
                description="Sublevel must be between 1 and 9.",
                help_text="Example: `/matron 1 9`"
            )
            await ctx.send(embed=embed, ephemeral=True)
            return
        
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
                
                # Generate matron
                matron = MatronService.generate_matron(sector, sublevel)
                
                # Get player power (total, not strategic)
                player_power = await CombatService.calculate_total_power(
                    session, player.discord_id, include_leader_bonus=True
                )
            
            # Build matron encounter embed
            embed = self._build_matron_embed(matron, player_power)
            
            # Create combat view
            view = MatronCombatView(
                user_id=ctx.author.id,
                matron=matron,
                player_power=player_power
            )
            
            message = await ctx.send(embed=embed, view=view)
            view.set_message(message)
        
        except Exception as e:
            logger.error(f"Matron command error: {e}", exc_info=True)
            embed = EmbedBuilder.error(
                title="Matron Error",
                description="Failed to initiate matron encounter.",
                help_text="Please try again."
            )
            await ctx.send(embed=embed, ephemeral=True)
    
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
            color=0x9932CC
        )
        
        # Matron info
        embed.add_field(
            name=f"⚔️ {matron['name']}",
            value=(
                f"{element_emoji} **{matron['element'].title()}**\n"
                f"**HP:** {matron['hp']:,}"
            ),
            inline=True
        )
        
        # Player power
        embed.add_field(
            name="💪 Your Total Power",
            value=f"{player_power:,}",
            inline=True
        )
        
        # Turn info
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
        
        # Rewards preview
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


class MatronCombatView(discord.ui.View):
    """Interactive matron combat view."""
    
    def __init__(
        self,
        user_id: int,
        matron: Dict[str, Any],
        player_power: int
    ):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.matron = matron
        self.player_power = player_power
        self.turn_count = 0
        self.message: Optional[discord.Message] = None
    
    def set_message(self, message: discord.Message):
        self.message = message
    
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
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This battle is not yours!",
                ephemeral=True
            )
            return
        
        await interaction.response.defer()
        
        try:
            self.turn_count += 1
            
            async with DatabaseService.get_transaction() as session:
                player = await PlayerService.get_player_with_regen(
                    session, self.user_id, lock=True
                )
                
                # Execute attack
                result = await MatronService.attack_matron(
                    session=session,
                    player=player,
                    matron=self.matron,
                    attack_type=attack_type,
                    turn_count=self.turn_count
                )
            
            # Update matron HP
            self.matron["hp"] = result["matron_hp"]
            
            # Check outcome
            if result["victory"]:
                # Victory!
                embed = self._build_victory_embed(result)
                await interaction.edit_original_response(embed=embed, view=None)
            
            elif result["dismissed"]:
                # Dismissed!
                embed = self._build_dismissal_embed(result)
                await interaction.edit_original_response(embed=embed, view=None)
            
            else:
                # Continue combat
                embed = self._build_turn_embed(result)
                
                # Warning at turn limit - 2
                if self.turn_count >= self.matron["turn_limit"] - 2:
                    for item in self.children:
                        if isinstance(item, discord.ui.Button):
                            item.style = discord.ButtonStyle.danger
                
                await interaction.edit_original_response(embed=embed, view=self)
        
        except InsufficientResourcesError as e:
            embed = EmbedBuilder.error(
                title="Insufficient Resources",
                description=str(e),
                help_text="You don't have enough resources for this attack."
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        
        except Exception as e:
            logger.error(f"Matron attack error: {e}", exc_info=True)
            embed = EmbedBuilder.error(
                title="Combat Error",
                description="Failed to execute attack.",
                help_text="Please try again."
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    def _build_turn_embed(self, result: Dict[str, Any]) -> discord.Embed:
        """Build turn result embed."""
        embed = discord.Embed(
            title=f"⚔️ TURN {result['turns_taken']}",
            color=0x0099FF
        )
        
        # Damage dealt
        embed.add_field(
            name="Damage Dealt",
            value=f"⚔️ {result['damage_dealt']:,}",
            inline=True
        )
        
        # Matron HP
        hp_bar = CombatService.render_hp_bar(
            result["matron_hp"], self.matron["max_hp"], width=10
        )
        embed.add_field(
            name="Matron HP",
            value=f"{hp_bar} {result['matron_hp']:,}/{self.matron['max_hp']:,}",
            inline=True
        )
        
        # Turn status
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
            value=(
                f"**Turns:** {turns} / {optimal} (Optimal)\n"
                f"**Turn Limit:** {turn_limit}\n"
                f"{status}"
            ),
            inline=False
        )
        
        embed.set_footer(
            text=f"Stamina: {result['stamina_cost']} | Gems: {result['gem_cost']}"
        )
        
        return embed
    
    def _build_victory_embed(self, result: Dict[str, Any]) -> discord.Embed:
        """Build victory embed."""
        rewards = result["rewards"]
        turn_bonus = rewards["turn_bonus"]
        
        bonus_emoji = {
            "perfect": "⭐",
            "fast": "🏃",
            "standard": "✅",
            "slow": "🐌"
        }
        
        bonus_text = {
            "perfect": "PERFECT CLEAR! (+100% rewards)",
            "fast": "FAST CLEAR! (+50% rewards)",
            "standard": "CLEAR (base rewards)",
            "slow": "SLOW CLEAR (-50% rewards)"
        }
        
        embed = discord.Embed(
            title="🏆 MATRON DEFEATED!",
            description=f"{self.matron['name']} has been conquered!",
            color=0x00FF00
        )
        
        # Turn performance
        embed.add_field(
            name=f"{bonus_emoji[turn_bonus]} {bonus_text[turn_bonus]}",
            value=f"**Turns Used:** {result['turns_taken']}",
            inline=False
        )
        
        # Rewards
        reward_text = f"**+{rewards['rikis']:,}** Rikis\n**+{rewards['xp']}** XP"
        
        if rewards.get("sector_clear_bonus"):
            bonus = rewards["sector_clear_bonus"]
            reward_text += f"\n\n**🏆 Sector Boss Bonus:**"
            reward_text += f"\n+{bonus['rikis']:,} Rikis"
            reward_text += f"\n🥈 Silver Token x1"
        
        embed.add_field(
            name="💰 Rewards",
            value=reward_text,
            inline=False
        )
        
        embed.set_footer(text="Matron defeated | Sector progress saved")
        
        return embed
    
    def _build_dismissal_embed(self, result: Dict[str, Any]) -> discord.Embed:
        """Build dismissal embed."""
        embed = discord.Embed(
            title="💨 DISMISSED",
            description=result["dismissal_text"],
            color=0x808080
        )
        
        # Combat stats
        embed.add_field(
            name="Combat Stats",
            value=(
                f"**Damage Dealt:** {result['damage_dealt']:,}\n"
                f"**Matron HP Remaining:** {result['matron_hp']:,}\n"
                f"**Turns Used:** {result['turns_taken']}"
            ),
            inline=False
        )
        
        # No rewards
        embed.add_field(
            name="❌ No Rewards",
            value=(
                f"Stamina consumed: {result['stamina_cost']}\n"
                f"Gems consumed: {result['gem_cost']}"
            ),
            inline=False
        )
        
        # Tips
        embed.add_field(
            name="💡 Tips",
            value=(
                "• Upgrade your maiden collection\n"
                "• Use higher attack multipliers (x3, x10)\n"
                "• Allocate more stamina for more attempts\n"
                "• Set a leader for income boost"
            ),
            inline=False
        )
        
        embed.set_footer(text="Better luck next time!")
        
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


async def setup(bot: commands.Bot):
    await bot.add_cog(ExplorationCog(bot))