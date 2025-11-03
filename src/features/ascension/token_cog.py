"""
Token management and redemption interface.

RIKI LAW Compliance:
- Article VI: Discord layer only
- Article VII: No business logic
"""

import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional, List

from src.core.infra.database_service import DatabaseService
from src.features.player.service import PlayerService
from src.features.ascension.token_service import TokenService
from src.features.ascension.constants import (
    TOKEN_TIERS,
    get_all_token_types
)
from src.features.maiden.constants import Element
from src.core.exceptions import InsufficientResourcesError, InvalidOperationError
from src.core.logging.logger import get_logger
from src.utils.decorators import ratelimit
from utils.embed_builder import EmbedBuilder

logger = get_logger(__name__)


class TokenCog(commands.Cog):
    """
    Token inventory and redemption system.
    
    Tokens earned from ascension tower, redeemed for random maidens.
    Each token type has a specific tier range for maiden summons.
    """
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    # ===============================================================
    # Token Inventory Command
    # ===============================================================
    @commands.hybrid_command(
        name="tokens",
        aliases=["token", "tk"],
        description="View your token inventory"
    )
    @ratelimit(uses=10, per_seconds=60, command_name="tokens")
    async def tokens(self, ctx: commands.Context):
        """Display token inventory with redemption info."""
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
                
                # Get token inventory
                inventory = await TokenService.get_player_tokens(
                    session, player.discord_id
                )
            
            # Build inventory embed
            embed = discord.Embed(
                title="🎫 Token Inventory",
                description=(
                    "Redeem tokens for random maidens!\n"
                    "Higher tier tokens = Higher tier maidens"
                ),
                color=0xFFD700
            )
            
            total_tokens = sum(inventory.values())
            has_tokens = False
            
            # Display each token type
            for token_type in get_all_token_types():
                token_data = TOKEN_TIERS[token_type]
                quantity = inventory.get(token_type, 0)
                tier_range = token_data["tier_range"]
                
                if quantity > 0:
                    has_tokens = True
                
                # Use checkmark or X based on quantity
                status = "✅" if quantity > 0 else "❌"
                
                embed.add_field(
                    name=f"{status} {token_data['emoji']} {token_data['name']}",
                    value=(
                        f"**Quantity:** {quantity}\n"
                        f"**Tier Range:** T{tier_range[0]}-T{tier_range[1]}\n"
                        f"*{token_data['description']}*"
                    ),
                    inline=True
                )
            
            # Total tokens summary
            embed.add_field(
                name="📊 Summary",
                value=f"**Total Tokens:** {total_tokens}",
                inline=False
            )
            
            # Help text based on whether user has tokens
            if has_tokens:
                embed.add_field(
                    name="💡 How to Redeem",
                    value=(
                        "Use `/redeem <token_type>` to redeem!\n"
                        "Example: `/redeem bronze`"
                    ),
                    inline=False
                )
            else:
                embed.add_field(
                    name="💡 How to Earn Tokens",
                    value=(
                        "Clear ascension tower floors to earn tokens!\n"
                        "• Floors 1-10: Bronze tokens\n"
                        "• Floors 11-25: Bronze/Silver mix\n"
                        "• Floors 26+: Higher tier tokens\n\n"
                        "Use `/ascend` to climb the tower!"
                    ),
                    inline=False
                )
            
            embed.set_footer(text=f"Player: {ctx.author.name}")
            embed.timestamp = discord.utils.utcnow()
            
            await ctx.send(embed=embed)
        
        except Exception as e:
            logger.error(f"Tokens command error for {ctx.author.id}: {e}", exc_info=True)
            embed = EmbedBuilder.error(
                title="Token Error",
                description="Failed to load token inventory.",
                help_text="Please try again."
            )
            await ctx.send(embed=embed, ephemeral=True)
    
    # ===============================================================
    # Token Redemption Command
    # ===============================================================
    @commands.hybrid_command(
        name="redeem",
        aliases=["use_token"],
        description="Redeem a token for a random maiden"
    )
    @app_commands.describe(token_type="Type of token to redeem (bronze, silver, gold, platinum, diamond)")
    @ratelimit(uses=10, per_seconds=60, command_name="redeem")
    async def redeem(
        self,
        ctx: commands.Context,
        token_type: str
    ):
        """Redeem token for random maiden in tier range."""
        await ctx.defer()
        
        token_type = token_type.lower()
        
        # Validate token type
        if token_type not in TOKEN_TIERS:
            valid_types = ", ".join(get_all_token_types())
            embed = EmbedBuilder.error(
                title="Invalid Token Type",
                description=f"❌ `{token_type}` is not a valid token type.",
                help_text=f"Valid types: **{valid_types}**\nExample: `/redeem bronze`"
            )
            await ctx.send(embed=embed, ephemeral=True)
            return
        
        try:
            async with DatabaseService.get_transaction() as session:
                player = await PlayerService.get_player_with_regen(
                    session, ctx.author.id, lock=True
                )
                
                if not player:
                    embed = EmbedBuilder.error(
                        title="Not Registered",
                        description="You need to register first!",
                        help_text="Use `/register` to create your account."
                    )
                    await ctx.send(embed=embed, ephemeral=True)
                    return
                
                # Redeem token
                result = await TokenService.redeem_token(
                    session=session,
                    player=player,
                    token_type=token_type
                )
                
                await session.commit()
            
            # Build success embed
            token_info = TOKEN_TIERS[token_type]
            maiden_base = result["maiden_base"]
            tier = result["tier"]
            tokens_remaining = result["tokens_remaining"]
            
            # Get element emoji
            element_obj = Element.from_string(maiden_base.element)
            element_emoji = element_obj.emoji if element_obj else "❓"
            element_name = element_obj.display_name if element_obj else maiden_base.element
            
            embed = discord.Embed(
                title="✨ Token Redeemed Successfully!",
                description=f"You used a **{token_info['name']}** {token_info['emoji']}",
                color=token_info["color"]
            )
            
            # Maiden info
            embed.add_field(
                name="🎴 Maiden Summoned",
                value=(
                    f"**{maiden_base.name}**\n"
                    f"{element_emoji} {element_name}\n"
                    f"**Tier {tier}**"
                ),
                inline=True
            )
            
            # Stats
            embed.add_field(
                name="📊 Base Stats",
                value=(
                    f"**ATK:** {maiden_base.base_atk:,}\n"
                    f"**DEF:** {maiden_base.base_def:,}"
                ),
                inline=True
            )
            
            # Remaining tokens
            embed.add_field(
                name="🎫 Tokens Remaining",
                value=(
                    f"{token_info['emoji']} **{token_info['name']}:** {tokens_remaining}"
                ),
                inline=False
            )
            
            embed.set_footer(text="Added to your collection! • Use /collection to view")
            embed.timestamp = discord.utils.utcnow()
            
            await ctx.send(embed=embed)
        
        except InsufficientResourcesError as e:
            token_info = TOKEN_TIERS[token_type]
            embed = EmbedBuilder.error(
                title="Insufficient Tokens",
                description=f"You don't have any {token_info['name']} {token_info['emoji']}!",
                help_text=(
                    "Earn tokens by clearing ascension tower floors.\n"
                    "Use `/tokens` to view your inventory."
                )
            )
            await ctx.send(embed=embed, ephemeral=True)
        
        except InvalidOperationError as e:
            embed = EmbedBuilder.error(
                title="Redemption Error",
                description=str(e),
                help_text="Please report this issue to support."
            )
            await ctx.send(embed=embed, ephemeral=True)
        
        except Exception as e:
            logger.error(f"Redeem command error for {ctx.author.id}: {e}", exc_info=True)
            embed = EmbedBuilder.error(
                title="Redemption Error",
                description="An unexpected error occurred while redeeming your token.",
                help_text="Please try again or contact support if this persists."
            )
            await ctx.send(embed=embed, ephemeral=True)
    
    # ===============================================================
    # Autocomplete for Redeem Command
    # ===============================================================
    @redeem.autocomplete("token_type")
    async def redeem_token_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str
    ) -> List[app_commands.Choice[str]]:
        """Autocomplete token types for redeem command."""
        token_types = get_all_token_types()
        
        # Filter based on current input
        if current:
            token_types = [
                t for t in token_types
                if current.lower() in t.lower()
            ]
        
        # Return as choices with emoji and name
        choices = []
        for token_type in token_types[:25]:  # Discord limit
            token_data = TOKEN_TIERS[token_type]
            choices.append(
                app_commands.Choice(
                    name=f"{token_data['emoji']} {token_data['name']}",
                    value=token_type
                )
            )
        
        return choices


async def setup(bot: commands.Bot):
    await bot.add_cog(TokenCog(bot))