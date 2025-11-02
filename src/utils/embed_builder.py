# src/utils/embed_builder.py
"""
Factory for standardized Discord embeds across RIKI systems.

Features:
- Consistent branding and colors (from maiden_constants)
- Type-safe embed creation
- Automatic Discord limits enforcement
- Specialized builders for common patterns
- Element/tier-aware coloring

Integration:
- Uses EmbedColor from maiden_constants for consistency
- Enforces Discord embed limits (title, description, fields)
- Provides helpers for common embed patterns
"""

import discord
from datetime import datetime
from typing import Optional, List, Dict, Any

from src.utils.maiden_constants import EmbedColor, UIConstants


class EmbedBuilder:
    """
    Factory for standardized Discord embeds across RIKI systems.

    Ensures consistent branding, tone, and hierarchy.
    All embeds automatically include timestamps and enforce Discord limits.
    """

    @staticmethod
    def _base_embed(
        title: str,
        description: str,
        color: int,
        footer: Optional[str] = None
    ) -> discord.Embed:
        """
        Create base embed with automatic limit enforcement.
        
        Args:
            title: Embed title (max 256 chars)
            description: Embed description (max 4096 chars)
            color: Discord color integer
            footer: Optional footer text (max 2048 chars)
        
        Returns:
            Discord Embed object
        """
        # Enforce Discord limits
        title = UIConstants.truncate_text(title, UIConstants.EMBED_TITLE_LIMIT)
        description = UIConstants.truncate_text(description, UIConstants.EMBED_DESCRIPTION_LIMIT)
        
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.utcnow()
        )
        
        if footer:
            footer = UIConstants.truncate_text(footer, UIConstants.EMBED_FOOTER_LIMIT)
            embed.set_footer(text=footer)
        
        return embed

    # =========================================================================
    # CORE TYPES
    # =========================================================================
    
    @staticmethod
    def primary(
        title: str,
        description: str,
        footer: Optional[str] = None
    ) -> discord.Embed:
        """Default embed for neutral/system messages."""
        return EmbedBuilder._base_embed(
            title, description, EmbedColor.DEFAULT, footer
        )

    @staticmethod
    def success(
        title: str,
        description: str,
        footer: Optional[str] = None
    ) -> discord.Embed:
        """Positive actions (rewards, victories, confirmations)."""
        return EmbedBuilder._base_embed(
            title, description, EmbedColor.SUCCESS, footer
        )

    @staticmethod
    def error(
        title: str,
        description: str,
        help_text: Optional[str] = None
    ) -> discord.Embed:
        """
        Error embeds with optional help text.
        
        Args:
            title: Error title
            description: Error description
            help_text: Optional helpful suggestion for user
        """
        desc = description
        if help_text:
            desc += f"\n\n💡 **Help:** {help_text}"
        return EmbedBuilder._base_embed(title, desc, EmbedColor.ERROR)

    @staticmethod
    def warning(
        title: str,
        description: str,
        footer: Optional[str] = None
    ) -> discord.Embed:
        """For recoverable issues or alerts."""
        return EmbedBuilder._base_embed(
            title, description, EmbedColor.WARNING, footer
        )

    @staticmethod
    def info(
        title: str,
        description: str,
        footer: Optional[str] = None
    ) -> discord.Embed:
        """Informational messages."""
        return EmbedBuilder._base_embed(
            title, description, EmbedColor.INFO, footer
        )

    # =========================================================================
    # GAME-SPECIFIC TYPES
    # =========================================================================
    
    @staticmethod
    def fusion_success(
        title: str,
        description: str,
        footer: Optional[str] = None
    ) -> discord.Embed:
        """Successful fusion embeds."""
        return EmbedBuilder._base_embed(
            title, description, EmbedColor.FUSION_SUCCESS, footer
        )
    
    @staticmethod
    def fusion_fail(
        title: str,
        description: str,
        footer: Optional[str] = None
    ) -> discord.Embed:
        """Failed fusion embeds."""
        return EmbedBuilder._base_embed(
            title, description, EmbedColor.FUSION_FAIL, footer
        )
    
    @staticmethod
    def summon(
        title: str,
        description: str,
        footer: Optional[str] = None
    ) -> discord.Embed:
        """Summon/gacha embeds."""
        return EmbedBuilder._base_embed(
            title, description, EmbedColor.SUMMON, footer
        )
    
    @staticmethod
    def level_up(
        title: str,
        description: str,
        footer: Optional[str] = None
    ) -> discord.Embed:
        """Level up celebration embeds."""
        return EmbedBuilder._base_embed(
            title, description, EmbedColor.LEVEL_UP, footer
        )
    
    @staticmethod
    def prayer(
        title: str,
        description: str,
        footer: Optional[str] = None
    ) -> discord.Embed:
        """Prayer system embeds."""
        return EmbedBuilder._base_embed(
            title, description, EmbedColor.PRAYER, footer
        )
    
    @staticmethod
    def ascension(
        title: str,
        description: str,
        footer: Optional[str] = None
    ) -> discord.Embed:
        """Ascension tower embeds."""
        return EmbedBuilder._base_embed(
            title, description, EmbedColor.ASCENSION, footer
        )

    # =========================================================================
    # CONTEXT-AWARE EMBEDS
    # =========================================================================
    
    @staticmethod
    def for_element(
        element: str,
        title: str,
        description: str,
        footer: Optional[str] = None
    ) -> discord.Embed:
        """Create embed with element-specific color."""
        color = EmbedColor.get_element_color(element)
        return EmbedBuilder._base_embed(title, description, color, footer)
    
    @staticmethod
    def for_tier(
        tier: int,
        title: str,
        description: str,
        footer: Optional[str] = None
    ) -> discord.Embed:
        """Create embed with tier-specific color."""
        color = EmbedColor.get_tier_color(tier)
        return EmbedBuilder._base_embed(title, description, color, footer)

    # =========================================================================
    # SPECIALIZED BUILDERS
    # =========================================================================
    
    @staticmethod
    def player_stats(player, title: str = "Player Profile") -> discord.Embed:
        """
        Detailed player profile display.
        
        Args:
            player: Player model instance
            title: Optional custom title
        
        Returns:
            Formatted player stats embed
        """
        player_class = getattr(player, "player_class", None) or "Adventurer"
        
        embed = discord.Embed(
            title=title,
            description=f"**Level {player.level} {player_class}**",
            color=EmbedColor.DEFAULT,
            timestamp=datetime.utcnow()
        )

        # Resource summary
        gems = getattr(player, "riki_gems", 0)
        embed.add_field(
            name="💰 Resources",
            value=(
                f"Rikis: **{UIConstants.format_number(player.rikis)}**\n"
                f"Grace: **{player.grace}**\n"
                f"Gems: **{gems}**"
            ),
            inline=True
        )

        # Energy & stamina
        embed.add_field(
            name="⚡ Energy & Stamina",
            value=(
                f"Energy: **{player.energy}/{player.max_energy}**\n"
                f"Stamina: **{player.stamina}/{player.max_stamina}**"
            ),
            inline=True
        )

        # Prayer
        next_regen = getattr(player, "get_prayer_regen_display", lambda: "N/A")
        next_regen_str = next_regen() if callable(next_regen) else "N/A"
        
        embed.add_field(
            name="🙏 Prayer Charges",
            value=(
                f"**{player.prayer_charges}/{player.max_prayer_charges}**\n"
                f"Next Regen: {next_regen_str}"
            ),
            inline=True
        )

        # Progression
        xp = getattr(player, "experience", 0)
        total_power = getattr(player, "total_power", 0)
        
        embed.add_field(
            name="📈 Progression",
            value=(
                f"XP: **{UIConstants.format_number(xp)}**\n"
                f"Total Power: **{UIConstants.format_number(total_power)}**"
            ),
            inline=False
        )

        # Collection stats
        total_maidens = getattr(player, "total_maidens_owned", 0)
        unique_maidens = getattr(player, "unique_maidens", 0)
        
        embed.add_field(
            name="🎴 Collection",
            value=(
                f"Total Maidens: **{total_maidens}**\n"
                f"Unique: **{unique_maidens}**"
            ),
            inline=True
        )

        embed.set_footer(text="RIKI RPG • Goddess blesses the prepared")
        return embed
    
    @staticmethod
    def resource_display(
        title: str,
        resources: Dict[str, int],
        description: Optional[str] = None,
        footer: Optional[str] = None
    ) -> discord.Embed:
        """
        Display resource amounts (rewards, costs, etc).
        
        Args:
            title: Embed title
            resources: Dict of resource names to amounts
            description: Optional description
            footer: Optional footer
        
        Returns:
            Formatted resource embed
        """
        embed = EmbedBuilder.primary(
            title=title,
            description=description or "",
            footer=footer
        )
        
        # Format resources
        resource_emojis = {
            "rikis": "💰",
            "grace": "✨",
            "riki_gems": "💎",
            "energy": "⚡",
            "stamina": "🔋",
            "prayer_charges": "🙏",
            "experience": "📈"
        }
        
        resource_lines = []
        for resource, amount in resources.items():
            emoji = resource_emojis.get(resource, "•")
            resource_name = resource.replace("_", " ").title()
            formatted_amount = UIConstants.format_number(amount)
            resource_lines.append(f"{emoji} **{resource_name}:** {formatted_amount}")
        
        if resource_lines:
            embed.add_field(
                name="Resources",
                value="\n".join(resource_lines),
                inline=False
            )
        
        return embed
    
    @staticmethod
    def paginated_list(
        title: str,
        items: List[str],
        page: int,
        total_pages: int,
        description: Optional[str] = None,
        footer: Optional[str] = None
    ) -> discord.Embed:
        """
        Create paginated list embed.
        
        Args:
            title: Embed title
            items: List of item strings to display
            page: Current page number (1-indexed)
            total_pages: Total number of pages
            description: Optional description
            footer: Optional footer (page info appended)
        
        Returns:
            Paginated embed
        """
        page_footer = f"Page {page}/{total_pages}"
        if footer:
            page_footer = f"{footer} • {page_footer}"
        
        # Combine items into description
        items_text = "\n".join(items) if items else "No items to display"
        full_description = f"{description}\n\n{items_text}" if description else items_text
        
        return EmbedBuilder.primary(
            title=title,
            description=full_description,
            footer=page_footer
        )
    
    @staticmethod
    def battle_result(
        victory: bool,
        title: str,
        description: str,
        stats: Optional[Dict[str, Any]] = None,
        footer: Optional[str] = None
    ) -> discord.Embed:
        """
        Create battle result embed.
        
        Args:
            victory: Whether battle was won
            title: Embed title
            description: Battle description
            stats: Optional battle stats dict
            footer: Optional footer
        
        Returns:
            Victory or defeat embed
        """
        color = EmbedColor.SUCCESS if victory else EmbedColor.ERROR
        embed = EmbedBuilder._base_embed(title, description, color, footer)
        
        if stats:
            for stat_name, stat_value in stats.items():
                embed.add_field(
                    name=stat_name.replace("_", " ").title(),
                    value=str(stat_value),
                    inline=True
                )
        
        return embed

    # =========================================================================
    # HELPERS
    # =========================================================================
    
    @staticmethod
    def add_fields_safe(
        embed: discord.Embed,
        fields: List[Dict[str, Any]],
        max_fields: int = 25
    ) -> int:
        """
        Safely add fields to embed with limit checking.
        
        Args:
            embed: Discord embed to add fields to
            fields: List of dicts with 'name', 'value', 'inline' keys
            max_fields: Maximum fields to add (Discord limit is 25)
        
        Returns:
            Number of fields actually added
        """
        added = 0
        for field in fields:
            if len(embed.fields) >= max_fields:
                break
            
            name = UIConstants.truncate_text(
                field.get("name", "Field"),
                UIConstants.EMBED_FIELD_LIMIT
            )
            value = UIConstants.truncate_text(
                field.get("value", "No value"),
                UIConstants.EMBED_FIELD_LIMIT
            )
            inline = field.get("inline", False)
            
            embed.add_field(name=name, value=value, inline=inline)
            added += 1
        
        return added
