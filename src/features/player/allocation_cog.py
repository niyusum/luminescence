"""
Stat allocation command interface.

Allows players to allocate stat points to Energy, Stamina, or HP.

RIKI LAW Compliance:
- Article VI: Discord layer only handles UI
- Article VII: No business logic in cog
- Article I.5: Specific exception handling
"""

import discord
from discord.ext import commands
from typing import Optional

from src.core.database_service import DatabaseService
from src.features.player.service import PlayerService
from src.features.player.allocation_service import AllocationService
from src.database.models.core.player import Player
from src.core.exceptions import InvalidOperationError
from src.core.logger import get_logger
from src.utils.decorators import ratelimit
from utils.embed_builder import EmbedBuilder

logger = get_logger(__name__)


class AllocationCog(commands.Cog):
    """
    Stat allocation system.
    
    Players allocate points earned from leveling to Energy, Stamina, or HP.
    """
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    @commands.hybrid_command(
        name="allocate",
        aliases=["stats", "alloc"],
        description="Allocate stat points to Energy, Stamina, or HP"
    )
    @ratelimit(uses=10, per_seconds=60, command_name="allocate")
    async def allocate(self, ctx: commands.Context):
        """View stat allocation interface."""
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
                
                # Check if player has points
                if player.stat_points_available == 0:
                    embed = EmbedBuilder.warning(
                        title="No Points Available",
                        description="You don't have any stat points to allocate!",
                        footer="Gain 5 points per level up"
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
                    footer="Gain 5 points per level | Full refresh on level up"
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
                
                # Allocation ratios
                embed.add_field(
                    name="Per Point Gain",
                    value=(
                        f"⚡ +{Player.ENERGY_PER_POINT} Energy\n"
                        f"💪 +{Player.STAMINA_PER_POINT} Stamina\n"
                        f"❤️ +{Player.HP_PER_POINT} HP"
                    ),
                    inline=True
                )
                
                # Total spent
                total_spent = spent["energy"] + spent["stamina"] + spent["hp"]
                embed.add_field(
                    name="Total Allocated",
                    value=(
                        f"⚡ {spent['energy']} to Energy\n"
                        f"💪 {spent['stamina']} to Stamina\n"
                        f"❤️ {spent['hp']} to HP\n"
                        f"**Total:** {total_spent} points"
                    ),
                    inline=False
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
                await ctx.send(embed=embed, view=view)
        
        except Exception as e:
            logger.error(f"Allocation command error: {e}", exc_info=True)
            embed = EmbedBuilder.error(
                title="Allocation Error",
                description="Failed to load allocation interface.",
                help_text="Please try again."
            )
            await ctx.send(embed=embed, ephemeral=True)


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
            # Parse input
            energy_pts = int(self.energy.value or 0)
            stamina_pts = int(self.stamina.value or 0)
            hp_pts = int(self.hp.value or 0)
            
            # Validate
            if energy_pts < 0 or stamina_pts < 0 or hp_pts < 0:
                raise ValueError("Cannot allocate negative points")
            
            total = energy_pts + stamina_pts + hp_pts
            if total == 0:
                raise ValueError("Must allocate at least 1 point")
            
            if total > self.available_points:
                raise ValueError(
                    f"Insufficient points. Have {self.available_points}, "
                    f"trying to spend {total}"
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
            
            # Success embed
            embed = EmbedBuilder.success(
                title="✅ Stats Allocated!",
                description=f"Successfully spent {total} points"
            )
            
            # Show changes
            new_max = result["new_max_stats"]
            embed.add_field(
                name="New Max Stats",
                value=(
                    f"⚡ **Energy:** {new_max['max_energy']} "
                    f"(+{energy_pts * Player.ENERGY_PER_POINT})\n"
                    f"💪 **Stamina:** {new_max['max_stamina']} "
                    f"(+{stamina_pts * Player.STAMINA_PER_POINT})\n"
                    f"❤️ **HP:** {new_max['max_hp']} "
                    f"(+{hp_pts * Player.HP_PER_POINT})"
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
        
        except Exception as e:
            logger.error(f"Allocation modal error: {e}", exc_info=True)
            embed = EmbedBuilder.error(
                title="Allocation Error",
                description="An unexpected error occurred.",
                help_text="Please try again."
            )
            await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AllocationCog(bot))